"""Run a real MCP XMODEM transfer over a com0com serial-port pair."""

import asyncio
import os
from pathlib import Path
import sys
import threading
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import serial


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "backend" / "mcp_server.py"
SOH, STX, EOT, ACK, NAK, CRC_REQUEST, SUB = 0x01, 0x02, 0x04, 0x06, 0x15, 0x43, 0x1A

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def read_exact(port: serial.Serial, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = port.read(size - len(data))
        if not chunk:
            raise TimeoutError(f"receiver timed out after {len(data)}/{size} bytes")
        data.extend(chunk)
    return bytes(data)


def receive_xmodem(
    port_name: str,
    ready: threading.Event,
    stop: threading.Event,
    output: bytearray,
    errors: list[BaseException],
) -> None:
    try:
        with serial.Serial(port_name, 115200, timeout=1, write_timeout=2) as port:
            ready.set()
            expected_block = 1
            while not stop.is_set():
                port.write(bytes((CRC_REQUEST,)))
                port.flush()
                header = port.read(1)
                if not header:
                    continue
                value = header[0]
                if value == EOT:
                    port.write(bytes((ACK,)))
                    port.flush()
                    return
                if value not in (SOH, STX):
                    continue
                size = 128 if value == SOH else 1024
                frame = read_exact(port, 2 + size + 2)
                block, inverse = frame[0], frame[1]
                payload = frame[2:2 + size]
                received_crc = int.from_bytes(frame[-2:], "big")
                if inverse != 0xFF - block or received_crc != crc16_xmodem(payload):
                    port.write(bytes((NAK,)))
                    port.flush()
                    continue
                if block == (expected_block & 0xFF):
                    output.extend(payload)
                    expected_block += 1
                elif block != ((expected_block - 1) & 0xFF):
                    port.write(bytes((NAK,)))
                    port.flush()
                    continue
                port.write(bytes((ACK,)))
                port.flush()
    except BaseException as exc:
        errors.append(exc)
        ready.set()


async def call_text(session: ClientSession, name: str, arguments: dict) -> str:
    result = await session.call_tool(name, arguments)
    text = "\n".join(getattr(item, "text", "") for item in result.content)
    if result.isError:
        raise RuntimeError(f"{name} failed: {text}")
    return text


async def main() -> None:
    send_port = os.environ.get("AI_SERIAL_XMODEM_SEND_PORT", "COM4")
    receive_port = os.environ.get("AI_SERIAL_XMODEM_RECEIVE_PORT", "COM5")
    payload = bytes(range(256)) + b"AI Serial Bridge XMODEM loopback" + bytes(range(32))
    artifact = ROOT / ".test-artifacts" / f"xmodem-{uuid.uuid4().hex}.bin"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(payload)

    ready = threading.Event()
    stop = threading.Event()
    received = bytearray()
    receiver_errors: list[BaseException] = []
    receiver = threading.Thread(
        target=receive_xmodem,
        args=(receive_port, ready, stop, received, receiver_errors),
        daemon=True,
    )
    receiver.start()
    if not ready.wait(5):
        raise RuntimeError("loopback receiver did not start")
    if receiver_errors:
        raise receiver_errors[0]

    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=dict(os.environ))
    opened = False
    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                open_text = await call_text(session, "serial_open", {"port": send_port, "baudrate": 115200})
                if "已打开" not in open_text and "opened" not in open_text.lower():
                    raise RuntimeError(open_text)
                opened = True
                try:
                    transfer_text = await call_text(session, "serial_send_protocol_file", {
                        "port": send_port,
                        "file_path": str(artifact),
                        "protocol": "xmodem",
                        "timeout": 2,
                        "retries": 10,
                    })
                    receiver.join(timeout=5)
                    if receiver.is_alive():
                        raise RuntimeError("loopback receiver did not observe EOT")
                    if receiver_errors:
                        raise receiver_errors[0]
                    if received[:len(payload)] != payload:
                        raise RuntimeError("loopback payload mismatch")
                    if any(value != SUB for value in received[len(payload):]):
                        raise RuntimeError("invalid XMODEM padding")
                    print(open_text)
                    print(transfer_text)
                    print(f"MCP XMODEM loopback passed: {send_port} -> {receive_port}, {len(payload)} bytes")
                finally:
                    print(await call_text(session, "serial_close", {"port": send_port}))
                    opened = False
    finally:
        stop.set()
        receiver.join(timeout=2)
        artifact.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
