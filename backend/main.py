"""
AI Serial Bridge - FastAPI Backend
提供 HTTP API + WebSocket 实时数据推送
支持多串口同时连接
"""

import asyncio
import base64
import hmac
import io
import json
import os
import secrets
import threading
import time
import zipfile
from contextlib import asynccontextmanager, suppress
from functools import wraps
from typing import List, Literal

from pathlib import Path
from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from automations import (
    AutomationStore,
    DiagnosticSchedule,
    HealthEvent,
    HealthMonitor,
    HealthRule,
    MacroDefinition,
    MacroRuntime,
    SchedulePlanner,
)
from leases import LeaseResult, PortLease, port_leases
from log_store import serial_logs
from transfers import (
    DEFAULT_MAX_BATCH_FILES,
    DEFAULT_MAX_BATCH_SIZE,
    TransferCancelled,
    TransferError,
    serial_transfers,
)
from serial_manager import (
    serial_manager,
    MessageSource,
    SerialMessage,
    SerialRawChunk,
)


# --- 可选鉴权 token（opt-in）---
# MCP 使用 Bearer token；浏览器用主 token 换取短期 HttpOnly 会话。
# /api/config 仅返回是否需要鉴权，WebSocket 还会校验浏览器 Origin。
_AUTH_TOKEN = os.environ.get("AI_SERIAL_TOKEN", "").strip()
_SESSION_COOKIE = "ai_serial_session"
_SESSION_TTL = 12 * 60 * 60
_SESSIONS: dict[str, float] = {}

MAX_WS_TEXT = 64 * 1024
MAX_FILE_CHUNK = 8 * 1024
MAX_FILE_SIZE = 32 * 1024 * 1024
DEFAULT_LEASE_TTL = 30.0

automation_store = AutomationStore()
health_monitor = HealthMonitor(automation_store)
macro_runtime = MacroRuntime(
    automation_store,
    is_open=serial_manager.is_open,
    write=lambda port, command, newline: serial_manager.write(
        port, command, MessageSource.AI, "utf-8", newline
    ),
    get_history=serial_manager.get_history,
)
schedule_planner = SchedulePlanner(automation_store)


def _token_ok(provided: str) -> bool:
    """未启用 token 时一律放行；启用后使用恒定时间比较防止时序侧信道。"""
    if not _AUTH_TOKEN:
        return True
    return bool(provided) and hmac.compare_digest(provided, _AUTH_TOKEN)


def _bearer_token(headers) -> str:
    auth = headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _new_session() -> str:
    now = time.time()
    expired = [token for token, expires in _SESSIONS.items() if expires <= now]
    for token in expired:
        _SESSIONS.pop(token, None)
    while len(_SESSIONS) >= 32:
        _SESSIONS.pop(next(iter(_SESSIONS)))
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = now + _SESSION_TTL
    return token


def _session_ok(provided: str) -> bool:
    if not _AUTH_TOKEN:
        return True
    expires = _SESSIONS.get(provided, 0)
    if expires <= time.time():
        _SESSIONS.pop(provided, None)
        return False
    return True


def _request_authenticated(request: Request) -> bool:
    if not _AUTH_TOKEN:
        return True
    return _token_ok(_bearer_token(request.headers)) or _session_ok(
        request.cookies.get(_SESSION_COOKIE, "")
    )


class SerialSettingsRequest(BaseModel):
    baudrate: int = Field(default=115200, ge=50, le=4_000_000)
    bytesize: Literal[5, 6, 7, 8] = 8
    parity: Literal["N", "E", "O", "M", "S"] = "N"
    stopbits: Literal[1, 1.5, 2] = 1
    xonxoff: bool = False
    rtscts: bool = False
    dsrdtr: bool = False
    dtr: bool | None = None
    rts: bool | None = None


class OpenPortRequest(SerialSettingsRequest):
    port: str = Field(min_length=1, max_length=256)


class WriteRequest(BaseModel):
    data: str = Field(max_length=MAX_WS_TEXT)
    encoding: str = Field(default="utf-8", max_length=32)
    newline: Literal["", "\r", "\n", "\r\n"] = "\r\n"


class PortInfo(BaseModel):
    device: str
    description: str
    hwid: str


class WriteCommand(BaseModel):
    action: Literal["write"]
    port: str = Field(min_length=1, max_length=256)
    data: str = Field(max_length=MAX_WS_TEXT)
    newline: Literal["", "\r", "\n", "\r\n"] = "\r\n"


class RawWriteCommand(BaseModel):
    action: Literal["raw_write"]
    port: str = Field(min_length=1, max_length=256)
    data: str | None = Field(default=None, max_length=MAX_WS_TEXT)
    data_b64: str | None = Field(default=None, max_length=MAX_WS_TEXT * 2)


class SendFileCommand(BaseModel):
    action: Literal["send_file"]
    port: str = Field(min_length=1, max_length=256)
    transfer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    sequence: int = Field(ge=0)
    data: str = Field(max_length=MAX_FILE_CHUNK * 2)
    final: bool = False


class CancelFileCommand(BaseModel):
    action: Literal["cancel_file"]
    transfer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class OpenCommand(SerialSettingsRequest):
    action: Literal["open"]
    port: str = Field(min_length=1, max_length=256)


class PortCommand(BaseModel):
    action: Literal["close"]
    port: str = Field(min_length=1, max_length=256)


class ListPortsCommand(BaseModel):
    action: Literal["list_ports"]


class AcquireLeaseCommand(BaseModel):
    action: Literal["acquire_lease"]
    port: str = Field(min_length=1, max_length=256)
    ttl: float = Field(default=DEFAULT_LEASE_TTL, ge=5, le=300)


class ReleaseLeaseCommand(BaseModel):
    action: Literal["release_lease"]
    port: str = Field(min_length=1, max_length=256)


class LeaseRequest(BaseModel):
    ttl: float = Field(default=DEFAULT_LEASE_TTL, ge=5, le=300)


_COMMAND_MODELS = {
    "write": WriteCommand,
    "raw_write": RawWriteCommand,
    "send_file": SendFileCommand,
    "cancel_file": CancelFileCommand,
    "open": OpenCommand,
    "close": PortCommand,
    "list_ports": ListPortsCommand,
    "acquire_lease": AcquireLeaseCommand,
    "release_lease": ReleaseLeaseCommand,
}


def _parse_command(data: object):
    if not isinstance(data, dict):
        raise ValueError("command must be an object")
    model = _COMMAND_MODELS.get(data.get("action"))
    if model is None:
        raise ValueError("unknown action")
    return model.model_validate(data)


def _client_identity(request: Request, default_id: str, default_label: str) -> tuple[str, str]:
    client_id = request.headers.get("x-ai-serial-client", default_id).strip()[:64]
    client_label = request.headers.get("x-ai-serial-client-label", default_label).strip()[:64]
    return client_id or default_id, client_label or default_label


def _settings_dict(model: SerialSettingsRequest) -> dict:
    return model.model_dump(include={
        "baudrate", "bytesize", "parity", "stopbits",
        "xonxoff", "rtscts", "dsrdtr", "dtr", "rts",
    })


def _lease_dict(port: str, lease: PortLease | None = None) -> dict | None:
    current = lease if lease is not None else port_leases.get(port)
    if current is None:
        return None
    return {
        "port": port,
        "owner_id": current.owner_id,
        "owner_label": current.owner_label,
        "expires_at": current.expires_at,
    }


def _lease_conflict(port: str, result: LeaseResult) -> JSONResponse:
    return JSONResponse(
        {
            "detail": {
                "code": "lease.conflict",
                "lease": _lease_dict(port, result.lease),
            }
        },
        status_code=409,
    )


def _transfer_conflict(port: str) -> JSONResponse | None:
    active = serial_transfers.active_for_port(port)
    if active is None:
        return None
    return JSONResponse(
        {
            "detail": {
                "code": "transfer.busy",
                "transfer_id": active.transfer_id,
                "protocol": active.protocol,
                "port": port,
            }
        },
        status_code=409,
    )


def _open_port_details() -> list[dict]:
    details = serial_manager.get_open_ports_detail()
    for detail in details:
        detail["lease"] = _lease_dict(detail["port"])
    return details


# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = asyncio.Lock()

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)

    async def send(self, websocket: WebSocket, message: dict) -> bool:
        lock = self.active_connections.get(websocket)
        if lock is None:
            return False
        try:
            async with lock:
                await asyncio.wait_for(websocket.send_json(message), timeout=2.0)
            return True
        except Exception:
            self.disconnect(websocket)
            return False

    async def broadcast(self, message: dict):
        connections = list(self.active_connections)
        if connections:
            await asyncio.gather(*(self.send(connection, message) for connection in connections))


manager = ConnectionManager()
_event_loop: asyncio.AbstractEventLoop | None = None
_serial_event_queue: asyncio.Queue[
    tuple[str, str, SerialMessage | SerialRawChunk | HealthEvent]
] | None = None
_serial_event_worker_task: asyncio.Task | None = None
_automation_scheduler_task: asyncio.Task | None = None
_AUTOMATION_OWNER_ID = "automation-scheduler"
_AUTOMATION_OWNER_LABEL = "Scheduled diagnostics"
_port_operation_registry_lock = threading.Lock()
_port_operation_locks: dict[str, threading.Lock] = {}


def _try_port_operation(port: str) -> threading.Lock | None:
    with _port_operation_registry_lock:
        operation = _port_operation_locks.setdefault(port, threading.Lock())
    return operation if operation.acquire(blocking=False) else None


def _operation_conflict(port: str) -> JSONResponse:
    return JSONResponse(
        {"detail": {"code": "port.operation_busy", "port": port}},
        status_code=409,
    )


def _serialized_port_operation(endpoint):
    @wraps(endpoint)
    async def wrapper(*args, **kwargs):
        port = str(kwargs.get("port", ""))
        operation = _try_port_operation(port)
        if operation is None:
            return _operation_conflict(port)
        try:
            return await endpoint(*args, **kwargs)
        finally:
            operation.release()

    return wrapper


async def _serial_event_worker():
    assert _serial_event_queue is not None
    while True:
        kind, port, event = await _serial_event_queue.get()
        if kind == "message":
            assert isinstance(event, SerialMessage)
            await manager.broadcast({
                "type": "serial_message",
                "port": port,
                "source": event.source.value,
                "content": event.content,
                "raw_hex": event.raw_bytes.hex() if event.raw_bytes else "",
                "sequence": event.sequence,
                "event_code": event.event_code,
                "event_params": event.event_params,
                "timestamp": event.timestamp,
                "time_str": time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            })
            if (
                event.source == MessageSource.SYSTEM
                and event.event_code in {"port.closed", "serial.read_error"}
                and not serial_manager.is_open(port)
            ):
                port_leases.clear(port)
                await broadcast_status(port)
                await broadcast_open_ports()
                await broadcast_lease(port)
        else:
            if kind == "raw":
                assert isinstance(event, SerialRawChunk)
                await manager.broadcast({
                    "type": "serial_raw",
                    "port": port,
                    "raw_hex": event.data.hex(),
                    "sequence": event.sequence,
                    "timestamp": event.timestamp,
                })
            else:
                assert isinstance(event, HealthEvent)
                await manager.broadcast({"type": "health_event", **event.model_dump(mode="json")})
        _serial_event_queue.task_done()


def on_serial_message(port: str, msg: SerialMessage):
    """串口消息回调 -> 广播到所有 WebSocket 客户端
    注意：此回调运行在后台读取线程，必须用 run_coroutine_threadsafe
    """
    serial_logs.record_message(port, msg)
    health_events = health_monitor.observe(port, msg.content) if msg.source == MessageSource.DEVICE else []
    if _event_loop is None or _serial_event_queue is None:
        return

    def enqueue():
        assert _serial_event_queue is not None
        if _serial_event_queue.full():
            with suppress(asyncio.QueueEmpty):
                _serial_event_queue.get_nowait()
                _serial_event_queue.task_done()
        with suppress(asyncio.QueueFull):
            _serial_event_queue.put_nowait(("message", port, msg))
        for health_event in health_events:
            if _serial_event_queue.full():
                break
            with suppress(asyncio.QueueFull):
                _serial_event_queue.put_nowait(("health", port, health_event))

    _event_loop.call_soon_threadsafe(enqueue)


def on_serial_raw(port: str, chunk: SerialRawChunk):
    serial_logs.record_raw(port, chunk)
    if _event_loop is None or _serial_event_queue is None:
        return

    def enqueue():
        assert _serial_event_queue is not None
        if _serial_event_queue.full():
            with suppress(asyncio.QueueEmpty):
                _serial_event_queue.get_nowait()
                _serial_event_queue.task_done()
        with suppress(asyncio.QueueFull):
            _serial_event_queue.put_nowait(("raw", port, chunk))

    _event_loop.call_soon_threadsafe(enqueue)


async def broadcast_status(port: str):
    """广播指定串口状态给所有 WebSocket 客户端"""
    await manager.broadcast({
        "type": "status",
        "port": port,
        "is_open": serial_manager.is_open(port),
    })


async def broadcast_open_ports():
    """广播已打开的串口列表（含波特率，供 Web UI 同步标签）"""
    await manager.broadcast({
        "type": "open_ports",
        "ports": _open_port_details()
    })


async def broadcast_lease(port: str):
    await manager.broadcast({
        "type": "lease_status",
        "port": port,
        "lease": _lease_dict(port),
    })


async def broadcast_transfer(message: dict):
    await manager.broadcast({"type": "transfer_progress", **message})


async def _run_due_schedules_once() -> None:
    for schedule in schedule_planner.due():
        schedule_planner.mark_started(schedule.id)
        operation = _try_port_operation(schedule.port)
        if operation is None:
            schedule_planner.record_result(schedule.id, "skipped", "port operation is active")
            continue
        run_id = ""
        try:
            if not serial_manager.is_open(schedule.port):
                schedule_planner.record_result(schedule.id, "skipped", "port is not open")
                continue
            if serial_transfers.active_for_port(schedule.port) is not None:
                schedule_planner.record_result(schedule.id, "skipped", "protocol transfer is active")
                continue
            lease = port_leases.ensure_writer(
                schedule.port, _AUTOMATION_OWNER_ID, _AUTOMATION_OWNER_LABEL, 300
            )
            if not lease.acquired:
                schedule_planner.record_result(
                    schedule.id, "skipped", "writer lease is held by another client"
                )
                continue
            run_id = f"schedule-{schedule.id}-{secrets.token_urlsafe(8)}"
            result = await asyncio.to_thread(
                macro_runtime.run_macro,
                run_id,
                schedule.macro_id,
                schedule.port,
                _AUTOMATION_OWNER_ID,
            )
            schedule_planner.record_result(
                schedule.id, result.status, result.error, run_id
            )
            await manager.broadcast({
                "type": "automation_run",
                **result.model_dump(mode="json"),
            })
        except Exception as exc:
            schedule_planner.record_result(schedule.id, "failed", str(exc), run_id)
        finally:
            port_leases.release(schedule.port, _AUTOMATION_OWNER_ID)
            await broadcast_lease(schedule.port)
            operation.release()


async def _automation_scheduler() -> None:
    while True:
        await _run_due_schedules_once()
        await asyncio.sleep(0.5)


async def reject_ws_transfer_busy(websocket: WebSocket, port: str) -> bool:
    active = serial_transfers.active_for_port(port)
    if active is None:
        return False
    await manager.send(websocket, {
        "type": "error",
        "code": "transfer.busy",
        "port": port,
        "transfer_id": active.transfer_id,
        "protocol": active.protocol,
    })
    return True


# 注册回调
serial_manager.register_callback(on_serial_message)
serial_manager.register_raw_callback(on_serial_raw)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global _event_loop, _serial_event_queue, _serial_event_worker_task, _automation_scheduler_task
    _event_loop = asyncio.get_running_loop()
    serial_logs.start()
    _serial_event_queue = asyncio.Queue(maxsize=1000)
    _serial_event_worker_task = asyncio.create_task(_serial_event_worker())
    _automation_scheduler_task = asyncio.create_task(_automation_scheduler())
    print("[AI Serial Bridge] 启动")
    print(f"[WebSocket] ws://localhost:{os.environ.get('AI_SERIAL_PORT', '8000')}/ws")
    print(f"[API] http://localhost:{os.environ.get('AI_SERIAL_PORT', '8000')}")
    if _AUTH_TOKEN:
        print("[Auth] token 鉴权已启用")
    try:
        yield
    finally:
        print("[Shutdown] 关闭中...")
        open_ports = serial_manager.get_open_ports()
        for port in open_ports:
            await asyncio.to_thread(serial_manager.close, port)
        await asyncio.to_thread(serial_logs.stop)
        if _automation_scheduler_task is not None:
            _automation_scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await _automation_scheduler_task
        _automation_scheduler_task = None
        if _serial_event_worker_task is not None:
            _serial_event_worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await _serial_event_worker_task
        _serial_event_worker_task = None
        _serial_event_queue = None
        _event_loop = None
        _SESSIONS.clear()
        port_leases.clear_all()


app = FastAPI(title="AI Serial Bridge", lifespan=lifespan)

# CORS 策略
# - 桌面模式：前端由本服务同源提供，CORS 实际不参与；显式允许回环地址即可。
# - 开发模式：仅允许本地 Vite 来源。
# 注意：绝不使用 allow_origins=["*"] + allow_credentials=True（CORS 规范禁止，
#       且会暴露硬件控制接口给任意跨站页面）。
_desktop_mode = os.environ.get('AI_SERIAL_DESKTOP', '') == '1'
_origins_env = os.environ.get("CORS_ORIGINS", "")
if _origins_env:
    _allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
elif _desktop_mode:
    _api_port = os.environ.get("AI_SERIAL_PORT", "8000")
    _allowed_origins = [
        f"http://127.0.0.1:{_api_port}",
        f"http://localhost:{_api_port}",
    ]
else:
    _allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """保护 API；config 与 session 仅用于安全会话引导。"""
    path = request.url.path
    public_paths = {"/api/config", "/api/session"}
    if _AUTH_TOKEN and path.startswith("/api") and path not in public_paths:
        if not _request_authenticated(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/api/config")
async def get_config():
    """仅返回鉴权状态，绝不向客户端公开主 token。"""
    return {"auth_required": bool(_AUTH_TOKEN)}


@app.post("/api/session")
async def create_session(request: Request, response: Response):
    """用主 token 换取短期 HttpOnly 浏览器会话。"""
    if not _AUTH_TOKEN or not _token_ok(_bearer_token(request.headers)):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    session = _new_session()
    response.set_cookie(
        _SESSION_COOKIE,
        session,
        max_age=_SESSION_TTL,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"success": True}


@app.delete("/api/session")
async def delete_session(request: Request, response: Response):
    session = request.cookies.get(_SESSION_COOKIE, "")
    _SESSIONS.pop(session, None)
    response.delete_cookie(_SESSION_COOKIE, path="/")
    return {"success": True}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "open_ports": len(serial_manager.get_open_ports()),
        "websocket_clients": len(manager.active_connections),
        "dropped_log_records": serial_logs.dropped_records,
        "persistent_logs": serial_logs.available,
    }


@app.get("/api/ports")
async def list_ports() -> List[PortInfo]:
    """列出可用串口"""
    ports = await asyncio.to_thread(serial_manager.list_ports)
    return [PortInfo(**p) for p in ports]


@app.get("/api/open-ports")
async def get_open_ports():
    """获取已打开串口的参数与当前写租约。"""
    return {"ports": _open_port_details()}


@app.get("/api/lease")
async def get_lease(port: str):
    return _lease_dict(port)


@app.post("/api/lease/acquire")
async def acquire_lease(request: Request, req: LeaseRequest, port: str):
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    result = port_leases.acquire(port, client_id, client_label, req.ttl)
    if not result.acquired:
        return _lease_conflict(port, result)
    await broadcast_lease(port)
    return {"success": True, "lease": _lease_dict(port, result.lease)}


@app.post("/api/lease/release")
async def release_lease(request: Request, port: str):
    client_id, _ = _client_identity(request, "rest-client", "REST client")
    released = port_leases.release(port, client_id)
    if released:
        await broadcast_lease(port)
    return {"success": released, "lease": _lease_dict(port)}


@app.post("/api/open")
async def open_port(request: Request, req: OpenPortRequest):
    """打开串口"""
    if conflict := _transfer_conflict(req.port):
        return conflict
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.acquire(req.port, client_id, client_label, DEFAULT_LEASE_TTL)
    if not lease.acquired:
        return _lease_conflict(req.port, lease)
    settings = _settings_dict(req)
    ok = await asyncio.to_thread(serial_manager.open, req.port, **settings)
    if ok:
        await broadcast_status(req.port)
        await broadcast_open_ports()
        await broadcast_lease(req.port)
    else:
        port_leases.release(req.port, client_id)
    return {
        "success": ok,
        "port": req.port,
        "baudrate": req.baudrate,
        "settings": settings,
        "lease": _lease_dict(req.port),
    }


@app.post("/api/close")
async def close_port(request: Request, port: str):
    """关闭指定串口"""
    if conflict := _transfer_conflict(port):
        return conflict
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    ok = await asyncio.to_thread(serial_manager.close, port)
    if ok:
        port_leases.clear(port)
        await broadcast_status(port)
        await broadcast_open_ports()
        await broadcast_lease(port)
    return {"success": ok, "port": port}


@app.get("/api/status")
async def get_status(port: str):
    """获取指定串口状态"""
    return {
        "port": port,
        "is_open": serial_manager.is_open(port),
    }


@app.post("/api/write")
async def write_data(request: Request, req: WriteRequest, port: str):
    """发送数据到指定串口"""
    if conflict := _transfer_conflict(port):
        return conflict
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    ok = await asyncio.to_thread(
        serial_manager.write, port, req.data, MessageSource.USER, req.encoding, req.newline
    )
    await broadcast_lease(port)
    return {"success": ok, "port": port}


@app.post("/api/write-ai")
async def write_ai_data(request: Request, req: WriteRequest, port: str):
    """AI 发送数据到指定串口"""
    if conflict := _transfer_conflict(port):
        return conflict
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    ok = await asyncio.to_thread(
        serial_manager.write, port, req.data, MessageSource.AI, req.encoding, req.newline
    )
    await broadcast_lease(port)
    return {"success": ok, "port": port}


@app.get("/api/history")
async def get_history(port: str, limit: int = Query(default=1000, ge=1, le=10000)):
    """获取指定串口的历史消息"""
    history = serial_manager.get_history(port, limit)
    return [
        {
            "source": h.source.value,
            "content": h.content,
            "raw_hex": h.raw_bytes.hex() if h.raw_bytes else "",
            "sequence": h.sequence,
            "event_code": h.event_code,
            "event_params": h.event_params,
            "timestamp": h.timestamp,
            "time_str": time.strftime("%H:%M:%S", time.localtime(h.timestamp))
        }
        for h in history
    ]


@app.get("/api/raw-history")
async def get_raw_history(port: str, limit: int = Query(default=1000, ge=1, le=10000)):
    return [
        {
            "raw_hex": chunk.data.hex(),
            "sequence": chunk.sequence,
            "timestamp": chunk.timestamp,
        }
        for chunk in serial_manager.get_raw_history(port, limit)
    ]


@app.get("/api/logs")
async def list_persistent_logs():
    return {
        "available": serial_logs.available,
        "error": serial_logs.last_error,
        "ports": await asyncio.to_thread(serial_logs.list_ports),
        "dropped_records": serial_logs.dropped_records,
        "encrypted": serial_logs.encrypted,
    }


@app.get("/api/logs/{port}")
async def query_persistent_logs(
    port: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    search: str = Query(default="", max_length=256),
    kind: Literal["", "message", "raw"] = "",
    session_id: str = Query(default="", max_length=160),
):
    return await asyncio.to_thread(serial_logs.query, port, limit, search, kind, session_id)


@app.get("/api/logs/{port}/sessions")
async def list_log_sessions(port: str):
    return await asyncio.to_thread(serial_logs.list_sessions, port)


@app.get("/api/logs/{port}/sessions-page")
async def page_log_sessions(
    port: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    return await asyncio.to_thread(serial_logs.page_sessions, port, offset, limit)


@app.post("/api/logs/retention")
async def apply_log_retention(days: int = Query(ge=1, le=3650)):
    removed = await asyncio.to_thread(serial_logs.purge_older_than, days)
    return {"success": True, "days": days, "removed_files": removed}


@app.delete("/api/logs/{port}")
async def clear_persistent_logs(port: str):
    removed = await asyncio.to_thread(serial_logs.clear, port)
    return {"success": True, "removed_files": removed}


def _automation_definitions() -> dict:
    return {
        "macros": [item.model_dump(mode="json") for item in automation_store.list_macros()],
        "rules": [item.model_dump(mode="json") for item in automation_store.list_rules()],
        "schedules": [item.model_dump(mode="json") for item in automation_store.list_schedules()],
        "schedule_status": {
            key: value.model_dump(mode="json")
            for key, value in schedule_planner.status().items()
        },
    }


def _definition_error(exc: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/automations")
async def list_automations():
    return _automation_definitions()


@app.put("/api/automations/macros/{macro_id}")
async def save_macro(macro_id: str, macro: MacroDefinition):
    if macro.id != macro_id:
        return JSONResponse({"detail": "macro id does not match path"}, status_code=400)
    automation_store.save_macro(macro)
    return {"success": True, "macro": macro.model_dump(mode="json")}


@app.delete("/api/automations/macros/{macro_id}")
async def delete_macro(macro_id: str):
    try:
        removed = automation_store.delete_macro(macro_id)
    except ValueError as exc:
        return _definition_error(exc)
    return {"success": removed, "macro_id": macro_id}


@app.put("/api/automations/rules/{rule_id}")
async def save_health_rule(rule_id: str, rule: HealthRule):
    if rule.id != rule_id:
        return JSONResponse({"detail": "rule id does not match path"}, status_code=400)
    automation_store.save_rule(rule)
    return {"success": True, "rule": rule.model_dump(mode="json")}


@app.delete("/api/automations/rules/{rule_id}")
async def delete_health_rule(rule_id: str):
    return {"success": automation_store.delete_rule(rule_id), "rule_id": rule_id}


@app.put("/api/automations/schedules/{schedule_id}")
async def save_diagnostic_schedule(schedule_id: str, schedule: DiagnosticSchedule):
    if schedule.id != schedule_id:
        return JSONResponse({"detail": "schedule id does not match path"}, status_code=400)
    try:
        automation_store.save_schedule(schedule)
    except ValueError as exc:
        return _definition_error(exc)
    return {"success": True, "schedule": schedule.model_dump(mode="json")}


@app.delete("/api/automations/schedules/{schedule_id}")
async def delete_diagnostic_schedule(schedule_id: str):
    return {"success": automation_store.delete_schedule(schedule_id), "schedule_id": schedule_id}


@app.post("/api/automations/macros/{macro_id}/run")
@_serialized_port_operation
async def run_macro(
    request: Request,
    macro_id: str,
    port: str,
    run_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
):
    transfer_conflict = _transfer_conflict(port)
    if transfer_conflict is not None:
        return transfer_conflict
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, 300)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    try:
        result = await asyncio.to_thread(
            macro_runtime.run_macro, run_id, macro_id, port, client_id
        )
    except ValueError as exc:
        return _definition_error(exc)
    finally:
        port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
        await broadcast_lease(port)
    return result.model_dump(mode="json")


@app.post("/api/automations/runs/{run_id}/cancel")
async def cancel_macro_run(request: Request, run_id: str):
    client_id, _ = _client_identity(request, "rest-client", "REST client")
    return {"success": macro_runtime.cancel(run_id, client_id), "run_id": run_id}


@app.get("/api/automations/runs")
async def list_macro_runs(port: str = "", limit: int = Query(default=100, ge=1, le=1000)):
    return [item.model_dump(mode="json") for item in macro_runtime.history(port, limit)]


@app.get("/api/automations/health")
async def list_health_events(port: str = "", limit: int = Query(default=100, ge=1, le=1000)):
    return [item.model_dump(mode="json") for item in health_monitor.history(port, limit)]


@app.post("/api/transfer/send")
@_serialized_port_operation
async def send_protocol_file(
    request: Request,
    port: str,
    transfer_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    protocol: Literal["xmodem", "xmodem1k", "ymodem"] = "xmodem",
    filename: str = Query(default="transfer.bin", min_length=1, max_length=255),
    timeout: float = Query(default=10.0, ge=0.2, le=60),
    retries: int = Query(default=10, ge=1, le=50),
):
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, 300)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        content_length = 0
    if content_length > MAX_FILE_SIZE:
        return JSONResponse({"detail": "file exceeds maximum size"}, status_code=413)
    data = await request.body()
    if not data:
        return JSONResponse({"detail": "file is empty"}, status_code=400)
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse({"detail": "file exceeds maximum size"}, status_code=413)

    loop = asyncio.get_running_loop()

    def progress(sent: int, total: int, block: int, retry_count: int) -> None:
        port_leases.ensure_writer(port, client_id, client_label, 300)
        payload = {
            "transfer_id": transfer_id,
            "port": port,
            "protocol": protocol,
            "sent": sent,
            "total": total,
            "block": block,
            "retries": retry_count,
            "complete": False,
        }
        loop.call_soon_threadsafe(lambda: asyncio.create_task(broadcast_transfer(payload)))

    try:
        result = await asyncio.to_thread(
            serial_transfers.send,
            transfer_id,
            port,
            client_id,
            protocol,
            data,
            filename,
            timeout,
            retries,
            progress,
        )
    except TransferCancelled as exc:
        await broadcast_transfer({
            "transfer_id": transfer_id,
            "port": port,
            "protocol": protocol,
            "error": str(exc),
            "cancelled": True,
            "complete": False,
        })
        return JSONResponse({"detail": str(exc), "cancelled": True}, status_code=409)
    except TransferError as exc:
        await broadcast_transfer({
            "transfer_id": transfer_id,
            "port": port,
            "protocol": protocol,
            "error": str(exc),
            "complete": False,
        })
        return JSONResponse({"detail": str(exc)}, status_code=400)
    finally:
        port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
        await broadcast_lease(port)

    payload = {
        "transfer_id": transfer_id,
        "port": port,
        "protocol": result.protocol,
        "sent": result.bytes_sent,
        "total": result.bytes_sent,
        "blocks": result.blocks,
        "retries": result.retries,
        "duration": result.duration,
        "complete": True,
    }
    await broadcast_transfer(payload)
    return {"success": True, **payload}


@app.post("/api/transfer/cancel")
async def cancel_protocol_file(request: Request, transfer_id: str):
    client_id, _ = _client_identity(request, "rest-client", "REST client")
    cancelled = serial_transfers.cancel(transfer_id, client_id)
    return {"success": cancelled, "transfer_id": transfer_id}


@app.post("/api/transfer/receive")
@_serialized_port_operation
async def receive_protocol_file(
    request: Request,
    port: str,
    transfer_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    protocol: Literal["xmodem", "ymodem"] = "xmodem",
    expected_size: int | None = Query(default=None, ge=0, le=MAX_FILE_SIZE),
    timeout: float = Query(default=10.0, ge=0.2, le=60),
    retries: int = Query(default=10, ge=1, le=50),
):
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, 300)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    loop = asyncio.get_running_loop()

    def progress(received: int, total: int, block: int, retry_count: int):
        port_leases.ensure_writer(port, client_id, client_label, 300)
        payload = {
            "transfer_id": transfer_id,
            "port": port,
            "protocol": f"receive-{protocol}",
            "sent": received,
            "total": total,
            "block": block,
            "retries": retry_count,
            "complete": False,
        }
        loop.call_soon_threadsafe(lambda: asyncio.create_task(broadcast_transfer(payload)))

    try:
        result = await asyncio.to_thread(
            serial_transfers.receive,
            transfer_id,
            port,
            client_id,
            protocol,
            expected_size,
            timeout,
            retries,
            progress,
        )
    except TransferCancelled as exc:
        return JSONResponse({"detail": str(exc), "cancelled": True}, status_code=409)
    except TransferError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    finally:
        port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
        await broadcast_lease(port)

    await broadcast_transfer({
        "transfer_id": transfer_id,
        "port": port,
        "protocol": f"receive-{protocol}",
        "sent": len(result.data),
        "total": len(result.data),
        "blocks": result.blocks,
        "retries": result.retries,
        "complete": True,
    })
    return Response(
        content=result.data,
        media_type="application/octet-stream",
        headers={
            "X-AI-Serial-Filename": result.filename.encode("ascii", errors="replace").decode("ascii"),
            "X-AI-Serial-Protocol": result.protocol,
            "X-AI-Serial-Blocks": str(result.blocks),
            "X-AI-Serial-Retries": str(result.retries),
        },
    )


@app.post("/api/transfer/receive-batch")
@_serialized_port_operation
async def receive_protocol_batch(
    request: Request,
    port: str,
    transfer_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    timeout: float = Query(default=10.0, ge=0.2, le=60),
    retries: int = Query(default=10, ge=1, le=50),
):
    client_id, client_label = _client_identity(request, "rest-client", "REST client")
    lease = port_leases.ensure_writer(port, client_id, client_label, 300)
    if not lease.acquired:
        return _lease_conflict(port, lease)
    loop = asyncio.get_running_loop()

    def progress(received: int, total: int, block: int, retry_count: int) -> None:
        port_leases.ensure_writer(port, client_id, client_label, 300)
        payload = {
            "transfer_id": transfer_id,
            "port": port,
            "protocol": "receive-ymodem-batch",
            "sent": received,
            "total": total,
            "block": block,
            "retries": retry_count,
            "complete": False,
        }
        loop.call_soon_threadsafe(lambda: asyncio.create_task(broadcast_transfer(payload)))

    try:
        result = await asyncio.to_thread(
            serial_transfers.receive_batch,
            transfer_id,
            port,
            client_id,
            timeout,
            retries,
            progress,
            DEFAULT_MAX_BATCH_FILES,
            MAX_FILE_SIZE,
            DEFAULT_MAX_BATCH_SIZE,
        )
    except TransferCancelled as exc:
        return JSONResponse({"detail": str(exc), "cancelled": True}, status_code=409)
    except TransferError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    finally:
        port_leases.ensure_writer(port, client_id, client_label, DEFAULT_LEASE_TTL)
        await broadcast_lease(port)

    total_bytes = sum(len(file.data) for file in result.files)
    manifest = {
        "protocol": result.protocol,
        "file_count": len(result.files),
        "total_bytes": total_bytes,
        "blocks": result.blocks,
        "retries": result.retries,
        "duration": result.duration,
        "files": [
            {"filename": file.filename, "size": len(file.data), "sha256": file.sha256}
            for file in result.files
        ],
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for file in result.files:
            bundle.writestr(f"files/{file.filename}", file.data)

    await broadcast_transfer({
        "transfer_id": transfer_id,
        "port": port,
        "protocol": "receive-ymodem-batch",
        "sent": total_bytes,
        "total": total_bytes,
        "blocks": result.blocks,
        "retries": result.retries,
        "files": len(result.files),
        "complete": True,
    })
    archive_port = "".join(char if char.isalnum() or char in "-_" else "_" for char in port)[:64] or "serial"
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="ymodem-{archive_port}-batch.zip"',
            "X-AI-Serial-Protocol": result.protocol,
            "X-AI-Serial-Files": str(len(result.files)),
            "X-AI-Serial-Bytes": str(total_bytes),
            "X-AI-Serial-Blocks": str(result.blocks),
            "X-AI-Serial-Retries": str(result.retries),
        },
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时数据推送"""
    origin = websocket.headers.get("origin")
    if origin and origin not in _allowed_origins:
        await websocket.close(code=1008, reason="origin not allowed")
        return

    if _AUTH_TOKEN and not _session_ok(websocket.cookies.get(_SESSION_COOKIE, "")):
        await websocket.close(code=1008, reason="authentication required")
        return

    await manager.connect(websocket)
    client_id = f"web-{secrets.token_urlsafe(12)}"
    client_label = "Web UI"
    file_transfers: dict[str, dict[str, int]] = {}

    await manager.send(websocket, {
        "type": "welcome",
        "client_id": client_id,
        "lease_ttl": DEFAULT_LEASE_TTL,
    })
    await manager.send(websocket, {
        "type": "open_ports",
        "ports": _open_port_details()
    })

    try:
        while True:
            try:
                command = _parse_command(await websocket.receive_json())

                if isinstance(command, WriteCommand):
                    if await reject_ws_transfer_busy(websocket, command.port):
                        continue
                    lease = port_leases.ensure_writer(
                        command.port, client_id, client_label, DEFAULT_LEASE_TTL
                    )
                    if not lease.acquired:
                        await manager.send(websocket, {
                            "type": "error",
                            "code": "lease.conflict",
                            "port": command.port,
                            "lease": _lease_dict(command.port, lease.lease),
                        })
                        continue
                    await asyncio.to_thread(
                        serial_manager.write,
                        command.port,
                        command.data,
                        MessageSource.USER,
                        "utf-8",
                        command.newline,
                    )
                    await broadcast_lease(command.port)

                elif isinstance(command, RawWriteCommand):
                    if await reject_ws_transfer_busy(websocket, command.port):
                        continue
                    lease = port_leases.ensure_writer(
                        command.port, client_id, client_label, DEFAULT_LEASE_TTL
                    )
                    if not lease.acquired:
                        await manager.send(websocket, {
                            "type": "error",
                            "code": "lease.conflict",
                            "port": command.port,
                            "lease": _lease_dict(command.port, lease.lease),
                        })
                        continue
                    if command.data_b64 is not None:
                        raw = base64.b64decode(command.data_b64, validate=True)
                    else:
                        raw = (command.data or "").encode("utf-8")
                    if len(raw) > MAX_WS_TEXT:
                        raise ValueError("raw payload too large")
                    if raw:
                        await asyncio.to_thread(
                            serial_manager.write_raw, command.port, raw, MessageSource.USER
                        )
                        await broadcast_lease(command.port)

                elif isinstance(command, SendFileCommand):
                    if await reject_ws_transfer_busy(websocket, command.port):
                        continue
                    lease = port_leases.ensure_writer(
                        command.port, client_id, client_label, DEFAULT_LEASE_TTL
                    )
                    if not lease.acquired:
                        await manager.send(websocket, {
                            "type": "error",
                            "code": "lease.conflict",
                            "port": command.port,
                            "lease": _lease_dict(command.port, lease.lease),
                        })
                        continue
                    state = file_transfers.setdefault(command.transfer_id, {"sequence": 0, "received": 0})
                    if command.sequence != state["sequence"]:
                        raise ValueError("unexpected file chunk sequence")
                    raw = base64.b64decode(command.data, validate=True)
                    if not raw or len(raw) > MAX_FILE_CHUNK:
                        raise ValueError("invalid file chunk size")
                    if state["received"] + len(raw) > MAX_FILE_SIZE:
                        raise ValueError("file exceeds maximum size")
                    ok = await asyncio.to_thread(
                        serial_manager.write_raw, command.port, raw, MessageSource.USER
                    )
                    if ok:
                        state["sequence"] += 1
                        state["received"] += len(raw)
                    await manager.send(websocket, {
                        "type": "file_ack",
                        "transfer_id": command.transfer_id,
                        "sequence": command.sequence,
                        "success": ok,
                        "received": state["received"],
                        "complete": bool(ok and command.final),
                    })
                    if command.final or not ok:
                        file_transfers.pop(command.transfer_id, None)
                    await broadcast_lease(command.port)

                elif isinstance(command, CancelFileCommand):
                    file_transfers.pop(command.transfer_id, None)
                    await manager.send(websocket, {
                        "type": "file_cancelled",
                        "transfer_id": command.transfer_id,
                    })

                elif isinstance(command, OpenCommand):
                    if await reject_ws_transfer_busy(websocket, command.port):
                        continue
                    lease = port_leases.acquire(
                        command.port, client_id, client_label, DEFAULT_LEASE_TTL
                    )
                    if not lease.acquired:
                        await manager.send(websocket, {
                            "type": "error",
                            "code": "lease.conflict",
                            "port": command.port,
                            "lease": _lease_dict(command.port, lease.lease),
                        })
                        continue
                    ok = await asyncio.to_thread(
                        serial_manager.open, command.port, **_settings_dict(command)
                    )
                    if ok:
                        await broadcast_status(command.port)
                        await broadcast_open_ports()
                        await broadcast_lease(command.port)
                    else:
                        port_leases.release(command.port, client_id)

                elif isinstance(command, PortCommand):
                    if await reject_ws_transfer_busy(websocket, command.port):
                        continue
                    lease = port_leases.ensure_writer(
                        command.port, client_id, client_label, DEFAULT_LEASE_TTL
                    )
                    if not lease.acquired:
                        await manager.send(websocket, {
                            "type": "error",
                            "code": "lease.conflict",
                            "port": command.port,
                            "lease": _lease_dict(command.port, lease.lease),
                        })
                        continue
                    ok = await asyncio.to_thread(serial_manager.close, command.port)
                    if ok:
                        port_leases.clear(command.port)
                        await broadcast_status(command.port)
                        await broadcast_open_ports()
                        await broadcast_lease(command.port)

                elif isinstance(command, AcquireLeaseCommand):
                    lease = port_leases.acquire(
                        command.port, client_id, client_label, command.ttl
                    )
                    if not lease.acquired:
                        await manager.send(websocket, {
                            "type": "error",
                            "code": "lease.conflict",
                            "port": command.port,
                            "lease": _lease_dict(command.port, lease.lease),
                        })
                        continue
                    await broadcast_lease(command.port)

                elif isinstance(command, ReleaseLeaseCommand):
                    port_leases.release(command.port, client_id)
                    await broadcast_lease(command.port)

                elif isinstance(command, ListPortsCommand):
                    ports = await asyncio.to_thread(serial_manager.list_ports)
                    await manager.send(websocket, {
                        "type": "port_list",
                        "ports": ports
                    })

            except (ValidationError, ValueError, TypeError, base64.binascii.Error) as exc:
                await manager.send(websocket, {
                    "type": "error",
                    "message": str(exc),
                })

    except WebSocketDisconnect:
        pass
    finally:
        released_ports = port_leases.release_owner(client_id)
        manager.disconnect(websocket)
        for port in released_ports:
            await broadcast_lease(port)


# --- 桌面模式：静态文件服务 ---
_base_dir = Path(__file__).parent.parent  # 项目根目录
_dist_dir = _base_dir / 'frontend' / 'dist'

if _desktop_mode and _dist_dir.is_dir():
    @app.get("/", include_in_schema=False)
    async def serve_index():
        """提供前端入口页面"""
        return FileResponse(str(_dist_dir / 'index.html'))

    # 挂载静态资源目录（JS、CSS、图片等）
    app.mount("/", StaticFiles(directory=str(_dist_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    _host = os.environ.get("AI_SERIAL_HOST", "127.0.0.1")
    _port = int(os.environ.get("AI_SERIAL_PORT", "8000"))
    uvicorn.run(app, host=_host, port=_port)
