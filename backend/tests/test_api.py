"""FastAPI 接口测试：config、i18n 持久化、history 含 raw_hex、WS send_file。"""
import base64
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import serial_manager as sm_mod
import main
from serial_manager import serial_manager
from transfers import ActiveTransfer, ReceiveResult, TransferResult
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
