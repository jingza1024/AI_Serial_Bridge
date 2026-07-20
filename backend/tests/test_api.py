"""FastAPI 接口测试：config、i18n 持久化、history 含 raw_hex、WS send_file。"""
import base64
import io
import json
import asyncio
import threading
import time
import zipfile
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import serial_manager as sm_mod
import main
from automations import AutomationStore, HealthEvent, MacroRunResult
from serial_manager import serial_manager
from transfers import ActiveTransfer, BatchFile, BatchReceiveResult, ReceiveResult, TransferResult
from fakeserial import FakeSerial


@pytest.fixture(autouse=True)
def _patch_serial(monkeypatch):
    monkeypatch.setattr(sm_mod.serial, "Serial", FakeSerial)


def _receive_initial(ws):
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome"
    assert welcome["client_id"].startswith("web-")
    opened = ws.receive_json()
    assert opened["type"] == "open_ports"
    return welcome, opened


def _ws_open(ws, port: str):
    ws.send_json({"action": "open", "port": port, "baudrate": 115200})
    while True:
        message = ws.receive_json()
        if message.get("type") == "open_ports" and any(
            item["port"] == port for item in message["ports"]
        ):
            return message


def test_config_endpoint_no_auth():
    with TestClient(main.app) as c:
        r = c.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert body == {"auth_required": False}


def test_config_never_discloses_token_and_session_cookie_authenticates(monkeypatch):
    monkeypatch.setattr(main, "_AUTH_TOKEN", "topsecret")

    with TestClient(main.app) as c:
        assert c.get("/api/config").json() == {"auth_required": True}
        assert c.get("/api/ports").status_code == 401
        assert c.post("/api/session").status_code == 401

        r = c.post("/api/session", headers={"Authorization": "Bearer topsecret"})
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert c.cookies.get(main._SESSION_COOKIE)
        assert c.get("/api/ports").status_code == 200


def test_websocket_rejects_untrusted_browser_origin():
    with TestClient(main.app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws", headers={"Origin": "https://evil.example"}):
                pass


def test_websocket_accepts_configured_origin():
    with TestClient(main.app) as c:
        with c.websocket_connect("/ws", headers={"Origin": "http://localhost:5173"}) as ws:
            _receive_initial(ws)


def test_backend_language_endpoints_are_removed():
    with TestClient(main.app) as c:
        assert c.post("/api/lang", json={"lang": "en"}).status_code == 404
        assert c.get("/api/lang").status_code == 404


def test_list_ports_returns_list():
    with TestClient(main.app) as c:
        r = c.get("/api/ports")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_open_ports_initially_empty_or_list():
    with TestClient(main.app) as c:
        r = c.get("/api/open-ports")
        assert r.status_code == 200
        assert "ports" in r.json()


def test_open_applies_advanced_settings_and_returns_them():
    with TestClient(main.app) as c:
        r = c.post("/api/open", json={
            "port": "COM_CFG",
            "baudrate": 57600,
            "bytesize": 7,
            "parity": "E",
            "stopbits": 2,
            "xonxoff": True,
            "rtscts": True,
            "dsrdtr": False,
            "dtr": False,
            "rts": True,
        }, headers={"X-AI-Serial-Client": "test-a"})
        assert r.status_code == 200
        assert r.json()["settings"]["parity"] == "E"
        detail = c.get("/api/open-ports").json()["ports"][0]
        assert detail["settings"]["bytesize"] == 7


def test_write_lease_prevents_interleaved_clients():
    with TestClient(main.app) as c:
        first = {"X-AI-Serial-Client": "client-a"}
        second = {"X-AI-Serial-Client": "client-b"}
        assert c.post("/api/open", json={"port": "COM_LEASE"}, headers=first).status_code == 200
        denied = c.post(
            "/api/write?port=COM_LEASE",
            json={"data": "NO", "newline": ""},
            headers=second,
        )
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "lease.conflict"

        status = c.get("/api/lease", params={"port": "COM_LEASE"}).json()
        assert status["owner_id"] == "client-a"
        assert c.post("/api/lease/release", params={"port": "COM_LEASE"}, headers=first).status_code == 200
        assert c.post(
            "/api/write?port=COM_LEASE",
            json={"data": "OK", "newline": ""},
            headers=second,
        ).status_code == 200


def test_history_contains_raw_hex():
    with TestClient(main.app) as c:
        assert c.post("/api/open", json={"port": "COM_H", "baudrate": 115200}).json()["success"] is True
        # 写入数据（不追加换行，便于断言 raw_hex）
        assert c.post("/api/write?port=COM_H", json={"data": "ABC", "newline": ""}).json()["success"] is True
        time.sleep(0.15)

        r = c.get("/api/history?port=COM_H")
        assert r.status_code == 200
        entries = r.json()
        # 至少存在一条带 raw_hex 的记录，且 ABC 的 hex 为 414243
        hexes = [e.get("raw_hex", "") for e in entries]
        assert "414243" in hexes
        assert all(isinstance(e.get("sequence"), int) for e in entries)
        system_entries = [entry for entry in entries if entry["source"] == "system"]
        assert all(entry.get("event_code") for entry in system_entries)


def test_raw_history_preserves_exact_received_bytes():
    with TestClient(main.app) as c:
        assert c.post("/api/open", json={"port": "COM_RAW"}).json()["success"] is True
        serial_manager._ports["COM_RAW"]._serial.feed(b"A\r\nB\x00\xff")
        time.sleep(0.15)

        chunks = c.get("/api/raw-history", params={"port": "COM_RAW"}).json()
        assert "410d0a4200ff" in [chunk["raw_hex"] for chunk in chunks]
        assert all(isinstance(chunk["sequence"], int) for chunk in chunks)


def test_protocol_transfer_endpoint_enforces_identity_and_returns_result(monkeypatch):
    captured = {}

    def fake_send(*args):
        captured["args"] = args
        progress = args[-1]
        progress(4, 4, 1, 0)
        return TransferResult("xmodem", 4, 1, 0, 0.1)

    monkeypatch.setattr(main.serial_transfers, "send", fake_send)
    with TestClient(main.app) as c:
        response = c.post(
            "/api/transfer/send",
            params={
                "port": "COM_X",
                "transfer_id": "tx-xmodem",
                "protocol": "xmodem",
                "filename": "fw.bin",
            },
            content=b"DATA",
            headers={"X-AI-Serial-Client": "transfer-client"},
        )
        assert response.status_code == 200
        assert response.json()["complete"] is True
        assert captured["args"][2] == "transfer-client"
        assert captured["args"][4] == b"DATA"


def test_normal_write_is_blocked_during_protocol_transfer(monkeypatch):
    active = ActiveTransfer("tx-busy", "COM_BUSY", "client-a", "xmodem", threading.Event())
    monkeypatch.setattr(main.serial_transfers, "active_for_port", lambda port: active if port == "COM_BUSY" else None)
    with TestClient(main.app) as c:
        response = c.post(
            "/api/write",
            params={"port": "COM_BUSY"},
            json={"data": "interleave", "newline": ""},
            headers={"X-AI-Serial-Client": "client-a"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "transfer.busy"


def test_persistent_log_endpoints_do_not_disclose_storage_path(monkeypatch):
    monkeypatch.setattr(main.serial_logs, "list_ports", lambda: [{"port": "COM14", "size": 10, "updated_at": 1.0}])
    monkeypatch.setattr(main.serial_logs, "query", lambda *args: [{"kind": "message", "content": "Linux"}])
    monkeypatch.setattr(main.serial_logs, "clear", lambda port: 2)
    with TestClient(main.app) as c:
        listed = c.get("/api/logs").json()
        assert "directory" not in listed
        assert listed["ports"][0]["port"] == "COM14"
        assert c.get("/api/logs/COM14", params={"search": "Linux"}).json()[0]["content"] == "Linux"
        assert c.delete("/api/logs/COM14").json()["removed_files"] == 2


def test_log_session_page_endpoint_is_bounded(monkeypatch):
    monkeypatch.setattr(main.serial_logs, "page_sessions", lambda port, offset, limit: {
        "items": [{"session_id": "s2", "records": 4}],
        "total": 3,
        "offset": offset,
        "limit": limit,
    })
    with TestClient(main.app) as c:
        response = c.get("/api/logs/COM14/sessions-page", params={"offset": 1, "limit": 1})
        assert response.status_code == 200
        assert response.json() == {
            "items": [{"session_id": "s2", "records": 4}],
            "total": 3,
            "offset": 1,
            "limit": 1,
        }


def test_automation_crud_endpoints_persist_definitions(monkeypatch):
    path = Path.cwd() / ".test-artifacts" / f"api-automations-{uuid.uuid4().hex}.json"
    store = AutomationStore(path)
    monkeypatch.setattr(main, "automation_store", store)
    try:
        with TestClient(main.app) as c:
            macro = {
                "id": "linux-health",
                "name": "Linux health",
                "steps": [{"command": "uname -a", "newline": "\r", "wait_seconds": 1}],
                "enabled": True,
            }
            assert c.put("/api/automations/macros/linux-health", json=macro).status_code == 200
            rule = {
                "id": "kernel-panic",
                "name": "Kernel panic",
                "pattern": "kernel panic",
                "severity": "critical",
                "message": "Kernel panic detected",
                "cooldown_seconds": 60,
                "enabled": True,
            }
            schedule = {
                "id": "hourly-health",
                "name": "Hourly health",
                "macro_id": "linux-health",
                "port": "COM14",
                "interval_seconds": 3600,
                "enabled": True,
            }
            assert c.put("/api/automations/rules/kernel-panic", json=rule).status_code == 200
            assert c.put("/api/automations/schedules/hourly-health", json=schedule).status_code == 200
            listed = c.get("/api/automations").json()
            assert listed["macros"] == [macro]
            assert listed["rules"] == [rule]
            assert listed["schedules"] == [schedule]
            blocked = c.delete("/api/automations/macros/linux-health")
            assert blocked.status_code == 400
            assert "referenced by a schedule" in blocked.json()["detail"]
            assert c.delete("/api/automations/schedules/hourly-health").status_code == 200
            assert c.delete("/api/automations/rules/kernel-panic").status_code == 200
            assert c.delete("/api/automations/macros/linux-health").status_code == 200
            cleared = c.get("/api/automations").json()
            assert cleared["macros"] == []
            assert cleared["rules"] == []
            assert cleared["schedules"] == []
    finally:
        path.unlink(missing_ok=True)


def test_macro_run_endpoint_respects_writer_lease(monkeypatch):
    result = MacroRunResult(
        run_id="run-1",
        macro_id="linux-health",
        port="COM_AUTO",
        owner_id="client-a",
        status="completed",
        output="Linux\n",
        steps_completed=1,
        started_at=1,
        finished_at=2,
    )
    captured = {}

    def fake_run(*args):
        captured["args"] = args
        return result

    monkeypatch.setattr(main.macro_runtime, "run_macro", fake_run)
    with TestClient(main.app) as c:
        first = {"X-AI-Serial-Client": "client-a"}
        second = {"X-AI-Serial-Client": "client-b"}
        assert c.post("/api/open", json={"port": "COM_AUTO"}, headers=first).status_code == 200
        denied = c.post(
            "/api/automations/macros/linux-health/run",
            params={"port": "COM_AUTO", "run_id": "run-1"},
            headers=second,
        )
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "lease.conflict"

        response = c.post(
            "/api/automations/macros/linux-health/run",
            params={"port": "COM_AUTO", "run_id": "run-1"},
            headers=first,
        )
        assert response.status_code == 200
        assert response.json()["output"] == "Linux\n"
        assert captured["args"][:4] == ("run-1", "linux-health", "COM_AUTO", "client-a")


def test_macro_run_endpoint_rejects_active_protocol_transfer(monkeypatch):
    active = ActiveTransfer("tx-busy", "COM_AUTO", "client-a", "ymodem", threading.Event())
    monkeypatch.setattr(main.serial_transfers, "active_for_port", lambda port: active)
    with TestClient(main.app) as c:
        response = c.post(
            "/api/automations/macros/linux-health/run",
            params={"port": "COM_AUTO", "run_id": "run-busy"},
            headers={"X-AI-Serial-Client": "client-a"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "transfer.busy"


def test_protocol_transfer_rejects_same_owner_while_macro_is_running(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    result = MacroRunResult(
        run_id="run-locked",
        macro_id="linux-health",
        port="COM_LOCKED",
        owner_id="shared-client",
        status="completed",
        steps_completed=1,
        started_at=1,
        finished_at=2,
    )

    def fake_run(*args):
        started.set()
        assert release.wait(2)
        return result

    monkeypatch.setattr(main.macro_runtime, "run_macro", fake_run)
    monkeypatch.setattr(
        main.serial_transfers,
        "send",
        lambda *args: TransferResult("xmodem", 1, 1, 0, 0.1),
    )
    headers = {"X-AI-Serial-Client": "shared-client"}
    with TestClient(main.app) as c:
        macro_response = {}

        def run_macro_request():
            macro_response["value"] = c.post(
                "/api/automations/macros/linux-health/run",
                params={"port": "COM_LOCKED", "run_id": "run-locked"},
                headers=headers,
            )

        thread = threading.Thread(target=run_macro_request)
        thread.start()
        assert started.wait(2)
        try:
            response = c.post(
                "/api/transfer/send",
                params={"port": "COM_LOCKED", "transfer_id": "tx-locked"},
                headers=headers,
                content=b"x",
            )
        finally:
            release.set()
            thread.join(2)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "port.operation_busy"
    assert macro_response["value"].status_code == 200


def test_automation_status_includes_health_events(monkeypatch):
    event = HealthEvent(
        event_id="health-1",
        rule_id="kernel-panic",
        port="COM14",
        severity="critical",
        message="Kernel panic detected",
        content="kernel panic",
        timestamp=1,
    )
    monkeypatch.setattr(main.health_monitor, "history", lambda port="", limit=100: [event])
    with TestClient(main.app) as c:
        response = c.get("/api/automations/health", params={"port": "COM14"})
        assert response.status_code == 200
        assert response.json()[0]["severity"] == "critical"


def test_serial_messages_are_observed_by_health_monitor(monkeypatch):
    observed = []
    monkeypatch.setattr(main.health_monitor, "observe", lambda port, content: observed.append((port, content)) or [])
    message = main.SerialMessage(
        source=main.MessageSource.DEVICE,
        content="kernel panic",
        timestamp=1,
        sequence=1,
    )

    main.on_serial_message("COM14", message)

    assert observed == [("COM14", "kernel panic")]


def test_due_schedule_runs_with_internal_lease(monkeypatch):
    schedule = main.DiagnosticSchedule(
        id="health-every-minute",
        name="Health every minute",
        macro_id="linux-health",
        port="COM14",
        interval_seconds=60,
        enabled=True,
    )
    marked = []
    recorded = []
    captured = {}
    result = MacroRunResult(
        run_id="scheduled-run",
        macro_id="linux-health",
        port="COM14",
        owner_id="automation-scheduler",
        status="completed",
        output="Linux\n",
        steps_completed=1,
        started_at=1,
        finished_at=2,
    )
    monkeypatch.setattr(main.schedule_planner, "due", lambda: [schedule])
    monkeypatch.setattr(main.schedule_planner, "mark_started", lambda schedule_id: marked.append(schedule_id))
    monkeypatch.setattr(
        main.schedule_planner,
        "record_result",
        lambda schedule_id, status, error="", run_id="": recorded.append((schedule_id, status, error, run_id)),
    )
    monkeypatch.setattr(main.serial_manager, "is_open", lambda port: True)
    monkeypatch.setattr(main.serial_transfers, "active_for_port", lambda port: None)

    def fake_run(*args):
        captured["args"] = args
        return result

    monkeypatch.setattr(main.macro_runtime, "run_macro", fake_run)
    asyncio.run(main._run_due_schedules_once())

    assert marked == [schedule.id]
    assert captured["args"][1:] == ("linux-health", "COM14", "automation-scheduler")
    assert recorded == [(schedule.id, "completed", "", captured["args"][0])]
    assert main.port_leases.get("COM14") is None


def test_due_schedule_skips_user_owned_lease(monkeypatch):
    schedule = main.DiagnosticSchedule(
        id="health-every-minute",
        name="Health every minute",
        macro_id="linux-health",
        port="COM14",
        interval_seconds=60,
        enabled=True,
    )
    recorded = []
    main.port_leases.acquire("COM14", "user-client", "User", 30)
    monkeypatch.setattr(main.schedule_planner, "due", lambda: [schedule])
    monkeypatch.setattr(main.schedule_planner, "mark_started", lambda schedule_id: None)
    monkeypatch.setattr(
        main.schedule_planner,
        "record_result",
        lambda schedule_id, status, error="", run_id="": recorded.append((status, error)),
    )
    monkeypatch.setattr(main.serial_manager, "is_open", lambda port: True)
    monkeypatch.setattr(main.serial_transfers, "active_for_port", lambda port: None)
    monkeypatch.setattr(main.macro_runtime, "run_macro", lambda *args: pytest.fail("macro must not run"))

    asyncio.run(main._run_due_schedules_once())

    assert recorded == [("skipped", "writer lease is held by another client")]


def test_due_schedule_records_runtime_error_and_continues(monkeypatch):
    schedules = [
        main.DiagnosticSchedule(
            id="broken",
            name="Broken",
            macro_id="linux-health",
            port="COM16",
            interval_seconds=60,
            enabled=True,
        ),
        main.DiagnosticSchedule(
            id="healthy",
            name="Healthy",
            macro_id="linux-health",
            port="COM17",
            interval_seconds=60,
            enabled=True,
        ),
    ]
    recorded = []
    monkeypatch.setattr(main.schedule_planner, "due", lambda: schedules)
    monkeypatch.setattr(main.schedule_planner, "mark_started", lambda schedule_id: None)
    monkeypatch.setattr(
        main.schedule_planner,
        "record_result",
        lambda schedule_id, status, error="", run_id="": recorded.append((schedule_id, status, error)),
    )
    monkeypatch.setattr(main.serial_manager, "is_open", lambda port: True)
    monkeypatch.setattr(main.serial_transfers, "active_for_port", lambda port: None)

    def fake_run(run_id, macro_id, port, owner_id):
        if port == "COM16":
            raise RuntimeError("serial history failed")
        return MacroRunResult(
            run_id=run_id,
            macro_id=macro_id,
            port=port,
            owner_id=owner_id,
            status="completed",
            started_at=1,
            finished_at=2,
        )

    monkeypatch.setattr(main.macro_runtime, "run_macro", fake_run)

    asyncio.run(main._run_due_schedules_once())

    assert recorded[0] == ("broken", "failed", "serial history failed")
    assert recorded[1] == ("healthy", "completed", "")


def test_protocol_receive_endpoint_returns_exact_bytes(monkeypatch):
    monkeypatch.setattr(main.serial_transfers, "receive", lambda *args: ReceiveResult(
        "ymodem", b"DATA", "fw.bin", 1, 0, 0.1
    ))
    with TestClient(main.app) as c:
        response = c.post(
            "/api/transfer/receive",
            params={"port": "COM_RX", "transfer_id": "rx-1", "protocol": "ymodem"},
            headers={"X-AI-Serial-Client": "receiver"},
        )
        assert response.status_code == 200
        assert response.content == b"DATA"
        assert response.headers["X-AI-Serial-Filename"] == "fw.bin"


def test_protocol_batch_receive_returns_zip_manifest(monkeypatch):
    monkeypatch.setattr(main.serial_transfers, "receive_batch", lambda *args: BatchReceiveResult(
        "ymodem-batch",
        (
            BatchFile("a.bin", b"A", "559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd"),
            BatchFile("b.bin", b"BC", "768921a22b8e190c2cfafeb068f0d6e700b5c00601e3b283e66dbf12e57c4096"),
        ),
        2,
        0,
        0.1,
    ))
    with TestClient(main.app) as c:
        response = c.post(
            "/api/transfer/receive-batch",
            params={"port": "COM_BATCH", "transfer_id": "rx-batch-1"},
            headers={"X-AI-Serial-Client": "receiver"},
        )
        assert response.status_code == 200
        assert response.headers["X-AI-Serial-Files"] == "2"
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            assert manifest["file_count"] == 2
            assert manifest["total_bytes"] == 3
            assert bundle.read("files/a.bin") == b"A"
            assert bundle.read("files/b.bin") == b"BC"


def test_ws_send_file_writes_bytes():
    with TestClient(main.app) as c:
        payload = base64.b64encode(b"\x10\x20\x30").decode()
        with c.websocket_connect("/ws") as ws:
            _receive_initial(ws)
            _ws_open(ws, "COM_W")
            ws.send_json({
                "action": "send_file",
                "port": "COM_W",
                "transfer_id": "tx-1",
                "sequence": 0,
                "data": payload,
                "final": True,
            })
            while True:
                ack = ws.receive_json()
                if ack.get("type") == "file_ack":
                    break
            assert ack == {
                "type": "file_ack",
                "transfer_id": "tx-1",
                "sequence": 0,
                "success": True,
                "received": 3,
                "complete": True,
            }

        fake = serial_manager._ports["COM_W"]._serial
        assert fake.written == b"\x10\x20\x30"


def test_ws_file_transfer_can_be_cancelled():
    with TestClient(main.app) as c:
        payload = base64.b64encode(b"chunk").decode()
        with c.websocket_connect("/ws") as ws:
            _receive_initial(ws)
            _ws_open(ws, "COM_CANCEL")
            ws.send_json({
                "action": "send_file",
                "port": "COM_CANCEL",
                "transfer_id": "tx-cancel",
                "sequence": 0,
                "data": payload,
                "final": False,
            })
            while ws.receive_json().get("type") != "file_ack":
                pass
            ws.send_json({"action": "cancel_file", "transfer_id": "tx-cancel"})
            while True:
                message = ws.receive_json()
                if message.get("type") == "file_cancelled":
                    break
            assert message["transfer_id"] == "tx-cancel"


def test_ws_write_action_echoes_to_serial():
    with TestClient(main.app) as c:
        with c.websocket_connect("/ws") as ws:
            _receive_initial(ws)
            _ws_open(ws, "COM_WW")
            ws.send_json({"action": "write", "port": "COM_WW", "data": "PING", "newline": ""})
            time.sleep(0.2)
        assert serial_manager._ports["COM_WW"]._serial.written == b"PING"


def test_ws_raw_write_accepts_unicode_as_utf8():
    with TestClient(main.app) as c:
        with c.websocket_connect("/ws") as ws:
            _receive_initial(ws)
            _ws_open(ws, "COM_UTF8")
            ws.send_json({"action": "raw_write", "port": "COM_UTF8", "data": "你"})
            time.sleep(0.1)
        assert serial_manager._ports["COM_UTF8"]._serial.written == "你".encode("utf-8")


def test_token_enforced_when_set(monkeypatch):
    """启用 token 后：config 放行、受保护接口 401、带正确 token 200。"""
    monkeypatch.setattr(main, "_AUTH_TOKEN", "topsecret")

    with TestClient(main.app) as c:
        # 注意：main 内的中间件闭包引用模块级 _AUTH_TOKEN，monkeypatch 模块属性后应生效
        assert c.get("/api/config").status_code == 200
        assert c.get("/api/ports").status_code == 401
        assert c.get("/api/ports", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/ports", headers={"Authorization": "Bearer topsecret"}).status_code == 200


def test_websocket_token_uses_session_cookie(monkeypatch):
    monkeypatch.setattr(main, "_AUTH_TOKEN", "topsecret")

    with TestClient(main.app) as c:
        c.post("/api/session", headers={"Authorization": "Bearer topsecret"})
        with c.websocket_connect("/ws", headers={"Origin": "http://localhost:5173"}) as ws:
            _receive_initial(ws)
