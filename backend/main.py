"""
AI Serial Bridge - FastAPI Backend
提供 HTTP API + WebSocket 实时数据推送
支持多串口同时连接
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from serial_manager import SerialPortManager, serial_manager, MessageSource, SerialMessage
from locales import set_lang, get_lang


class OpenPortRequest(BaseModel):
    port: str
    baudrate: int = 115200


class WriteRequest(BaseModel):
    data: str
    encoding: str = "utf-8"
    newline: str = "\r\n"


class PortInfo(BaseModel):
    device: str
    description: str
    hwid: str


# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for d in disconnected:
            self.disconnect(d)


manager = ConnectionManager()
_event_loop: asyncio.AbstractEventLoop | None = None


def on_serial_message(port: str, msg: SerialMessage):
    """串口消息回调 -> 广播到所有 WebSocket 客户端
    注意：此回调运行在后台读取线程，必须用 run_coroutine_threadsafe
    """
    if _event_loop is None:
        return
    asyncio.run_coroutine_threadsafe(manager.broadcast({
        "type": "serial_message",
        "port": port,
        "source": msg.source.value,
        "content": msg.content,
        "timestamp": msg.timestamp,
        "time_str": time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
    }), _event_loop)


async def broadcast_status(port: str):
    """广播指定串口状态给所有 WebSocket 客户端"""
    await manager.broadcast({
        "type": "status",
        "port": port,
        "is_open": serial_manager.is_open(port),
    })


async def broadcast_open_ports():
    """广播已打开的串口列表"""
    await manager.broadcast({
        "type": "open_ports",
        "ports": serial_manager.get_open_ports()
    })


# 注册回调
serial_manager.register_callback(on_serial_message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    print("[AI Serial Bridge] 启动")
    print("[WebSocket] ws://localhost:8000/ws")
    print("[API] http://localhost:8000")
    yield
    print("[Shutdown] 关闭中...")
    for port in serial_manager.get_open_ports():
        serial_manager.close(port)


app = FastAPI(title="AI Serial Bridge", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/lang")
async def set_language(req: dict):
    """设置后端语言"""
    lang = req.get("lang", "zh")
    set_lang(lang)
    return {"lang": lang}


@app.get("/api/lang")
async def get_language():
    """获取当前后端语言"""
    return {"lang": get_lang()}


@app.get("/api/ports")
async def list_ports() -> List[PortInfo]:
    """列出可用串口"""
    return [PortInfo(**p) for p in serial_manager.list_ports()]


@app.get("/api/open-ports")
async def get_open_ports():
    """获取已打开的串口列表"""
    return {"ports": serial_manager.get_open_ports()}


@app.post("/api/open")
async def open_port(req: OpenPortRequest):
    """打开串口"""
    ok = serial_manager.open(req.port, req.baudrate)
    if ok:
        await broadcast_status(req.port)
        await broadcast_open_ports()
    return {"success": ok, "port": req.port, "baudrate": req.baudrate}


@app.post("/api/close")
async def close_port(port: str):
    """关闭指定串口"""
    ok = serial_manager.close(port)
    if ok:
        await broadcast_status(port)
        await broadcast_open_ports()
    return {"success": ok, "port": port}


@app.get("/api/status")
async def get_status(port: str):
    """获取指定串口状态"""
    return {
        "port": port,
        "is_open": serial_manager.is_open(port),
    }


@app.post("/api/write")
async def write_data(req: WriteRequest, port: str):
    """发送数据到指定串口"""
    ok = serial_manager.write(port, req.data, MessageSource.USER, req.encoding, req.newline)
    return {"success": ok, "port": port}


@app.post("/api/write-ai")
async def write_ai_data(req: WriteRequest, port: str):
    """AI 发送数据到指定串口"""
    ok = serial_manager.write(port, req.data, MessageSource.AI, req.encoding, req.newline)
    return {"success": ok, "port": port}


@app.get("/api/history")
async def get_history(port: str, limit: int = 1000):
    """获取指定串口的历史消息"""
    history = serial_manager.get_history(port, limit)
    return [
        {
            "source": h.source.value,
            "content": h.content,
            "timestamp": h.timestamp,
            "time_str": time.strftime("%H:%M:%S", time.localtime(h.timestamp))
        }
        for h in history
    ]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时数据推送"""
    await manager.connect(websocket)

    # 发送当前已打开的串口列表
    await websocket.send_json({
        "type": "open_ports",
        "ports": serial_manager.get_open_ports()
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                action = cmd.get("action")
                port = cmd.get("port", "")

                if action == "write":
                    text = cmd.get("data", "")
                    source_val = cmd.get("source", "user")
                    newline = cmd.get("newline", "\r\n")
                    source = MessageSource.USER if source_val == "user" else MessageSource.AI
                    serial_manager.write(port, text, source, newline=newline)

                elif action == "raw_write":
                    text = cmd.get("data", "")
                    if text:
                        raw = text.encode("latin-1")
                        serial_manager.write_raw(port, raw, MessageSource.USER)

                elif action == "open":
                    p = cmd.get("port", "")
                    baud = cmd.get("baudrate", 115200)
                    ok = serial_manager.open(p, baud)
                    if ok:
                        await broadcast_status(p)
                        await broadcast_open_ports()

                elif action == "close":
                    p = cmd.get("port", "")
                    ok = serial_manager.close(p)
                    if ok:
                        await broadcast_status(p)
                        await broadcast_open_ports()

                elif action == "list_ports":
                    ports = serial_manager.list_ports()
                    await websocket.send_json({
                        "type": "port_list",
                        "ports": ports
                    })

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
