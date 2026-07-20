"""XMODEM/YMODEM packet, retry, and handshake tests."""

import queue
import threading

import pytest

from transfers import (
    ACK,
    CRC_REQUEST,
    EOT,
    NAK,
    SOH,
    STX,
    XyModemSender,
    XyModemReceiver,
    TransferCancelled,
    TransferError,
    crc16_xmodem,
)


def test_crc16_xmodem_reference_vector():
    assert crc16_xmodem(b"123456789") == 0x31C3


def test_cancelled_transfer_stops_before_writing():
    cancel = threading.Event()
    cancel.set()
    writes = []
    sender = XyModemSender(lambda data: writes.append(data) or True, lambda timeout: None, cancel, timeout=0.2)
    with pytest.raises(TransferCancelled):
        sender.send_xmodem(b"data")
    assert writes == []


def test_xmodem_crc_transfer_retries_nak_and_finishes():
    responses: queue.Queue[int] = queue.Queue()
    responses.put(CRC_REQUEST)
    payloads = []
    attempts = {1: 0}

    def write(packet: bytes) -> bool:
        if packet == bytes((EOT,)):
            responses.put(ACK)
            return True
        assert packet[0] == SOH
        block = packet[1]
        payload = packet[3:131]
        assert packet[2] == 0xFF - block
        assert int.from_bytes(packet[-2:], "big") == crc16_xmodem(payload)
        attempts[block] = attempts.get(block, 0) + 1
        if block == 1 and attempts[block] == 1:
            responses.put(NAK)
        else:
            payloads.append(payload)
            responses.put(ACK)
        return True

    def read_byte(_timeout: float):
        try:
            return responses.get_nowait()
        except queue.Empty:
            return None

    result = XyModemSender(write, read_byte, timeout=0.2, retries=3).send_xmodem(b"hello")
    assert payloads[0].startswith(b"hello")
    assert result.bytes_sent == 5
    assert result.blocks == 1
    assert result.retries == 1


def test_ymodem_sends_metadata_1k_data_and_end_block():
    responses: queue.Queue[int] = queue.Queue()
    responses.put(CRC_REQUEST)
    packets = []
    eot_count = 0

    def write(packet: bytes) -> bool:
        nonlocal eot_count
        if packet == bytes((EOT,)):
            eot_count += 1
            if eot_count == 1:
                responses.put(NAK)
            else:
                responses.put(ACK)
                responses.put(CRC_REQUEST)
            return True
        packets.append(packet)
        responses.put(ACK)
        if len(packets) == 1:
            responses.put(CRC_REQUEST)
        return True

    def read_byte(_timeout: float):
        try:
            return responses.get_nowait()
        except queue.Empty:
            return None

    data = b"firmware" * 200
    result = XyModemSender(write, read_byte, timeout=0.2, retries=3).send_ymodem(data, "fw.bin")
    assert packets[0][0] == SOH and packets[0][1] == 0
    assert packets[0][3:3 + len(b"fw.bin\0")].startswith(b"fw.bin\0")
    assert packets[1][0] == STX and packets[1][1] == 1
    assert packets[-1][0] == SOH and packets[-1][1] == 0
    assert packets[-1][3:131] == bytes(128)
    assert result.protocol == "ymodem"
    assert result.bytes_sent == len(data)


def test_xmodem_receiver_validates_crc_and_trims_expected_size():
    incoming: queue.Queue[int] = queue.Queue()
    controls = []
    payload = b"received-data".ljust(128, bytes((0x1A,)))
    crc = crc16_xmodem(payload)
    frame = bytes((SOH, 1, 0xFE)) + payload + bytes((crc >> 8, crc & 0xFF, EOT))

    def write(data: bytes):
        controls.extend(data)
        if data == bytes((CRC_REQUEST,)):
            for value in frame:
                incoming.put(value)
        return True

    receiver = XyModemReceiver(write, lambda timeout: incoming.get_nowait() if not incoming.empty() else None, timeout=0.2)
    result = receiver.receive_xmodem(expected_size=len(b"received-data"))
    assert result.data == b"received-data"
    assert controls == [CRC_REQUEST, ACK, ACK]


def test_ymodem_receiver_parses_filename_and_size():
    incoming: queue.Queue[int] = queue.Queue()
    controls = []

    def packet(block: int, payload: bytes):
        crc = crc16_xmodem(payload)
        return bytes((SOH, block, 0xFF - block)) + payload + bytes((crc >> 8, crc & 0xFF))

    metadata = b"fw.bin\0 4\0".replace(b"\0 ", b"\0").ljust(128, b"\0")
    data = b"DATA".ljust(128, bytes((0x1A,)))
    stream = packet(0, metadata) + packet(1, data) + bytes((EOT, EOT)) + packet(0, bytes(128))

    def write(value: bytes):
        controls.extend(value)
        if value == bytes((CRC_REQUEST,)):
            for byte in stream:
                incoming.put(byte)
        return True

    receiver = XyModemReceiver(write, lambda timeout: incoming.get_nowait() if not incoming.empty() else None, timeout=0.2)
    result = receiver.receive_ymodem()
    assert result.filename == "fw.bin"
    assert result.data == b"DATA"
    assert result.blocks == 1


def test_ymodem_batch_receiver_returns_sha256_manifest():
    incoming: queue.Queue[int] = queue.Queue()

    def packet(block: int, payload: bytes):
        crc = crc16_xmodem(payload)
        return bytes((SOH, block, 0xFF - block)) + payload + bytes((crc >> 8, crc & 0xFF))

    def metadata(name: str, size: int):
        return f"{name}\0{size}\0".encode().ljust(128, b"\0")

    stream = (
        packet(0, metadata("a.bin", 1))
        + packet(1, b"A".ljust(128, bytes((0x1A,))))
        + bytes((EOT, EOT))
        + packet(0, metadata("b.bin", 2))
        + packet(1, b"BC".ljust(128, bytes((0x1A,))))
        + bytes((EOT, EOT))
        + packet(0, bytes(128))
    )

    def write(value: bytes):
        if value == bytes((CRC_REQUEST,)):
            for byte in stream:
                incoming.put(byte)
        return True

    receiver = XyModemReceiver(write, lambda timeout: incoming.get_nowait() if not incoming.empty() else None, timeout=0.2)
    result = receiver.receive_ymodem_batch()
    assert [file.filename for file in result.files] == ["a.bin", "b.bin"]
    assert [file.data for file in result.files] == [b"A", b"BC"]
    assert all(len(file.sha256) == 64 for file in result.files)


def test_ymodem_batch_receiver_sanitizes_filename_and_enforces_size_limit():
    incoming: queue.Queue[int] = queue.Queue()

    def packet(block: int, payload: bytes):
        crc = crc16_xmodem(payload)
        return bytes((SOH, block, 0xFF - block)) + payload + bytes((crc >> 8, crc & 0xFF))

    stream = packet(0, b"../../fw.bin\0" + b"4\0" + bytes(113))

    def write(value: bytes):
        if value == bytes((CRC_REQUEST,)):
            for byte in stream:
                incoming.put(byte)
        return True

    receiver = XyModemReceiver(write, lambda timeout: incoming.get_nowait() if not incoming.empty() else None, timeout=0.2)
    with pytest.raises(TransferError, match="file size limit"):
        receiver.receive_ymodem_batch(max_file_size=3)
