"""MCP 工具回归测试：用消息序号关联命令响应。"""

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import uuid
import zipfile

import httpx
import pytest

import local_runtime
import mcp_server


class FakeResponse:
    def __init__(self, payload, content=b"", headers=None, status_code=200, request=None):
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code
        self.request = request or httpx.Request("GET", "http://test.invalid")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self,
            )


class FakeClient:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.trust_env_calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)


def test_mcp_dependency_stays_on_v1_api_line():
    requirements = (Path(__file__).parents[1] / "requirements-mcp.txt").read_text(
        encoding="utf-8"
    )

    assert "mcp>=1.0.0,<2.0.0" in requirements


def _use_fake_client(monkeypatch, handler):
    client = FakeClient(handler)

    async def get_client(*, trust_env=True):
        client.trust_env_calls.append(trust_env)
        return client

    monkeypatch.setattr(mcp_server, "_get_client", get_client)
    return client


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
    first = mcp_server._client_headers("secret")
    second = mcp_server._client_headers("secret")
    assert first["X-AI-Serial-Client"] == second["X-AI-Serial-Client"]
    assert first["X-AI-Serial-Client-Label"]
    assert first["Authorization"] == "Bearer secret"


def test_request_preflights_without_authorization(monkeypatch):
    target = local_runtime.ConnectionTarget(
        "http://127.0.0.1:8123",
        "saved-secret",
        "desktop-runtime",
        "desktop-a",
    )
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: [target],
    )

    def handler(method, url, kwargs):
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": "desktop-a",
                "auth_required": True,
            })
        return FakeResponse([{"device": "COM18"}])

    client = _use_fake_client(monkeypatch, handler)
    response = asyncio.run(mcp_server.api_get("/api/ports"))

    assert response.json() == [{"device": "COM18"}]
    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8123/api/config",
        "http://127.0.0.1:8123/api/ports",
    ]
    assert "Authorization" not in client.calls[0][2]["headers"]
    assert client.calls[1][2]["headers"]["Authorization"] == "Bearer saved-secret"
    assert client.trust_env_calls == [False]


def test_manifest_port_change_is_seen_without_mcp_restart(
    monkeypatch,
    tmp_path,
):
    token = local_runtime.load_or_create_token(state_dir=tmp_path)
    monkeypatch.setenv("AI_SERIAL_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("AI_SERIAL_API_URL", raising=False)
    monkeypatch.delenv("AI_SERIAL_TOKEN", raising=False)
    instances = {}

    def handler(method, url, kwargs):
        base = url.rsplit("/api/", 1)[0]
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": instances[base],
                "auth_required": True,
            })
        assert kwargs["headers"]["Authorization"] == f"Bearer {token}"
        return FakeResponse({"base": base})

    client = _use_fake_client(monkeypatch, handler)
    with local_runtime.desktop_instance_lock(state_dir=tmp_path) as instance_id:
        instances["http://127.0.0.1:8101"] = instance_id
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:8101",
            pid=os.getpid(),
            instance_id=instance_id,
            state_dir=tmp_path,
        )
        first = asyncio.run(mcp_server.api_get("/api/open-ports"))
    with local_runtime.desktop_instance_lock(state_dir=tmp_path) as instance_id:
        instances["http://127.0.0.1:8102"] = instance_id
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:8102",
            pid=os.getpid(),
            instance_id=instance_id,
            state_dir=tmp_path,
        )
        second = asyncio.run(mcp_server.api_get("/api/open-ports"))

    assert first.json()["base"] == "http://127.0.0.1:8101"
    assert second.json()["base"] == "http://127.0.0.1:8102"
    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8101/api/config",
        "http://127.0.0.1:8101/api/open-ports",
        "http://127.0.0.1:8102/api/config",
        "http://127.0.0.1:8102/api/open-ports",
    ]


def test_stale_loopback_token_retries_only_after_401(monkeypatch):
    targets = [
        local_runtime.ConnectionTarget("http://127.0.0.1:8000", "stale", "environment"),
        local_runtime.ConnectionTarget("http://127.0.0.1:8123", "saved", "desktop-runtime"),
    ]
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: targets,
    )

    def handler(method, url, kwargs):
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": "",
                "auth_required": True,
            })
        if url.startswith("http://127.0.0.1:8000"):
            return FakeResponse({}, status_code=401, request=httpx.Request(method, url))
        return FakeResponse({"ports": []})

    client = _use_fake_client(monkeypatch, handler)
    response = asyncio.run(mcp_server.api_get("/api/open-ports"))

    assert response.json() == {"ports": []}
    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8000/api/config",
        "http://127.0.0.1:8000/api/open-ports",
        "http://127.0.0.1:8123/api/config",
        "http://127.0.0.1:8123/api/open-ports",
    ]
    assert all(
        "Authorization" not in call[2]["headers"]
        for call in (client.calls[0], client.calls[2])
    )


def test_unreachable_loopback_preflight_falls_back_before_operation(monkeypatch):
    targets = [
        local_runtime.ConnectionTarget("http://127.0.0.1:8000", "stale", "environment"),
        local_runtime.ConnectionTarget("http://127.0.0.1:8123", "saved", "desktop-runtime"),
    ]
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: targets,
    )

    def handler(method, url, kwargs):
        if url == "http://127.0.0.1:8000/api/config":
            raise httpx.ConnectError("stale endpoint", request=httpx.Request(method, url))
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": "",
                "auth_required": True,
            })
        return FakeResponse([{"device": "COM18"}])

    client = _use_fake_client(monkeypatch, handler)
    response = asyncio.run(mcp_server.api_get("/api/ports"))

    assert response.json() == [{"device": "COM18"}]
    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8000/api/config",
        "http://127.0.0.1:8123/api/config",
        "http://127.0.0.1:8123/api/ports",
    ]


def test_url_only_loopback_config_never_sends_saved_token(
    monkeypatch,
    tmp_path,
):
    saved = local_runtime.load_or_create_token(state_dir=tmp_path)
    monkeypatch.setenv("AI_SERIAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("AI_SERIAL_API_URL", "http://127.0.0.1:8000")
    monkeypatch.delenv("AI_SERIAL_TOKEN", raising=False)

    with local_runtime.desktop_instance_lock(state_dir=tmp_path) as instance_id:
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:8123",
            pid=os.getpid(),
            instance_id=instance_id,
            state_dir=tmp_path,
        )

        def handler(method, url, kwargs):
            if url == "http://127.0.0.1:8000/api/config":
                return FakeResponse({
                    "service": "ai-serial-bridge",
                    "instance_id": "spoofed",
                    "auth_required": True,
                })
            if url.endswith("/api/config"):
                return FakeResponse({
                    "service": "ai-serial-bridge",
                    "instance_id": instance_id,
                    "auth_required": True,
                })
            return FakeResponse([])

        client = _use_fake_client(monkeypatch, handler)
        asyncio.run(mcp_server.api_get("/api/ports"))

    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8000/api/config",
        "http://127.0.0.1:8123/api/config",
        "http://127.0.0.1:8123/api/ports",
    ]
    assert "Authorization" not in client.calls[0][2]["headers"]
    assert "Authorization" not in client.calls[1][2]["headers"]
    assert client.calls[2][2]["headers"]["Authorization"] == f"Bearer {saved}"


def test_operation_read_timeout_is_not_retried(monkeypatch):
    targets = [
        local_runtime.ConnectionTarget("http://127.0.0.1:8101", "one", "first"),
        local_runtime.ConnectionTarget("http://127.0.0.1:8102", "two", "second"),
    ]
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: targets,
    )

    def handler(method, url, kwargs):
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": "",
                "auth_required": True,
            })
        raise httpx.ReadTimeout("ambiguous read", request=httpx.Request(method, url))

    client = _use_fake_client(monkeypatch, handler)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(mcp_server.api_get("/api/history"))

    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8101/api/config",
        "http://127.0.0.1:8101/api/history",
    ]


def test_ambiguous_post_failure_is_not_retried(monkeypatch):
    targets = [
        local_runtime.ConnectionTarget("http://127.0.0.1:8101", "one", "first"),
        local_runtime.ConnectionTarget("http://127.0.0.1:8102", "two", "second"),
    ]
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: targets,
    )

    def handler(method, url, kwargs):
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": "",
                "auth_required": True,
            })
        raise httpx.RemoteProtocolError(
            "connection closed after write",
            request=httpx.Request(method, url),
        )

    client = _use_fake_client(monkeypatch, handler)
    with pytest.raises(httpx.RemoteProtocolError):
        asyncio.run(mcp_server.api_post("/api/open", {"port": "COM18"}))

    assert [call[1] for call in client.calls] == [
        "http://127.0.0.1:8101/api/config",
        "http://127.0.0.1:8101/api/open",
    ]


def test_manifest_instance_mismatch_never_sends_token(monkeypatch):
    target = local_runtime.ConnectionTarget(
        "http://127.0.0.1:8123",
        "saved-secret",
        "desktop-runtime",
        "expected-instance",
    )
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: [target],
    )

    def handler(method, url, kwargs):
        return FakeResponse({
            "service": "ai-serial-bridge",
            "instance_id": "different-instance",
            "auth_required": True,
        })

    client = _use_fake_client(monkeypatch, handler)
    with pytest.raises(mcp_server.BackendDiscoveryError):
        asyncio.run(mcp_server.api_get("/api/ports"))

    assert len(client.calls) == 1
    assert "Authorization" not in client.calls[0][2]["headers"]


def test_explicit_api_path_prefix_is_preserved(monkeypatch):
    target = local_runtime.ConnectionTarget(
        "https://remote.example/bridge",
        "remote-secret",
        "environment",
    )
    monkeypatch.setattr(
        mcp_server.local_runtime,
        "resolve_connection_targets",
        lambda: [target],
    )

    def handler(method, url, kwargs):
        if url.endswith("/api/config"):
            return FakeResponse({
                "service": "ai-serial-bridge",
                "instance_id": "remote",
                "auth_required": True,
            })
        return FakeResponse([])

    client = _use_fake_client(monkeypatch, handler)
    asyncio.run(mcp_server.api_get("/api/ports"))

    assert [call[1] for call in client.calls] == [
        "https://remote.example/bridge/api/config",
        "https://remote.example/bridge/api/ports",
    ]
    assert client.trust_env_calls == [True]


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
