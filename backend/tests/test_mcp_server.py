"""MCP 工具回归测试：用消息序号关联命令响应。"""

import asyncio
from pathlib import Path
import uuid

import mcp_server


class FakeResponse:
    def __init__(self, payload, content=b"", headers=None):
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_write_then_read_uses_history_sequence_cursor(monkeypatch):
    async def fake_get(path, params=None):
        assert path == "/api/history"
        if params["limit"] == 1:
            return FakeResponse([{"sequence": 10, "source": "device", "content": "old"}])
        return FakeResponse([
            {"sequence": 9, "source": "device", "content": "stale"},
            {"sequence": 11, "source": "ai", "content": "AT"},
            {"sequence": 12, "source": "device", "content": "OK\r\n"},
        ])

    async def fake_post(path, json_data=None, params=None):
        assert path == "/api/write-ai"
        assert params == {"port": "COM_TEST"}
        return FakeResponse({"success": True})

    monkeypatch.setattr(mcp_server, "api_get", fake_get)
    monkeypatch.setattr(mcp_server, "api_post", fake_post)

    result = asyncio.run(mcp_server.call_tool(
        "serial_write_then_read",
        {"port": "COM_TEST", "data": "AT", "wait_time": 0, "newline": "\r\n"},
    ))
    text = result[0].text
    assert "OK" in text
    assert "stale" not in text


def test_default_port_supports_detailed_open_port_payload(monkeypatch):
    async def fake_get(path, params=None):
        assert path == "/api/open-ports"
        return FakeResponse({"ports": [{"port": "COM9", "settings": {"baudrate": 9600}}]})

    monkeypatch.setattr(mcp_server, "api_get", fake_get)
    assert asyncio.run(mcp_server._get_default_port()) == "COM9"


def test_open_forwards_advanced_serial_settings(monkeypatch):
    captured = {}

    async def fake_post(path, json_data=None, params=None):
        captured.update(json_data)
        return FakeResponse({"success": True})

    monkeypatch.setattr(mcp_server, "api_post", fake_post)
    result = asyncio.run(mcp_server.call_tool("serial_open", {
        "port": "COM_CFG",
        "baudrate": 57600,
        "bytesize": 7,
        "parity": "E",
        "stopbits": 2,
        "xonxoff": True,
        "rtscts": True,
        "dtr": False,
    }))

    assert "已打开" in result[0].text
    assert captured["bytesize"] == 7
    assert captured["parity"] == "E"
    assert captured["dtr"] is False


def test_structured_system_events_are_localized(monkeypatch):
    monkeypatch.setattr(mcp_server, "_LANG", "en")
    assert mcp_server._event_content({
        "event_code": "serial.read_error",
        "event_params": {"error": "device gone"},
    }) == "Serial read failed: device gone"


def test_client_headers_include_stable_identity(monkeypatch):
    monkeypatch.setattr(mcp_server, "_AUTH_TOKEN", "secret")
    first = mcp_server._client_headers()
    second = mcp_server._client_headers()
    assert first["X-AI-Serial-Client"] == second["X-AI-Serial-Client"]
    assert first["X-AI-Serial-Client-Label"]
    assert first["Authorization"] == "Bearer secret"


def test_protocol_file_tool_posts_exact_bytes(monkeypatch):
    path = Path.cwd() / ".test-artifacts" / f"fw-{uuid.uuid4().hex}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"firmware")
    captured = {}

    async def fake_post_bytes(endpoint, data, params=None):
        captured.update({"endpoint": endpoint, "data": data, "params": params})
        return FakeResponse({"sent": len(data), "blocks": 1, "retries": 0})

    monkeypatch.setattr(mcp_server, "api_post_bytes", fake_post_bytes)
    try:
        result = asyncio.run(mcp_server.call_tool("serial_send_protocol_file", {
            "port": "COM14",
            "file_path": str(path),
            "protocol": "ymodem",
        }))
        assert "传输完成" in result[0].text
        assert captured["data"] == b"firmware"
        assert captured["params"]["filename"] == path.name
    finally:
        path.unlink(missing_ok=True)


def test_receive_protocol_file_writes_exact_bytes(monkeypatch):
    path = Path.cwd() / ".test-artifacts" / f"rx-{uuid.uuid4().hex}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)

    async def fake_receive(endpoint, params=None):
        assert endpoint == "/api/transfer/receive"
        assert params["protocol"] == "xmodem"
        return FakeResponse({}, content=b"received", headers={})

    monkeypatch.setattr(mcp_server, "api_receive_bytes", fake_receive)
    try:
        result = asyncio.run(mcp_server.call_tool("serial_receive_protocol_file", {
            "port": "COM14",
            "output_path": str(path),
            "protocol": "xmodem",
            "expected_size": 8,
        }))
        assert "接收完成" in result[0].text
        assert path.read_bytes() == b"received"
    finally:
        path.unlink(missing_ok=True)
