"""
AI Serial Bridge - MCP Server (HTTP Proxy Mode)
Model Context Protocol server for AI Agent integration
通过 HTTP 代理到 main.py，与 Web UI 共享同一个串口状态
支持 stdio 模式，兼容 Claude Desktop, Cline, Continue 等
"""

import asyncio
import json
import time

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import httpx

BASE_URL = "http://localhost:8000"

app = Server("ai-serial-bridge")


async def api_get(path: str):
    async with httpx.AsyncClient() as client:
        return await client.get(f"{BASE_URL}{path}", timeout=10.0)


async def api_post(path: str, json_data: dict = None):
    async with httpx.AsyncClient() as client:
        return await client.post(f"{BASE_URL}{path}", json=json_data, timeout=10.0)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="serial_list_ports",
            description="列出计算机上所有可用的串口设备",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="serial_open",
            description="打开指定串口",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "串口设备名称，例如 'COM3' 或 '/dev/ttyUSB0'"
                    },
                    "baudrate": {
                        "type": "integer",
                        "description": "波特率，默认 115200",
                        "default": 115200
                    }
                },
                "required": ["port"]
            }
        ),
        Tool(
            name="serial_close",
            description="关闭当前打开的串口",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="serial_write",
            description="向串口发送数据（会自动添加换行符）",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "要发送的字符串数据"
                    },
                    "newline": {
                        "type": "string",
                        "description": "行尾换行符，\\r 为CR(推荐Linux串口), \\r\\n 为CRLF, \\n 为LF, 空字符串为无",
                        "default": "\r"
                    }
                },
                "required": ["data"]
            }
        ),
        Tool(
            name="serial_write_then_read",
            description="发送数据到串口并等待读取响应（常用：发送命令后等待设备回复）",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "要发送的命令"
                    },
                    "wait_time": {
                        "type": "number",
                        "description": "发送后等待响应的时间（秒）",
                        "default": 1.0
                    },
                    "read_timeout": {
                        "type": "number",
                        "description": "读取超时时间（秒）",
                        "default": 2.0
                    }
                },
                "required": ["data"]
            }
        ),
        Tool(
            name="serial_is_open",
            description="检查串口是否已打开",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="serial_get_history",
            description="获取串口通信历史记录",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回的最大记录数",
                        "default": 100
                    }
                },
                "required": []
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "serial_list_ports":
            r = await api_get("/api/ports")
            ports = r.json()
            if not ports:
                return [TextContent(type="text", text="未找到可用串口设备")]
            lines = ["可用串口设备:"]
            for p in ports:
                lines.append(f"  - {p['device']}: {p['description']} (HWID: {p['hwid']})")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "serial_open":
            port = arguments["port"]
            baud = arguments.get("baudrate", 115200)
            r = await api_post("/api/open", {"port": port, "baudrate": baud})
            ok = r.json().get("success", False)
            if ok:
                return [TextContent(type="text", text=f"✅ 串口已打开: {port} @ {baud}bps")]
            else:
                return [TextContent(type="text", text=f"❌ 打开串口失败: {port}")]

        elif name == "serial_close":
            r = await api_post("/api/close")
            ok = r.json().get("success", False)
            return [TextContent(type="text", text="✅ 串口已关闭" if ok else "❌ 关闭失败或串口未打开")]

        elif name == "serial_write":
            data = arguments["data"]
            newline = arguments.get("newline", "\r")
            r = await api_post("/api/write", {"data": data, "newline": newline})
            ok = r.json().get("success", False)
            if ok:
                return [TextContent(type="text", text=f"📤 已发送: {data}")]
            else:
                return [TextContent(type="text", text="❌ 发送失败，串口可能未打开")]

        elif name == "serial_write_then_read":
            data = arguments["data"]
            wait_time = arguments.get("wait_time", 1.0)
            read_timeout = arguments.get("read_timeout", 2.0)

            # 先发送
            r = await api_post("/api/write", {"data": data, "newline": "\r"})
            if not r.json().get("success", False):
                return [TextContent(type="text", text="❌ 发送失败，串口可能未打开")]

            # 等待设备响应
            await asyncio.sleep(wait_time)

            # 获取历史记录中的最新设备返回
            r = await api_get("/api/history?limit=50")
            history = r.json()

            # 过滤出设备返回，取最近的
            device_msgs = [h for h in history if h.get("source") == "device"]
            if device_msgs:
                # 取最后几条设备消息拼接
                recent = device_msgs[-10:]
                lines = [f"📤 发送: {data}", "📥 收到:"]
                for m in recent:
                    lines.append(m["content"])
                return [TextContent(type="text", text="\n".join(lines))]
            else:
                return [TextContent(type="text", text=f"📤 发送: {data}\n⏱️ 等待 {wait_time}s 后未收到响应")]

        elif name == "serial_is_open":
            r = await api_get("/api/status")
            status = r.json()
            is_open = status.get("is_open", False)
            port = status.get("port")
            baud = status.get("baudrate")
            if is_open and port:
                return [TextContent(type="text", text=f"串口状态: 已打开 ({port} @ {baud}bps)")]
            else:
                return [TextContent(type="text", text="串口状态: 未打开")]

        elif name == "serial_get_history":
            limit = arguments.get("limit", 100)
            r = await api_get(f"/api/history?limit={limit}")
            history = r.json()
            if not history:
                return [TextContent(type="text", text="暂无通信记录")]

            lines = ["串口通信历史:"]
            for h in history:
                ts = h.get("time_str", "")
                source = h.get("source", "")
                content = h.get("content", "")
                prefix = "【设备】" if source == "device" else \
                         "【AI】" if source == "ai" else \
                         "【用户】" if source == "user" else "【系统】"
                lines.append(f"[{ts}] {prefix} {content}")
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except httpx.ConnectError:
        return [TextContent(type="text", text="❌ 无法连接到后端服务 (http://localhost:8000)，请先启动 main.py")]
    except Exception as e:
        return [TextContent(type="text", text=f"错误: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
