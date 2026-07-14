"""XMODEM/YMODEM senders and serial-port transfer coordination."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import queue
import threading
import time
from typing import Callable, Literal

from serial_manager import MessageSource, SerialRawChunk, serial_manager


SOH = 0x01
STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CAN = 0x18
CRC_REQUEST = 0x43
SUB = 0x1A
DEFAULT_MAX_BATCH_FILES = 64
DEFAULT_MAX_FILE_SIZE = 32 * 1024 * 1024
DEFAULT_MAX_BATCH_SIZE = 64 * 1024 * 1024


class TransferError(RuntimeError):
    pass


class TransferCancelled(TransferError):
    pass


@dataclass(frozen=True)
class TransferResult:
    protocol: str
    bytes_sent: int
    blocks: int
    retries: int
    duration: float


@dataclass(frozen=True)
class ReceiveResult:
    protocol: str
    data: bytes
    filename: str
    blocks: int
    retries: int
    duration: float


@dataclass(frozen=True)
class BatchFile:
    filename: str
    data: bytes
    sha256: str


@dataclass(frozen=True)
class BatchReceiveResult:
    protocol: str
    files: tuple[BatchFile, ...]
    blocks: int
    retries: int
    duration: float


def _safe_ymodem_filename(filename: str) -> str:
    safe_name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if safe_name in {"", ".", ".."} or any(ord(char) < 32 for char in safe_name):
        raise TransferError("invalid YMODEM filename")
    return safe_name[:255]


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class XyModemSender:
    def __init__(
        self,
        write: Callable[[bytes], bool],
        read_byte: Callable[[float], int | None],
        cancel: threading.Event | None = None,
        progress: Callable[[int, int, int, int], None] | None = None,
        timeout: float = 10.0,
        retries: int = 10,
    ):
        self.write = write
        self.read_byte = read_byte
        self.cancel = cancel or threading.Event()
        self.progress = progress
        self.timeout = min(max(float(timeout), 0.2), 60.0)
        self.max_retries = min(max(int(retries), 1), 50)
        self.retry_count = 0

    def _check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise TransferCancelled("transfer cancelled")

    def _read_response(self, accepted: set[int], timeout: float | None = None) -> int | None:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        can_count = 0
        while time.monotonic() < deadline:
            self._check_cancelled()
            value = self.read_byte(min(0.2, max(0.01, deadline - time.monotonic())))
            if value is None:
                continue
            if value == CAN:
                can_count += 1
                if can_count >= 2:
                    raise TransferCancelled("receiver cancelled transfer")
                continue
            can_count = 0
            if value in accepted:
                return value
        return None

    def _wait_receiver(self, require_crc: bool = False) -> bool:
        accepted = {CRC_REQUEST} if require_crc else {CRC_REQUEST, NAK}
        for _ in range(self.max_retries):
            response = self._read_response(accepted)
            if response is not None:
                return response == CRC_REQUEST
            self.retry_count += 1
        raise TransferError("receiver did not start transfer")

    @staticmethod
    def _packet(block: int, payload: bytes, crc_mode: bool) -> bytes:
        if len(payload) not in (128, 1024):
            raise ValueError("payload must be 128 or 1024 bytes")
        header = SOH if len(payload) == 128 else STX
        body = bytes((header, block & 0xFF, 0xFF - (block & 0xFF))) + payload
        if crc_mode:
            crc = crc16_xmodem(payload)
            return body + bytes((crc >> 8, crc & 0xFF))
        return body + bytes((sum(payload) & 0xFF,))

    def _send_packet(self, block: int, payload: bytes, crc_mode: bool) -> None:
        packet = self._packet(block, payload, crc_mode)
        for attempt in range(self.max_retries + 1):
            self._check_cancelled()
            if not self.write(packet):
                raise TransferError("serial write failed")
            response = self._read_response({ACK, NAK})
            if response == ACK:
                return
            if attempt < self.max_retries:
                self.retry_count += 1
        raise TransferError(f"block {block} was not acknowledged")

    def _finish_eot(self, ymodem: bool = False) -> None:
        for attempt in range(self.max_retries + 1):
            self._check_cancelled()
            if not self.write(bytes((EOT,))):
                raise TransferError("serial write failed")
            response = self._read_response({ACK, NAK})
            if response == ACK:
                return
            if response == NAK and ymodem:
                if not self.write(bytes((EOT,))):
                    raise TransferError("serial write failed")
                if self._read_response({ACK}) == ACK:
                    return
            if attempt < self.max_retries:
                self.retry_count += 1
        raise TransferError("EOT was not acknowledged")

    def send_xmodem(self, data: bytes, block_size: Literal[128, 1024] = 128) -> TransferResult:
        started = time.monotonic()
        crc_mode = self._wait_receiver()
        total = len(data)
        blocks = 0
        for offset in range(0, total, block_size):
            chunk = data[offset:offset + block_size].ljust(block_size, bytes((SUB,)))
            blocks += 1
            self._send_packet(blocks, chunk, crc_mode)
            self.progress and self.progress(min(offset + block_size, total), total, blocks, self.retry_count)
        self._finish_eot()
        return TransferResult("xmodem", total, blocks, self.retry_count, time.monotonic() - started)

    def send_ymodem(self, data: bytes, filename: str) -> TransferResult:
        started = time.monotonic()
        self._wait_receiver(require_crc=True)
        safe_name = Path(filename).name.encode("ascii", errors="replace")[:100]
        metadata = safe_name + b"\0" + str(len(data)).encode("ascii") + b"\0"
        self._send_packet(0, metadata.ljust(128, b"\0"), True)
        if self._read_response({CRC_REQUEST}) != CRC_REQUEST:
            raise TransferError("receiver did not request file data")

        total = len(data)
        blocks = 0
        for offset in range(0, total, 1024):
            chunk = data[offset:offset + 1024].ljust(1024, bytes((SUB,)))
            blocks += 1
            self._send_packet(blocks, chunk, True)
            self.progress and self.progress(min(offset + 1024, total), total, blocks, self.retry_count)
        self._finish_eot(ymodem=True)
        if self._read_response({CRC_REQUEST}) != CRC_REQUEST:
            raise TransferError("receiver did not request end-of-batch block")
        self._send_packet(0, bytes(128), True)
        return TransferResult("ymodem", total, blocks, self.retry_count, time.monotonic() - started)


class XyModemReceiver:
    def __init__(
        self,
        write: Callable[[bytes], bool],
        read_byte: Callable[[float], int | None],
        cancel: threading.Event | None = None,
        progress: Callable[[int, int, int, int], None] | None = None,
        timeout: float = 10.0,
        retries: int = 10,
    ):
        self.write = write
        self.read_byte = read_byte
        self.cancel = cancel or threading.Event()
        self.progress = progress
        self.timeout = min(max(float(timeout), 0.2), 60.0)
        self.max_retries = min(max(int(retries), 1), 50)
        self.retry_count = 0

    def _check_cancelled(self):
        if self.cancel.is_set():
            raise TransferCancelled("transfer cancelled")

    def _read(self, timeout: float | None = None) -> int | None:
        self._check_cancelled()
        return self.read_byte(self.timeout if timeout is None else timeout)

    def _read_exact(self, size: int) -> bytes | None:
        data = bytearray()
        deadline = time.monotonic() + self.timeout
        while len(data) < size and time.monotonic() < deadline:
            value = self._read(min(0.2, max(0.01, deadline - time.monotonic())))
            if value is not None:
                data.append(value)
        return bytes(data) if len(data) == size else None

    def _read_packet(self, header: int) -> tuple[int, bytes] | None:
        size = 128 if header == SOH else 1024
        frame = self._read_exact(2 + size + 2)
        if frame is None:
            return None
        block, inverse = frame[0], frame[1]
        payload = frame[2:2 + size]
        received_crc = int.from_bytes(frame[-2:], "big")
        if inverse != 0xFF - block or received_crc != crc16_xmodem(payload):
            return None
        return block, payload

    def _request_header(self) -> int:
        for _ in range(self.max_retries + 1):
            self._check_cancelled()
            if not self.write(bytes((CRC_REQUEST,))):
                raise TransferError("serial write failed")
            header = self._read()
            if header in (SOH, STX, EOT, CAN):
                return header
            self.retry_count += 1
        raise TransferError("sender did not start transfer")

    def _wait_header(self) -> int:
        for _ in range(self.max_retries + 1):
            header = self._read()
            if header in (SOH, STX, EOT, CAN):
                return header
            self.retry_count += 1
        raise TransferError("sender stopped responding")

    def receive_xmodem(self, expected_size: int | None = None) -> ReceiveResult:
        started = time.monotonic()
        output = bytearray()
        expected_block = 1
        blocks = 0
        header = self._request_header()
        while True:
            self._check_cancelled()
            if header == CAN:
                raise TransferCancelled("sender cancelled transfer")
            if header == EOT:
                self.write(bytes((ACK,)))
                data = bytes(output[:expected_size] if expected_size is not None else output)
                return ReceiveResult("xmodem", data, "", blocks, self.retry_count, time.monotonic() - started)
            packet = self._read_packet(header)
            if packet is None:
                self.retry_count += 1
                if self.retry_count > self.max_retries:
                    raise TransferError("too many invalid packets")
                self.write(bytes((NAK,)))
            else:
                block, payload = packet
                if block == (expected_block & 0xFF):
                    output.extend(payload)
                    expected_block += 1
                    blocks += 1
                    self.progress and self.progress(len(output), expected_size or 0, blocks, self.retry_count)
                elif block != ((expected_block - 1) & 0xFF):
                    self.write(bytes((NAK,)))
                    header = self._read() or 0
                    continue
                self.write(bytes((ACK,)))
            header = self._wait_header()

    def receive_ymodem(self) -> ReceiveResult:
        batch = self.receive_ymodem_batch(max_files=1)
        if not batch.files:
            return ReceiveResult("ymodem", b"", "", batch.blocks, batch.retries, batch.duration)
        file = batch.files[0]
        return ReceiveResult("ymodem", file.data, file.filename, batch.blocks, batch.retries, batch.duration)

    def receive_ymodem_batch(
        self,
        max_files: int = DEFAULT_MAX_BATCH_FILES,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        max_total_size: int = DEFAULT_MAX_BATCH_SIZE,
    ) -> BatchReceiveResult:
        started = time.monotonic()
        header = self._request_header()
        files: list[BatchFile] = []
        filenames: set[str] = set()
        total_size = 0
        total_blocks = 0
        while True:
            if header not in (SOH, STX):
                raise TransferError("missing YMODEM metadata block")
            metadata_packet = self._read_packet(header)
            if metadata_packet is None or metadata_packet[0] != 0:
                raise TransferError("invalid YMODEM metadata block")
            metadata = metadata_packet[1].split(b"\0")
            raw_filename = metadata[0].decode("utf-8", errors="replace")
            if not raw_filename:
                self.write(bytes((ACK,)))
                return BatchReceiveResult(
                    "ymodem-batch", tuple(files), total_blocks, self.retry_count,
                    time.monotonic() - started,
                )
            if len(files) >= max_files:
                raise TransferError("YMODEM batch file limit exceeded")
            filename = _safe_ymodem_filename(raw_filename)
            filename_key = filename.casefold()
            if filename_key in filenames:
                raise TransferError("duplicate YMODEM batch filename")
            try:
                expected_size = int(metadata[1].split(b" ", 1)[0] or b"0")
            except (ValueError, IndexError):
                expected_size = 0
            if expected_size < 0:
                raise TransferError("invalid YMODEM file size")
            if expected_size > max_file_size:
                raise TransferError("YMODEM file size limit exceeded")
            if expected_size and total_size + expected_size > max_total_size:
                raise TransferError("YMODEM batch size limit exceeded")
            self.write(bytes((ACK, CRC_REQUEST)))

            output = bytearray()
            expected_block = 1
            while True:
                header = self._wait_header()
                if header == EOT:
                    self.write(bytes((NAK,)))
                    if self._read() != EOT:
                        raise TransferError("missing second YMODEM EOT")
                    self.write(bytes((ACK, CRC_REQUEST)))
                    data = bytes(output[:expected_size] if expected_size else output)
                    if len(data) > max_file_size:
                        raise TransferError("YMODEM file size limit exceeded")
                    if total_size + len(data) > max_total_size:
                        raise TransferError("YMODEM batch size limit exceeded")
                    files.append(BatchFile(
                        filename,
                        data,
                        hashlib.sha256(data).hexdigest(),
                    ))
                    filenames.add(filename_key)
                    total_size += len(data)
                    header = self._wait_header()
                    break
                if header not in (SOH, STX):
                    continue
                packet = self._read_packet(header)
                if packet is None:
                    self.retry_count += 1
                    self.write(bytes((NAK,)))
                    continue
                block, payload = packet
                if block == (expected_block & 0xFF):
                    effective_size = expected_size or len(output) + len(payload)
                    if effective_size > max_file_size:
                        raise TransferError("YMODEM file size limit exceeded")
                    output.extend(payload)
                    expected_block += 1
                    total_blocks += 1
                    self.progress and self.progress(
                        min(len(output), expected_size), expected_size, total_blocks, self.retry_count
                    )
                self.write(bytes((ACK,)))


@dataclass
class ActiveTransfer:
    transfer_id: str
    port: str
    owner_id: str
    protocol: str
    cancel: threading.Event


class SerialTransferManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._active: dict[str, ActiveTransfer] = {}

    def get(self, transfer_id: str) -> ActiveTransfer | None:
        with self._lock:
            return self._active.get(transfer_id)

    def active_for_port(self, port: str) -> ActiveTransfer | None:
        with self._lock:
            return next((active for active in self._active.values() if active.port == port), None)

    def cancel(self, transfer_id: str, owner_id: str) -> bool:
        with self._lock:
            active = self._active.get(transfer_id)
            if active is None or active.owner_id != owner_id:
                return False
            active.cancel.set()
            return True

    def send(
        self,
        transfer_id: str,
        port: str,
        owner_id: str,
        protocol: Literal["xmodem", "xmodem1k", "ymodem"],
        data: bytes,
        filename: str,
        timeout: float,
        retries: int,
        progress: Callable[[int, int, int, int], None] | None = None,
    ) -> TransferResult:
        if not serial_manager.is_open(port):
            raise TransferError("port is not open")
        with self._lock:
            if transfer_id in self._active:
                raise TransferError("transfer id is already active")
            if any(active.port == port for active in self._active.values()):
                raise TransferError("another transfer is active on this port")
            active = ActiveTransfer(transfer_id, port, owner_id, protocol, threading.Event())
            self._active[transfer_id] = active

        inbox: queue.Queue[int] = queue.Queue(maxsize=65536)

        def on_raw(raw_port: str, chunk: SerialRawChunk) -> None:
            if raw_port != port:
                return
            for value in chunk.data:
                try:
                    inbox.put_nowait(value)
                except queue.Full:
                    break

        def read_byte(wait: float) -> int | None:
            try:
                return inbox.get(timeout=wait)
            except queue.Empty:
                return None

        def write(payload: bytes) -> bool:
            return serial_manager.write_raw(port, payload, MessageSource.USER, record=False)

        serial_manager.register_raw_callback(on_raw)
        sender = XyModemSender(write, read_byte, active.cancel, progress, timeout, retries)
        try:
            if protocol == "ymodem":
                return sender.send_ymodem(data, filename)
            return sender.send_xmodem(data, 1024 if protocol == "xmodem1k" else 128)
        except TransferCancelled:
            serial_manager.write_raw(port, bytes((CAN, CAN, CAN)), MessageSource.USER, record=False)
            raise
        finally:
            serial_manager.unregister_raw_callback(on_raw)
            with self._lock:
                self._active.pop(transfer_id, None)

    def receive(
        self,
        transfer_id: str,
        port: str,
        owner_id: str,
        protocol: Literal["xmodem", "ymodem"],
        expected_size: int | None,
        timeout: float,
        retries: int,
        progress: Callable[[int, int, int, int], None] | None = None,
    ) -> ReceiveResult:
        if not serial_manager.is_open(port):
            raise TransferError("port is not open")
        with self._lock:
            if transfer_id in self._active or any(active.port == port for active in self._active.values()):
                raise TransferError("another transfer is active on this port")
            active = ActiveTransfer(transfer_id, port, owner_id, f"receive-{protocol}", threading.Event())
            self._active[transfer_id] = active

        inbox: queue.Queue[int] = queue.Queue(maxsize=65536)

        def on_raw(raw_port: str, chunk: SerialRawChunk):
            if raw_port != port:
                return
            for value in chunk.data:
                try:
                    inbox.put_nowait(value)
                except queue.Full:
                    break

        def read_byte(wait: float) -> int | None:
            try:
                return inbox.get(timeout=wait)
            except queue.Empty:
                return None

        def write(payload: bytes) -> bool:
            return serial_manager.write_raw(port, payload, MessageSource.USER, record=False)

        serial_manager.register_raw_callback(on_raw)
        receiver = XyModemReceiver(write, read_byte, active.cancel, progress, timeout, retries)
        try:
            return receiver.receive_ymodem() if protocol == "ymodem" else receiver.receive_xmodem(expected_size)
        except TransferCancelled:
            serial_manager.write_raw(port, bytes((CAN, CAN, CAN)), MessageSource.USER, record=False)
            raise
        finally:
            serial_manager.unregister_raw_callback(on_raw)
            with self._lock:
                self._active.pop(transfer_id, None)

    def receive_batch(
        self,
        transfer_id: str,
        port: str,
        owner_id: str,
        timeout: float,
        retries: int,
        progress: Callable[[int, int, int, int], None] | None = None,
        max_files: int = DEFAULT_MAX_BATCH_FILES,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        max_total_size: int = DEFAULT_MAX_BATCH_SIZE,
    ) -> BatchReceiveResult:
        if not serial_manager.is_open(port):
            raise TransferError("port is not open")
        with self._lock:
            if transfer_id in self._active or any(active.port == port for active in self._active.values()):
                raise TransferError("another transfer is active on this port")
            active = ActiveTransfer(transfer_id, port, owner_id, "receive-ymodem-batch", threading.Event())
            self._active[transfer_id] = active

        inbox: queue.Queue[int] = queue.Queue(maxsize=65536)

        def on_raw(raw_port: str, chunk: SerialRawChunk) -> None:
            if raw_port != port:
                return
            for value in chunk.data:
                try:
                    inbox.put_nowait(value)
                except queue.Full:
                    break

        def read_byte(wait: float) -> int | None:
            try:
                return inbox.get(timeout=wait)
            except queue.Empty:
                return None

        def write(payload: bytes) -> bool:
            return serial_manager.write_raw(port, payload, MessageSource.USER, record=False)

        serial_manager.register_raw_callback(on_raw)
        receiver = XyModemReceiver(write, read_byte, active.cancel, progress, timeout, retries)
        try:
            return receiver.receive_ymodem_batch(max_files, max_file_size, max_total_size)
        except TransferCancelled:
            serial_manager.write_raw(port, bytes((CAN, CAN, CAN)), MessageSource.USER, record=False)
            raise
        finally:
            serial_manager.unregister_raw_callback(on_raw)
            with self._lock:
                self._active.pop(transfer_id, None)


serial_transfers = SerialTransferManager()
