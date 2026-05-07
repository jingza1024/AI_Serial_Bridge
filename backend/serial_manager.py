"""
Serial Port Manager
共享串口管理模块，支持多客户端（Web UI + MCP）并发访问
"""

import serial
import serial.tools.list_ports
import threading
import time
from typing import Callable, Optional, List, Dict
from dataclasses import dataclass
from enum import Enum
from locales import t


class MessageSource(Enum):
    USER = "user"
    AI = "ai"
    DEVICE = "device"
    SYSTEM = "system"


@dataclass
class SerialMessage:
    source: MessageSource
    content: str
    timestamp: float
    raw_bytes: Optional[bytes] = None


class SerialManager:
    """线程安全的串口管理器"""

    def __init__(self):
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.RLock()
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._callbacks: List[Callable[[SerialMessage], None]] = []
        self._history: List[SerialMessage] = []
        self._history_lock = threading.Lock()
        self._max_history = 10000

    def list_ports(self) -> List[Dict[str, str]]:
        """列出所有可用串口"""
        ports = []
        for port in serial.tools.list_ports.comports():
            ports.append({
                "device": port.device,
                "description": port.description or "",
                "hwid": port.hwid or ""
            })
        return ports

    def is_open(self) -> bool:
        with self._lock:
            return self._serial is not None and self._serial.is_open

    def open(self, port: str, baudrate: int = 115200,
             bytesize: int = 8, parity: str = "N", stopbits: int = 1,
             timeout: float = 0.1) -> bool:
        """打开串口"""
        with self._lock:
            if self._serial is not None and self._serial.is_open:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_already_open_close_first", port=self._serial.port),
                    timestamp=time.time()
                ))
                self._close_internal()

            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                    timeout=timeout
                )
                self._running = True
                self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._read_thread.start()

                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_opened", port=port, baudrate=baudrate),
                    timestamp=time.time()
                ))
                return True
            except Exception as e:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_open_failed", error=str(e)),
                    timestamp=time.time()
                ))
                return False

    def close(self) -> bool:
        """关闭串口"""
        with self._lock:
            return self._close_internal()

    def _close_internal(self) -> bool:
        self._running = False
        if self._read_thread is not None:
            self._read_thread.join(timeout=1.0)
            self._read_thread = None

        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_closed", port=self._serial.port),
                    timestamp=time.time()
                ))
                self._serial = None
                return True
            except Exception as e:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_close_failed", error=str(e)),
                    timestamp=time.time()
                ))
                return False
        return True

    def write(self, data: str, source: MessageSource = MessageSource.USER,
              encoding: str = "utf-8", newline: str = "\r\n") -> bool:
        """发送字符串数据到串口
        newline: 行尾换行符，默认 \\r\\n（兼容大多数串口设备）
               可选: \\n (LF), \\r\\n (CRLF), \\r (CR), "" (无)
        """
        with self._lock:
            if self._serial is None or not self._serial.is_open:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_not_open"),
                    timestamp=time.time()
                ))
                return False

            try:
                # 追加换行符（如果指定了且数据末尾没有）
                if newline and not data.endswith(newline):
                    data = data + newline
                raw = data.encode(encoding)
                self._serial.write(raw)
                self._serial.flush()

                # 清理显示内容中的换行符，避免终端显示可见的 \r\n
                display = data.replace("\r", "").replace("\n", "")
                self._notify(SerialMessage(
                    source=source,
                    content=display,
                    timestamp=time.time(),
                    raw_bytes=raw
                ))
                return True
            except Exception as e:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("send_failed", error=str(e)),
                    timestamp=time.time()
                ))
                return False

    def write_raw(self, data: bytes, source: MessageSource = MessageSource.USER) -> bool:
        """发送原始字节到串口"""
        with self._lock:
            if self._serial is None or not self._serial.is_open:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_not_open"),
                    timestamp=time.time()
                ))
                return False

            try:
                self._serial.write(data)
                self._serial.flush()

                # 尝试以utf-8解码用于显示，失败则用hex
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.hex()

                # 清理显示内容中的换行符（只对非DEVICE消息）
                if source != MessageSource.DEVICE:
                    text = text.replace("\r", "").replace("\n", "")

                self._notify(SerialMessage(
                    source=source,
                    content=text,
                    timestamp=time.time(),
                    raw_bytes=data
                ))
                return True
            except Exception as e:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("send_failed", error=str(e)),
                    timestamp=time.time()
                ))
                return False

    def read(self, size: int = 1024, timeout: float = 1.0) -> Optional[str]:
        """同步读取数据（用于MCP等场景）"""
        with self._lock:
            if self._serial is None or not self._serial.is_open:
                return None

            start = time.time()
            buffer = bytearray()
            while (time.time() - start) < timeout:
                available = self._serial.in_waiting
                if available > 0:
                    chunk = self._serial.read(min(available, size - len(buffer)))
                    buffer.extend(chunk)
                    if len(buffer) >= size:
                        break
                time.sleep(0.01)

            if buffer:
                try:
                    return buffer.decode("utf-8")
                except UnicodeDecodeError:
                    return buffer.hex()
            return None

    def register_callback(self, callback: Callable[[SerialMessage], None]):
        """注册数据接收回调"""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[SerialMessage], None]):
        """注销回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def get_history(self, limit: int = 1000) -> List[SerialMessage]:
        """获取历史记录"""
        with self._history_lock:
            return self._history[-limit:]

    def _read_loop(self):
        """后台读取线程"""
        while self._running:
            try:
                if self._serial is None or not self._serial.is_open:
                    time.sleep(0.05)
                    continue

                # in_waiting 是线程安全的，不需要加锁
                available = self._serial.in_waiting
                if available > 0:
                    with self._lock:
                        # 双重检查
                        if self._serial is None or not self._serial.is_open:
                            continue
                        data = self._serial.read(min(available, 4096))
                    if data:
                        try:
                            text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            text = data.hex()

                        msg = SerialMessage(
                            source=MessageSource.DEVICE,
                            content=text,
                            timestamp=time.time(),
                            raw_bytes=data
                        )
                        self._notify(msg)
                else:
                    time.sleep(0.002)  # 2ms 轮询，降低延迟
            except Exception as e:
                if self._running:
                    self._notify(SerialMessage(
                        source=MessageSource.SYSTEM,
                        content=t("read_error", error=str(e)),
                        timestamp=time.time()
                    ))
                time.sleep(0.05)

    def _notify(self, message: SerialMessage):
        """通知所有回调并保存历史"""
        with self._history_lock:
            self._history.append(message)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        for cb in self._callbacks:
            try:
                cb(message)
            except Exception:
                pass


# 全局单例 - 多串口管理器
class SerialPortManager:
    """管理多个串口连接，支持同时打开多个设备"""

    def __init__(self):
        self._ports: Dict[str, SerialManager] = {}
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[str, SerialMessage], None]] = []

    def list_ports(self) -> List[Dict[str, str]]:
        return SerialManager().list_ports()

    def get_open_ports(self) -> List[str]:
        """获取当前已打开的串口列表"""
        with self._lock:
            return [p for p, sm in self._ports.items() if sm.is_open()]

    def is_open(self, port: str) -> bool:
        with self._lock:
            if port not in self._ports:
                return False
            return self._ports[port].is_open()

    def open(self, port: str, baudrate: int = 115200) -> bool:
        """打开指定串口"""
        with self._lock:
            if port in self._ports and self._ports[port].is_open():
                # 已经打开，直接返回成功
                return True

            sm = SerialManager()
            # 包装回调，带上 port 信息
            def make_callback(port_name: str):
                def callback(msg: SerialMessage):
                    for cb in self._callbacks:
                        cb(port_name, msg)
                return callback
            sm.register_callback(make_callback(port))

            ok = sm.open(port, baudrate)
            if ok:
                self._ports[port] = sm
            return ok

    def close(self, port: str) -> bool:
        """关闭指定串口"""
        with self._lock:
            if port not in self._ports:
                return False
            sm = self._ports.pop(port)
            return sm.close()

    def write(self, port: str, data: str, source: MessageSource = MessageSource.USER,
              encoding: str = "utf-8", newline: str = "\r\n") -> bool:
        """向指定串口发送数据"""
        with self._lock:
            if port not in self._ports:
                return False
            return self._ports[port].write(data, source, encoding, newline)

    def write_raw(self, port: str, data: bytes, source: MessageSource = MessageSource.USER) -> bool:
        """向指定串口发送原始字节"""
        with self._lock:
            if port not in self._ports:
                return False
            return self._ports[port].write_raw(data, source)

    def read(self, port: str, size: int = 1024, timeout: float = 1.0) -> Optional[str]:
        """从指定串口读取数据"""
        with self._lock:
            if port not in self._ports:
                return None
            return self._ports[port].read(size, timeout)

    def get_history(self, port: str, limit: int = 1000) -> List[SerialMessage]:
        """获取指定串口的历史记录"""
        with self._lock:
            if port not in self._ports:
                return []
            return self._ports[port].get_history(limit)

    def register_callback(self, callback: Callable[[str, SerialMessage], None]):
        """注册数据接收回调，参数: (port, message)"""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[str, SerialMessage], None]):
        if callback in self._callbacks:
            self._callbacks.remove(callback)


serial_manager = SerialPortManager()
