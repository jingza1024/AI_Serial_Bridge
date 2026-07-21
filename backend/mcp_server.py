"""
AI Serial Bridge - MCP Server (HTTP Proxy Mode)
Model Context Protocol server for AI Agent integration
通过 HTTP 代理到 main.py，与 Web UI 共享同一个串口状态
支持 stdio 模式，兼容 Claude Desktop, Cline, Continue 等
"""

import asyncio
import hashlib
import io
import json
import os
import re
import secrets
import zipfile
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import httpx

import local_runtime

_CLIENT_ID = os.environ.get("AI_SERIAL_CLIENT_ID", "").strip() or f"mcp-{secrets.token_urlsafe(12)}"
_CLIENT_LABEL = os.environ.get("AI_SERIAL_CLIENT_LABEL", "MCP").strip()[:64] or "MCP"
_LANG = os.environ.get("AI_SERIAL_LANG", "zh").lower()
PREFLIGHT_TIMEOUT = 2.0
MAX_BATCH_FILES = 64
MAX_FILE_SIZE = 32 * 1024 * 1024
MAX_BATCH_SIZE = 64 * 1024 * 1024

app = Server("ai-serial-bridge")

# 复用单个 AsyncClient 以利用连接池，避免每次请求新建/销毁连接
_clients: dict[bool, httpx.AsyncClient] = {}
_port_locks: dict[str, asyncio.Lock] = {}


class BackendDiscoveryError(RuntimeError):
    """Raised when no discovered target can be safely authenticated."""


async def _get_client(*, trust_env: bool = True) -> httpx.AsyncClient:
    client = _clients.get(trust_env)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=10.0, trust_env=trust_env)
        _clients[trust_env] = client
    return client


async def _close_client() -> None:
    for client in _clients.values():
        if not client.is_closed:
            await client.aclose()
    _clients.clear()


def _client_headers(token: str = "") -> dict:
    headers = {
        "X-AI-Serial-Client": _CLIENT_ID,
        "X-AI-Serial-Client-Label": _CLIENT_LABEL,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _endpoint_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _validate_preflight(
    response,
    target: local_runtime.ConnectionTarget,
) -> bool:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("backend config is not an object")
    if payload.get("service") != local_runtime.SERVICE_NAME:
        raise ValueError("backend service identity mismatch")
    auth_required = payload.get("auth_required")
    instance_id = payload.get("instance_id", "")
    if not isinstance(auth_required, bool) or not isinstance(instance_id, str):
        raise ValueError("backend config has invalid fields")
    if target.instance_id and instance_id != target.instance_id:
        raise ValueError("backend instance identity mismatch")
    return auth_required


async def _api_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_data: dict | None = None,
    content: bytes | None = None,
    extra_headers: dict | None = None,
    timeout=10.0,
):
    try:
        targets = local_runtime.resolve_connection_targets()
    except local_runtime.RuntimeConfigError as exc:
        raise BackendDiscoveryError(str(exc)) from exc

    last_error: Exception | None = None
    for target in targets:
        client = await _get_client(
            trust_env=not local_runtime.is_loopback_url(target.api_url)
        )
        config_url = _endpoint_url(target.api_url, "/api/config")
        try:
            config_response = await client.request(
                "GET",
                config_url,
                headers=_client_headers(),
                timeout=PREFLIGHT_TIMEOUT,
            )
            auth_required = _validate_preflight(config_response, target)
            if auth_required and not target.token:
                raise ValueError("backend requires authentication but no token is available")
        except Exception as exc:
            last_error = exc
            continue

        headers = _client_headers(target.token if auth_required else "")
        if extra_headers:
            headers.update(extra_headers)
        request_kwargs = {
            "params": params,
            "headers": headers,
            "timeout": timeout,
        }
        if json_data is not None:
            request_kwargs["json"] = json_data
        if content is not None:
            request_kwargs["content"] = content

        response = await client.request(
            method,
            _endpoint_url(target.api_url, path),
            **request_kwargs,
        )
        if response.status_code == 401:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = exc
            continue
        response.raise_for_status()
        return response

    raise BackendDiscoveryError(
        "no compatible AI Serial Bridge backend is available"
    ) from last_error


async def api_get(path: str, params: dict | None = None):
    return await _api_request("GET", path, params=params)


async def api_post(path: str, json_data: dict = None, params: dict | None = None):
    return await _api_request(
        "POST",
        path,
        params=params,
        json_data=json_data,
    )


async def api_post_long(path: str, params: dict | None = None):
    return await _api_request("POST", path, params=params, timeout=None)


async def api_post_bytes(path: str, data: bytes, params: dict | None = None):
    return await _api_request(
        "POST",
        path,
        params=params,
        content=data,
        extra_headers={"Content-Type": "application/octet-stream"},
        timeout=None,
    )


async def api_receive_bytes(path: str, params: dict | None = None):
    return await _api_request("POST", path, params=params, timeout=None)


async def _get_default_port() -> str:
    """获取当前已打开的串口，如果只有一个则返回它"""
    r = await api_get("/api/open-ports")
    ports = r.json().get("ports", [])
    if len(ports) == 1:
        item = ports[0]
        return item.get("port", "") if isinstance(item, dict) else item
    return ""


def _resolve_port(arguments: dict) -> str:
    """从参数中解析 port，如果没传则尝试推断"""
    port = arguments.get("port", "")
    return port


_EVENT_TEXT = {
    "zh": {
        "port.already_open": "串口已打开: {port}",
        "port.opened": "串口已打开: {port}",
        "port.open_failed": "打开串口失败: {port} ({error})",
        "port.closed": "串口已关闭: {port}",
        "port.close_failed": "关闭串口失败: {error}",
        "port.not_open": "串口未打开",
        "serial.send_failed": "串口发送失败: {error}",
        "serial.read_error": "串口读取失败: {error}",
    },
    "en": {
        "port.already_open": "Port already open: {port}",
        "port.opened": "Port opened: {port}",
        "port.open_failed": "Failed to open port: {port} ({error})",
        "port.closed": "Port closed: {port}",
        "port.close_failed": "Failed to close port: {error}",
        "port.not_open": "Port is not open",
        "serial.send_failed": "Serial send failed: {error}",
        "serial.read_error": "Serial read failed: {error}",
    },
}


def _event_content(item: dict) -> str:
    content = item.get("content", "")
    code = item.get("event_code")
    if not code:
        return content
    template = _EVENT_TEXT.get(_LANG, _EVENT_TEXT["zh"]).get(code, code)
    params = {"port": "", "error": "", **(item.get("event_params") or {})}
    try:
        return template.format(**params)
    except (KeyError, ValueError):
        return code


def _lease_text(lease: dict | None) -> str:
    if not lease:
        return "当前没有写入者"
    return f"写租约由 {lease.get('owner_label') or lease.get('owner_id')} 持有"


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
                    },
                    "bytesize": {"type": "integer", "enum": [5, 6, 7, 8], "default": 8},
                    "parity": {"type": "string", "enum": ["N", "E", "O", "M", "S"], "default": "N"},
                    "stopbits": {"type": "number", "enum": [1, 1.5, 2], "default": 1},
                    "xonxoff": {"type": "boolean", "default": False},
                    "rtscts": {"type": "boolean", "default": False},
                    "dsrdtr": {"type": "boolean", "default": False},
                    "dtr": {"type": ["boolean", "null"], "default": None},
                    "rts": {"type": ["boolean", "null"], "default": None}
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
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 30
                    },
                    "newline": {
                        "type": "string",
                        "enum": ["", "\r", "\n", "\r\n"],
                        "default": "\r"
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
            name="serial_get_lease",
            description="查看指定串口当前的单写者租约",
            inputSchema={
                "type": "object",
                "properties": {"port": {"type": "string"}},
                "required": ["port"]
            }
        ),
        Tool(
            name="serial_acquire_lease",
            description="获取或续期指定串口的写租约",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "string"},
                    "ttl": {"type": "number", "minimum": 5, "maximum": 300, "default": 30}
                },
                "required": ["port"]
            }
        ),
        Tool(
            name="serial_release_lease",
            description="释放当前 MCP 持有的串口写租约，允许其他客户端写入",
            inputSchema={
                "type": "object",
                "properties": {"port": {"type": "string"}},
                "required": ["port"]
            }
        ),
        Tool(
            name="serial_send_protocol_file",
            description="使用 XMODEM、XMODEM-1K 或 YMODEM 向设备发送本地文件（接收端需先进入对应接收模式）",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "string"},
                    "file_path": {"type": "string", "description": "MCP 主机上的本地文件绝对路径"},
                    "protocol": {
                        "type": "string",
                        "enum": ["xmodem", "xmodem1k", "ymodem"],
                        "default": "xmodem"
                    },
                    "transfer_id": {"type": "string", "description": "可选的调用方传输 ID"},
                    "timeout": {"type": "number", "minimum": 0.2, "maximum": 60, "default": 10},
                    "retries": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
                },
                "required": ["port", "file_path"]
            }
        ),
        Tool(
            name="serial_cancel_transfer",
            description="取消当前 MCP 客户端发起的 XMODEM/YMODEM 传输",
            inputSchema={
                "type": "object",
                "properties": {"transfer_id": {"type": "string"}},
                "required": ["transfer_id"]
            }
        ),
        Tool(
            name="serial_receive_protocol_file",
            description="使用 XMODEM 或 YMODEM 从设备接收文件并保存到 MCP 主机",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "string"},
                    "output_path": {"type": "string"},
                    "protocol": {"type": "string", "enum": ["xmodem", "ymodem"], "default": "xmodem"},
                    "expected_size": {"type": "integer", "minimum": 0},
                    "timeout": {"type": "number", "minimum": 0.2, "maximum": 60, "default": 10},
                    "retries": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
                },
                "required": ["port", "output_path"]
            }
        ),
        Tool(
            name="serial_receive_ymodem_batch",
            description="使用 YMODEM 批量接收文件，校验 SHA-256 后保存到 MCP 主机目录",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "string"},
                    "output_directory": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": False},
                    "timeout": {"type": "number", "minimum": 0.2, "maximum": 60, "default": 10},
                    "retries": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
                },
                "required": ["port", "output_directory"]
            }
        ),
        Tool(
            name="serial_list_macros",
            description="列出后端已配置的串口命令宏",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        Tool(
            name="serial_run_macro",
            description="在指定串口运行已配置命令宏，并返回设备输出",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "string"},
                    "macro_id": {"type": "string"},
                    "run_id": {"type": "string", "description": "可选调用方运行 ID"}
                },
                "required": ["port", "macro_id"]
            }
        ),
        Tool(
            name="serial_cancel_macro",
            description="取消当前 MCP 客户端发起的命令宏",
            inputSchema={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"]
            }
        ),
        Tool(
            name="serial_get_health",
            description="读取设备健康规则产生的最近事件",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}
                },
                "required": []
            }
        ),
        Tool(
            name="serial_get_diagnostic_schedules",
            description="列出定时诊断计划及最近运行状态",
            inputSchema={"type": "object", "properties": {}, "required": []}
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
                        "default": 100,
                        "minimum": 1,
                        "maximum": 1000
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
            settings = {
                "port": port,
                "baudrate": arguments.get("baudrate", 115200),
                "bytesize": arguments.get("bytesize", 8),
                "parity": arguments.get("parity", "N"),
                "stopbits": arguments.get("stopbits", 1),
                "xonxoff": arguments.get("xonxoff", False),
                "rtscts": arguments.get("rtscts", False),
                "dsrdtr": arguments.get("dsrdtr", False),
                "dtr": arguments.get("dtr"),
                "rts": arguments.get("rts"),
            }
            r = await api_post("/api/open", settings)
            ok = r.json().get("success", False)
            if ok:
                return [TextContent(type="text", text=f"✅ 串口已打开: {port} @ {settings['baudrate']}bps")]
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
            r = await api_post("/api/close", params={"port": port})
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
            r = await api_post(
                "/api/write-ai", {"data": data, "newline": newline}, params={"port": port}
            )
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
            wait_time = min(max(float(arguments.get("wait_time", 1.0)), 0.0), 30.0)
            newline = arguments.get("newline", "\r")
            lock = _port_locks.setdefault(port, asyncio.Lock())

            async with lock:
                before = await api_get("/api/history", params={"port": port, "limit": 1})
                prior = before.json()
                cursor = prior[-1].get("sequence", 0) if prior else 0

                r = await api_post(
                    "/api/write-ai", {"data": data, "newline": newline}, params={"port": port}
                )
                if not r.json().get("success", False):
                    return [TextContent(type="text", text=f"❌ 向 {port} 发送失败，串口可能未打开")]

                await asyncio.sleep(wait_time)
                r = await api_get("/api/history", params={"port": port, "limit": 500})
                history = r.json()
                device_msgs = [
                    item for item in history
                    if item.get("source") == "device" and item.get("sequence", 0) > cursor
                ]
                if device_msgs:
                    content = "".join(message["content"] for message in device_msgs)
                    return [TextContent(type="text", text=f"📤 [{port}] 发送: {data}\n📥 收到:\n{content}")]

            return [TextContent(type="text", text=f"📤 [{port}] 发送: {data}\n⏱️ 等待 {wait_time}s 后未收到响应")]

        elif name == "serial_is_open":
            port = arguments.get("port", "")
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_get("/api/status", params={"port": port})
            status = r.json()
            is_open = status.get("is_open", False)
            if is_open:
                return [TextContent(type="text", text=f"串口 {port} 状态: 已打开")]
            else:
                return [TextContent(type="text", text=f"串口 {port} 状态: 未打开")]

        elif name == "serial_get_lease":
            port = arguments.get("port", "")
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_get("/api/lease", params={"port": port})
            return [TextContent(type="text", text=f"[{port}] {_lease_text(r.json())}")]

        elif name == "serial_acquire_lease":
            port = arguments.get("port", "")
            ttl = min(max(float(arguments.get("ttl", 30)), 5), 300)
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_post("/api/lease/acquire", {"ttl": ttl}, params={"port": port})
            return [TextContent(type="text", text=f"✅ [{port}] 已获取写租约 ({ttl:g}s)")]

        elif name == "serial_release_lease":
            port = arguments.get("port", "")
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_post("/api/lease/release", params={"port": port})
            released = r.json().get("success", False)
            text = f"✅ [{port}] 写租约已释放" if released else f"[{port}] 当前 MCP 未持有写租约"
            return [TextContent(type="text", text=text)]

        elif name == "serial_send_protocol_file":
            port = arguments.get("port", "")
            path = Path(arguments.get("file_path", "")).expanduser()
            protocol = arguments.get("protocol", "xmodem")
            transfer_id = arguments.get("transfer_id") or f"mcp-{secrets.token_urlsafe(12)}"
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            if protocol not in {"xmodem", "xmodem1k", "ymodem"}:
                return [TextContent(type="text", text="错误: 不支持的传输协议")]
            if not path.is_file():
                return [TextContent(type="text", text=f"错误: 文件不存在: {path}")]
            data = path.read_bytes()
            if not data:
                return [TextContent(type="text", text="错误: 文件为空")]
            if len(data) > 32 * 1024 * 1024:
                return [TextContent(type="text", text="错误: 文件超过 32 MiB 限制")]
            r = await api_post_bytes("/api/transfer/send", data, params={
                "port": port,
                "transfer_id": transfer_id,
                "protocol": protocol,
                "filename": path.name,
                "timeout": min(max(float(arguments.get("timeout", 10)), 0.2), 60),
                "retries": min(max(int(arguments.get("retries", 10)), 1), 50),
            })
            result = r.json()
            return [TextContent(
                type="text",
                text=(
                    f"✅ [{port}] {protocol.upper()} 传输完成: {path.name}, "
                    f"{result.get('sent', len(data))} bytes, "
                    f"{result.get('blocks', 0)} blocks, {result.get('retries', 0)} retries"
                ),
            )]

        elif name == "serial_cancel_transfer":
            transfer_id = arguments.get("transfer_id", "")
            if not transfer_id:
                return [TextContent(type="text", text="错误: 请指定 transfer_id")]
            r = await api_post("/api/transfer/cancel", params={"transfer_id": transfer_id})
            cancelled = r.json().get("success", False)
            text = f"✅ 已请求取消传输 {transfer_id}" if cancelled else f"未找到可取消的传输 {transfer_id}"
            return [TextContent(type="text", text=text)]

        elif name == "serial_receive_protocol_file":
            port = arguments.get("port", "")
            output_path = Path(arguments.get("output_path", "")).expanduser()
            protocol = arguments.get("protocol", "xmodem")
            if not port or not str(output_path):
                return [TextContent(type="text", text="错误: 请指定 port 和 output_path")]
            transfer_id = f"mcp-rx-{secrets.token_urlsafe(10)}"
            params = {
                "port": port,
                "transfer_id": transfer_id,
                "protocol": protocol,
                "timeout": min(max(float(arguments.get("timeout", 10)), 0.2), 60),
                "retries": min(max(int(arguments.get("retries", 10)), 1), 50),
            }
            if arguments.get("expected_size") is not None:
                params["expected_size"] = max(int(arguments["expected_size"]), 0)
            response = await api_receive_bytes("/api/transfer/receive", params=params)
            filename = response.headers.get("X-AI-Serial-Filename", "")
            target = output_path / filename if output_path.is_dir() and filename else output_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            return [TextContent(type="text", text=f"✅ [{port}] 接收完成: {target} ({len(response.content)} bytes)")]

        elif name == "serial_receive_ymodem_batch":
            port = arguments.get("port", "")
            output_value = str(arguments.get("output_directory", "")).strip()
            if not port or not output_value:
                return [TextContent(type="text", text="错误: 请指定 port 和 output_directory")]
            output_directory = Path(output_value).expanduser().resolve()
            if output_directory.exists() and not output_directory.is_dir():
                return [TextContent(type="text", text=f"错误: 输出路径不是目录: {output_directory}")]

            transfer_id = f"mcp-rxb-{secrets.token_urlsafe(10)}"
            response = await api_receive_bytes("/api/transfer/receive-batch", params={
                "port": port,
                "transfer_id": transfer_id,
                "timeout": min(max(float(arguments.get("timeout", 10)), 0.2), 60),
                "retries": min(max(int(arguments.get("retries", 10)), 1), 50),
            })
            with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
                manifest_info = bundle.getinfo("manifest.json")
                if manifest_info.file_size > 1024 * 1024:
                    raise ValueError("批次清单超过 1 MiB 限制")
                manifest_bytes = bundle.read(manifest_info)
                manifest = json.loads(manifest_bytes)
                files = manifest.get("files", [])
                if not isinstance(files, list) or len(files) > MAX_BATCH_FILES:
                    raise ValueError("批次文件数量无效")

                prepared: list[tuple[Path, bytes]] = []
                filenames: set[str] = set()
                total_size = 0
                for item in files:
                    filename = str(item.get("filename", ""))
                    safe_name = Path(filename).name
                    if not safe_name or safe_name in {".", ".."} or safe_name != filename:
                        raise ValueError("批次清单包含不安全的文件名")
                    filename_key = safe_name.casefold()
                    if filename_key in filenames:
                        raise ValueError("批次清单包含重复文件名")
                    filenames.add(filename_key)
                    target = (output_directory / safe_name).resolve()
                    target.relative_to(output_directory)
                    archive_name = f"files/{safe_name}"
                    info = bundle.getinfo(archive_name)
                    declared_size = int(item.get("size", -1))
                    if declared_size < 0 or declared_size > MAX_FILE_SIZE or info.file_size != declared_size:
                        raise ValueError(f"文件大小校验失败: {safe_name}")
                    total_size += declared_size
                    if total_size > MAX_BATCH_SIZE:
                        raise ValueError("批次总大小超过 64 MiB 限制")
                    data = bundle.read(info)
                    if hashlib.sha256(data).hexdigest() != item.get("sha256"):
                        raise ValueError(f"SHA-256 校验失败: {safe_name}")
                    prepared.append((target, data))

            manifest_target = (output_directory / "manifest.json").resolve()
            manifest_target.relative_to(output_directory)
            if not arguments.get("overwrite", False):
                existing = [target for target, _ in prepared if target.exists()]
                if manifest_target.exists():
                    existing.append(manifest_target)
                if existing:
                    raise ValueError(f"目标已存在: {existing[0]}")
            output_directory.mkdir(parents=True, exist_ok=True)
            for target, data in prepared:
                target.write_bytes(data)
            manifest_target.write_bytes(manifest_bytes)
            return [TextContent(
                type="text",
                text=(
                    f"✅ [{port}] YMODEM 批量接收完成: {output_directory}，"
                    f"{len(prepared)} files, {total_size} bytes，清单: {manifest_target}"
                ),
            )]

        elif name == "serial_list_macros":
            response = await api_get("/api/automations")
            macros = response.json().get("macros", [])
            if not macros:
                return [TextContent(type="text", text="未配置命令宏")]
            lines = ["命令宏:"]
            for macro in macros:
                state = "enabled" if macro.get("enabled", True) else "disabled"
                lines.append(
                    f"- {macro.get('id', '')}: {macro.get('name', '')} "
                    f"({len(macro.get('steps', []))} steps, {state})"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "serial_run_macro":
            port = str(arguments.get("port", "")).strip()
            macro_id = str(arguments.get("macro_id", "")).strip()
            run_id = str(arguments.get("run_id", "")).strip() or f"mcp-macro-{secrets.token_urlsafe(10)}"
            if not port or not macro_id:
                return [TextContent(type="text", text="错误: 请指定 port 和 macro_id")]
            if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id) is None:
                return [TextContent(type="text", text="错误: run_id 格式无效")]
            response = await api_post_long(
                f"/api/automations/macros/{macro_id}/run",
                params={"port": port, "run_id": run_id},
            )
            result = response.json()
            output = str(result.get("output", ""))
            text = (
                f"[{port}] 宏 {macro_id} {result.get('status', 'unknown')}, "
                f"{result.get('steps_completed', 0)} steps"
            )
            if output:
                text += f"\n{output}"
            if result.get("error"):
                text += f"\n错误: {result['error']}"
            return [TextContent(type="text", text=text)]

        elif name == "serial_cancel_macro":
            run_id = str(arguments.get("run_id", "")).strip()
            if not run_id:
                return [TextContent(type="text", text="错误: 请指定 run_id")]
            response = await api_post(f"/api/automations/runs/{run_id}/cancel")
            cancelled = response.json().get("success", False)
            text = f"已请求取消宏 {run_id}" if cancelled else f"未找到可取消的宏 {run_id}"
            return [TextContent(type="text", text=text)]

        elif name == "serial_get_health":
            port = str(arguments.get("port", "")).strip()
            limit = min(max(int(arguments.get("limit", 100)), 1), 1000)
            response = await api_get(
                "/api/automations/health",
                params={"port": port, "limit": limit},
            )
            events = response.json()
            if not events:
                return [TextContent(type="text", text="暂无设备健康事件")]
            lines = ["设备健康事件:"]
            for event in events:
                lines.append(
                    f"- {event.get('severity', 'info')}: {event.get('message', '')} "
                    f"({event.get('content', '')})"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "serial_get_diagnostic_schedules":
            response = await api_get("/api/automations")
            payload = response.json()
            schedules = payload.get("schedules", [])
            status = payload.get("schedule_status", {})
            if not schedules:
                return [TextContent(type="text", text="未配置定时诊断")]
            lines = ["定时诊断:"]
            for schedule in schedules:
                schedule_id = schedule.get("id", "")
                state = status.get(schedule_id, {})
                lines.append(
                    f"- {schedule_id}: {schedule.get('name', '')} @ {schedule.get('port', '')}, "
                    f"enabled={schedule.get('enabled', False)}, "
                    f"last={state.get('last_status', 'idle')}"
                )
                if state.get("last_error"):
                    lines.append(f"  error: {state['last_error']}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "serial_get_history":
            port = arguments.get("port", "")
            limit = min(max(int(arguments.get("limit", 100)), 1), 1000)
            if not port:
                return [TextContent(type="text", text="错误: 请指定串口")]
            r = await api_get("/api/history", params={"port": port, "limit": limit})
            history = r.json()
            if not history:
                return [TextContent(type="text", text="暂无通信记录")]

            lines = [f"串口 {port} 通信历史:"]
            for h in history:
                ts = h.get("time_str", "")
                source = h.get("source", "")
                content = _event_content(h)
                prefix = "【设备】" if source == "device" else \
                         "【AI】" if source == "ai" else \
                         "【用户】" if source == "user" else "【系统】"
                lines.append(f"[{ts}] {prefix} {content}")
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except BackendDiscoveryError:
        return [TextContent(type="text", text="❌ 未发现可用的 AI Serial Bridge 后端，请先启动桌面程序或 main.py")]
    except (httpx.ConnectError, httpx.TimeoutException):
        return [TextContent(type="text", text="❌ 后端请求中断，请确认 AI Serial Bridge 仍在运行")]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            detail = e.response.json().get("detail", {})
            lease = detail.get("lease")
            return [TextContent(type="text", text=f"写入被拒绝：{_lease_text(lease)}")]
        return [TextContent(type="text", text=f"后端请求失败: HTTP {e.response.status_code}")]
    except Exception as e:
        return [TextContent(type="text", text=f"错误: {str(e)}")]


async def main():
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
