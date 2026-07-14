"""Verify a Linux serial console through the real MCP stdio transport."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "backend" / "mcp_server.py"
MARKER = "__AI_SERIAL_MCP_OK__"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def call_text(session: ClientSession, name: str, arguments: dict) -> str:
    result = await session.call_tool(name, arguments)
    text = "\n".join(getattr(item, "text", "") for item in result.content)
    if result.isError:
        raise RuntimeError(f"{name} failed: {text}")
    return text


async def main() -> None:
    port = os.environ.get("AI_SERIAL_TEST_PORT", "COM14")
    baudrate = int(os.environ.get("AI_SERIAL_TEST_BAUDRATE", "115200"))
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env=dict(os.environ),
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            opened = False
            try:
                open_text = await call_text(session, "serial_open", {
                    "port": port,
                    "baudrate": baudrate,
                    "bytesize": 8,
                    "parity": "N",
                    "stopbits": 1,
                    "xonxoff": False,
                    "rtscts": False,
                    "dsrdtr": False,
                })
                if "已打开" not in open_text and "opened" not in open_text.lower():
                    raise RuntimeError(f"serial_open did not succeed: {open_text}")
                opened = True

                lease_text = await call_text(session, "serial_get_lease", {"port": port})
                probe = await call_text(session, "serial_write_then_read", {
                    "port": port,
                    "data": f"printf '{MARKER}\\n'; uname -srm",
                    "wait_time": 2.0,
                    "newline": "\r",
                })
                if MARKER not in probe or "Linux" not in probe:
                    raise RuntimeError(f"Linux probe did not return expected marker and uname: {probe}")

                print(open_text)
                print(lease_text)
                print(probe)
                print(f"MCP Linux serial verification passed: {port} @ {baudrate}")
            finally:
                if opened:
                    print(await call_text(session, "serial_close", {"port": port}))


if __name__ == "__main__":
    asyncio.run(main())
