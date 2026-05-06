"""
AI Serial Bridge - FastAPI Backend
提供 HTTP API + WebSocket 实时数据推送
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from serial_manager import SerialManager, serial_manager, MessageSource, SerialMessage


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


def on_serial_message(msg: SerialMessage):
    """串口消息回调 -> 广播到所有 WebSocket 客户端
    注意：此回调运行在后台读取线程，必须用 run_coroutine_threadsafe
    """
    if _event_loop is None:
        return
    asyncio.run_coroutine_threadsafe(manager.broadcast({
        "type": "serial_message",
        "source": msg.source.value,
        "content": msg.content,
        "timestamp": msg.timestamp,
        "time_str": time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
    }), _event_loop)


async def broadcast_status():
    """广播当前串口状态给所有 WebSocket 客户端"""
    await manager.broadcast({
        "type": "status",
        "is_open": serial_manager.is_open(),
        "port": serial_manager._serial.port if serial_manager._serial else None,
        "baudrate": serial_manager._serial.baudrate if serial_manager._serial else None
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
    serial_manager.close()


app = FastAPI(title="AI Serial Bridge", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/ports")
async def list_ports() -> List[PortInfo]:
    """列出可用串口"""
    return [PortInfo(**p) for p in serial_manager.list_ports()]


@app.post("/api/open")
async def open_port(req: OpenPortRequest):
    """打开串口"""
    ok = serial_manager.open(req.port, req.baudrate)
    if ok:
        await broadcast_status()
    return {"success": ok, "port": req.port, "baudrate": req.baudrate}


@app.post("/api/close")
async def close_port():
    """关闭串口"""
    ok = serial_manager.close()
    if ok:
        await broadcast_status()
    return {"success": ok}


@app.get("/api/status")
async def get_status():
    """获取串口状态"""
    return {
        "is_open": serial_manager.is_open(),
        "port": serial_manager._serial.port if serial_manager._serial else None,
        "baudrate": serial_manager._serial.baudrate if serial_manager._serial else None
    }


@app.post("/api/write")
async def write_data(req: WriteRequest):
    """发送数据到串口"""
    ok = serial_manager.write(req.data, MessageSource.USER, req.encoding, req.newline)
    return {"success": ok}


@app.post("/api/write-ai")
async def write_ai_data(req: WriteRequest):
    """AI 发送数据到串口（前端通过此接口标记来源为AI）"""
    ok = serial_manager.write(req.data, MessageSource.AI, req.encoding, req.newline)
    return {"success": ok}


@app.get("/api/history")
async def get_history(limit: int = 1000):
    """获取历史消息"""
    history = serial_manager.get_history(limit)
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

    # 发送当前状态
    await websocket.send_json({
        "type": "status",
        "is_open": serial_manager.is_open(),
        "port": serial_manager._serial.port if serial_manager._serial else None,
        "baudrate": serial_manager._serial.baudrate if serial_manager._serial else None
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                action = cmd.get("action")

                if action == "write":
                    text = cmd.get("data", "")
                    source_val = cmd.get("source", "user")
                    newline = cmd.get("newline", "\r\n")
                    source = MessageSource.USER if source_val == "user" else MessageSource.AI
                    serial_manager.write(text, source, newline=newline)

                elif action == "raw_write":
                    text = cmd.get("data", "")
                    if text:
                        raw = text.encode("latin-1")
                        serial_manager.write_raw(raw, MessageSource.USER)

                elif action == "open":
                    port = cmd.get("port", "")
                    baud = cmd.get("baudrate", 115200)
                    ok = serial_manager.open(port, baud)
                    if ok:
                        await broadcast_status()

                elif action == "close":
                    ok = serial_manager.close()
                    if ok:
                        await broadcast_status()

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
