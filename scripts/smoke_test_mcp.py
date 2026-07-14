"""Launch the stdio MCP server and verify its tool list and backend connectivity."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "backend" / "mcp_server.py"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            expected = {"serial_list_ports", "serial_open", "serial_write", "serial_close"}
            missing = expected.difference(names)
            if missing:
                raise RuntimeError(f"missing MCP tools: {sorted(missing)}")

            result = await session.call_tool("serial_list_ports")
            if result.isError:
                raise RuntimeError(f"serial_list_ports failed: {result.content}")
            text = "\n".join(getattr(item, "text", "") for item in result.content)
            print(f"MCP tools: {', '.join(names)}")
            print(f"serial_list_ports: {text}")


if __name__ == "__main__":
    asyncio.run(main())
