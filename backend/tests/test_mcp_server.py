"""MCP 工具回归测试：用消息序号关联命令响应。"""

import asyncio
import hashlib
import io
import json
from pathlib import Path
import uuid
import zipfile

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


def test_receive_ymodem_batch_verifies_and_writes_files(monkeypatch):
    files = {"a.bin": b"A", "b.bin": b"BC"}
    manifest = {
        "files": [
            {"filename": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ]
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            bundle.writestr(f"files/{name}", data)

    async def fake_receive(endpoint, params=None):
        assert endpoint == "/api/transfer/receive-batch"
        assert params["port"] == "COM14"
        return FakeResponse({}, content=archive.getvalue())

    monkeypatch.setattr(mcp_server, "api_receive_bytes", fake_receive)
    output_directory = Path.cwd() / ".test-artifacts" / f"batch-{uuid.uuid4().hex}"
    try:
        result = asyncio.run(mcp_server.call_tool("serial_receive_ymodem_batch", {
            "port": "COM14",
            "output_directory": str(output_directory),
        }))
        assert "批量接收完成" in result[0].text
        assert (output_directory / "a.bin").read_bytes() == b"A"
        assert (output_directory / "b.bin").read_bytes() == b"BC"
        assert json.loads((output_directory / "manifest.json").read_text())["files"] == manifest["files"]
    finally:
        for name in (*files, "manifest.json"):
            (output_directory / name).unlink(missing_ok=True)
        if output_directory.exists():
            output_directory.rmdir()


def test_receive_ymodem_batch_rejects_hash_mismatch_before_writing(monkeypatch):
    manifest = {"files": [{"filename": "fw.bin", "size": 4, "sha256": "0" * 64}]}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("files/fw.bin", b"DATA")

    async def fake_receive(endpoint, params=None):
        return FakeResponse({}, content=archive.getvalue())

    monkeypatch.setattr(mcp_server, "api_receive_bytes", fake_receive)
    output_directory = Path.cwd() / ".test-artifacts" / f"batch-{uuid.uuid4().hex}"
    result = asyncio.run(mcp_server.call_tool("serial_receive_ymodem_batch", {
        "port": "COM14",
        "output_directory": str(output_directory),
    }))
    assert "SHA-256 校验失败" in result[0].text
    assert not output_directory.exists()


def test_automation_tools_are_registered():
    names = {tool.name for tool in asyncio.run(mcp_server.list_tools())}
    assert {
        "serial_list_macros",
        "serial_run_macro",
        "serial_cancel_macro",
        "serial_get_health",
        "serial_get_diagnostic_schedules",
    }.issubset(names)


def test_list_and_run_macro_tools_proxy_automation_api(monkeypatch):
    calls = []

    async def fake_get(path, params=None):
        assert path == "/api/automations"
        return FakeResponse({
            "macros": [{"id": "linux-health", "name": "Linux health", "steps": [{"command": "uname -a"}]}],
            "schedules": [],
            "schedule_status": {},
        })

    async def fake_post_long(path, params=None):
        calls.append((path, params))
        return FakeResponse({
            "run_id": params["run_id"],
            "status": "completed",
            "output": "Linux 5.4\n",
            "steps_completed": 1,
        })

    monkeypatch.setattr(mcp_server, "api_get", fake_get)
    monkeypatch.setattr(mcp_server, "api_post_long", fake_post_long)
    listed = asyncio.run(mcp_server.call_tool("serial_list_macros", {}))
    assert "linux-health" in listed[0].text
    result = asyncio.run(mcp_server.call_tool("serial_run_macro", {
        "port": "COM14",
        "macro_id": "linux-health",
        "run_id": "mcp-health-1",
    }))
    assert "Linux 5.4" in result[0].text
    assert calls == [(
        "/api/automations/macros/linux-health/run",
        {"port": "COM14", "run_id": "mcp-health-1"},
    )]


def test_cancel_macro_tool_uses_caller_run_id(monkeypatch):
    captured = []

    async def fake_post(path, json_data=None, params=None):
        captured.append(path)
        return FakeResponse({"success": True, "run_id": "mcp-health-1"})

    monkeypatch.setattr(mcp_server, "api_post", fake_post)
    result = asyncio.run(mcp_server.call_tool("serial_cancel_macro", {"run_id": "mcp-health-1"}))
    assert "mcp-health-1" in result[0].text
    assert captured == ["/api/automations/runs/mcp-health-1/cancel"]


def test_health_and_schedule_tools_format_status(monkeypatch):
    async def fake_get(path, params=None):
        if path == "/api/automations/health":
            assert params == {"port": "COM14", "limit": 10}
            return FakeResponse([{
                "severity": "critical",
                "message": "Kernel panic detected",
                "content": "kernel panic",
            }])
        assert path == "/api/automations"
        return FakeResponse({
            "schedules": [{"id": "hourly", "name": "Hourly", "port": "COM14", "enabled": True}],
            "schedule_status": {"hourly": {"last_status": "completed", "last_error": ""}},
        })

    monkeypatch.setattr(mcp_server, "api_get", fake_get)
    health = asyncio.run(mcp_server.call_tool("serial_get_health", {"port": "COM14", "limit": 10}))
    schedules = asyncio.run(mcp_server.call_tool("serial_get_diagnostic_schedules", {}))
    assert "critical" in health[0].text
    assert "Kernel panic detected" in health[0].text
    assert "hourly" in schedules[0].text
    assert "completed" in schedules[0].text
