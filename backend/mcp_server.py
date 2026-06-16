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
import os

BASE_URL = os.environ.get("AI_SERIAL_API_URL", "http://localhost:8000")
_AUTH_TOKEN = os.environ.get("AI_SERIAL_TOKEN", "").strip()

app = Server("ai-serial-bridge")

# 复用单个 AsyncClient 以利用连接池，避免每次请求新建/销毁连接
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def _close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _auth_headers() -> dict:
    """后端启用 token 鉴权时附带 Authorization 头。"""
    return {"Authorization": f"Bearer {_AUTH_TOKEN}"} if _AUTH_TOKEN else {}


# 延迟初始化语言（避免模块导入时阻塞）
_lang_initialized = False

async def _init_lang():
    global _lang_initialized
    if _lang_initialized:
        return
    _lang_initialized = True
    lang = os.environ.get("AI_SERIAL_LANG", "zh")
    try:
        await api_post("/api/lang", {"lang": lang})
    except Exception:
        pass


async def api_get(path: str):
    client = await _get_client()
    return await client.get(f"{BASE_URL}{path}", headers=_auth_headers())


async def api_post(path: str, json_data: dict = None):
    client = await _get_client()
    return await client.post(f"{BASE_URL}{path}", json=json_data, headers=_auth_headers())


async def _get_default_port() -> str:
    """获取当前已打开的串口，如果只有一个则返回它"""
    r = await api_get("/api/open-ports")
    ports = r.json().get("ports", [])
    if len(ports) == 1:
        return ports[0]
    return ""


def _resolve_port(arguments: dict) -> str:
    """从参数中解析 port，如果没传则尝试推断"""
    port = arguments.get("port", "")
    return port


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
            description="关闭指定串口",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "要关闭的串口名称，例如 'COM3'。如果只有一个串口打开，可省略。"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="serial_write",
            description="向串口发送数据（会自动添加换行符）",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "目标串口名称，例如 'COM3'。如果只有一个串口打开，可省略。"
                    },
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
                    "port": {
                        "type": "string",
                        "description": "目标串口名称，例如 'COM3'。如果只有一个串口打开，可省略。"
                    },
                    "data": {
                        "type": "string",
                        "description": "要发送的命令"
                    },
                    "wait_time": {
                        "type": "number",
                        "description": "发送后等待响应的时间（秒）",
                        "default": 1.0
                    }
                },
                "required": ["data"]
            }
        ),
        Tool(
            name="serial_is_open",
            description="检查指定串口是否已打开",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "要检查的串口名称，例如 'COM3'"
                    }
                },
                "required": ["port"]
            }
        ),
        Tool(
            name="serial_get_history",
            description="获取指定串口的通信历史记录",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "要查询的串口名称，例如 'COM3'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回的最大记录数",
                        "default": 100
                    }
                },
                "required": ["port"]
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
            port = arguments.get("port", "")
            if not port:
                return [TextContent(type="text", text="❌ 请指定 port 参数")]
            baud = arguments.get("baudrate", 115200)
            r = await api_post("/api/open", {"port": port, "baudrate": baud})
            ok = r.json().get("success", False)
            if ok:
                return [TextContent(type="text", text=f"✅ 串口已打开: {port} @ {baud}bps")]
            else:
                return [TextContent(type="text", text=f"❌ 打开串口失败: {port}")]

        elif name == "serial_close":
            port = _resolve_port(arguments)
            if not port:
                default = await _get_default_port()
                if default:
                    port = default
                else:
                    return [TextContent(type="text", text="❌ 请指定 port 参数（或确保只有一个串口打开）")]
            r = await api_post(f"/api/close?port={port}")
            ok = r.json().get("success", False)
            return [TextContent(type="text", text=f"✅ 串口 {port} 已关闭" if ok else f"❌ 关闭 {port} 失败或串口未打开")]

        elif name == "serial_write":
            port = _resolve_port(arguments)
            if not port:
                default = await _get_default_port()
                if default:
                    port = default
                else:
                    return [TextContent(type="text", text="❌ 请指定 port 参数（或确保只有一个串口打开）")]
            data = arguments["data"]
            newline = arguments.get("newline", "\r")
            r = await api_post(f"/api/write-ai?port={port}", {"data": data, "newline": newline})
            ok = r.json().get("success", False)
            if ok:
                return [TextContent(type="text", text=f"📤 [{port}] 已发送: {data}")]
            else:
                return [TextContent(type="text", text=f"❌ 向 {port} 发送失败，串口可能未打开")]

        elif name == "serial_write_then_read":
            port = _resolve_port(arguments)
            if not port:
                default = await _get_default_port()
                if default:
                    port = default
                else:
                    return [TextContent(type="text", text="❌ 请指定 port 参数（或确保只有一个串口打开）")]
            data = arguments["data"]
            wait_time = arguments.get("wait_time", 1.0)

            # 先发送
            r = await api_post(f"/api/write-ai?port={port}", {"data": data, "newline": "\r"})
            if not r.json().get("success", False):
                return [TextContent(type="text", text=f"❌ 向 {port} 发送失败，串口可能未打开")]

            # 等待设备响应
            await asyncio.sleep(wait_time)

            # 获取历史记录
            r = await api_get(f"/api/history?port={port}&limit=500")
            history = r.json()

            # 找到最后一条 AI 消息的位置，取其后的设备消息
            ai_idx = -1
            for i in range(len(history) - 1, -1, -1):
                if history[i].get("source") == "ai":
                    ai_idx = i
                    break

            if ai_idx >= 0:
                # 取 AI 消息之后的所有设备消息
                device_msgs = [h for h in history[ai_idx + 1:] if h.get("source") == "device"]
                if device_msgs:
                    content = "".join(m["content"] for m in device_msgs)
                    return [TextContent(type="text", text=f"📤 [{port}] 发送: {data}\n📥 收到:\n{content}")]

            return [TextContent(type="text", text=f"📤 [{port}] 发送: {data}\n⏱️ 等待 {wait_time}s 后未收到响应")]

        elif name == "serial_is_open":
            port = arguments.get("port", "")
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_get(f"/api/status?port={port}")
            status = r.json()
            is_open = status.get("is_open", False)
            if is_open:
                return [TextContent(type="text", text=f"串口 {port} 状态: 已打开")]
            else:
                return [TextContent(type="text", text=f"串口 {port} 状态: 未打开")]

        elif name == "serial_get_history":
            port = arguments.get("port", "")
            limit = arguments.get("limit", 100)
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_get(f"/api/history?port={port}&limit={limit}")
            history = r.json()
            if not history:
                return [TextContent(type="text", text="暂无通信记录")]

            lines = [f"串口 {port} 通信历史:"]
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
    await _init_lang()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    finally:
        await _close_client()


if __name__ == "__main__":
    asyncio.run(main())
