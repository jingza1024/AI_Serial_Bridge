"""
Serial Port Manager
共享串口管理模块，支持多客户端（Web UI + MCP）并发访问

并发模型说明：
- self._lock        保护 self._serial 引用与线程句柄的更换（open/close/重开）。
- self._io_lock     串行化对串口对象的实际 read/write IO，避免并发读写竞争。
- self._stop_event   读线程的停止信号。

关键不变量：读线程 *绝不* 获取 self._lock。
因此 open/close 在持有 self._lock 的情况下 join 读线程不会死锁，
读线程也不会因为 close 持锁而成为孤儿（旧版本的核心缺陷）。
"""

import serial
import serial.tools.list_ports
import threading
import time
from typing import Callable, Optional, List, Dict
from dataclasses import dataclass
from enum import Enum
from collections import deque
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


def _list_serial_ports() -> List[Dict[str, str]]:
    """枚举系统可用串口（模块级工具函数，避免无谓实例化 SerialManager）。"""
    ports = []
    for port in serial.tools.list_ports.comports():
        ports.append({
            "device": port.device,
            "description": port.description or "",
            "hwid": port.hwid or ""
        })
    return ports


class SerialManager:
    """线程安全的单串口管理器"""

    def __init__(self):
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.RLock()          # 保护 _serial / _read_thread 的更换
        self._io_lock = threading.Lock()        # 串行化实际 read/write IO
        self._read_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: List[Callable[[SerialMessage], None]] = []
        self._callbacks_lock = threading.Lock()
        self._history: deque = deque(maxlen=10000)

    @staticmethod
    def list_ports() -> List[Dict[str, str]]:
        """列出所有可用串口"""
        return _list_serial_ports()

    def is_open(self) -> bool:
        with self._lock:
            return self._serial is not None and self._serial.is_open

    def open(self, port: str, baudrate: int = 115200,
             bytesize: int = 8, parity: str = "N", stopbits: int = 1,
             timeout: float = 0.1) -> bool:
        """打开串口（若已打开则先安全关闭再重开）。"""
        with self._lock:
            if self._serial is not None and self._serial.is_open:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_already_open_close_first", port=self._serial.port),
                    timestamp=time.time()
                ))
                self._stop_and_close_locked()

            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                    timeout=timeout
                )
                self._stop_event.clear()
                self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._read_thread.start()

                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_opened", port=port, baudrate=baudrate),
                    timestamp=time.time()
                ))
                return True
            except Exception as e:
                self._serial = None
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_open_failed", error=str(e)),
                    timestamp=time.time()
                ))
                return False

    def close(self) -> bool:
        """关闭串口"""
        with self._lock:
            return self._stop_and_close_locked()

    def _stop_and_close_locked(self) -> bool:
        """在已持有 self._lock 的情况下：停读线程 -> 关串口。

        读线程不依赖 self._lock，因此这里的 join 不会死锁；
        join 完成后再操作串口对象，避免读线程读到正在关闭的句柄。
        """
        self._stop_event.set()
        thread = self._read_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._read_thread = None

        if self._serial is not None:
            try:
                with self._io_lock:
                    if self._serial.is_open:
                        self._serial.close()
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_closed", port=self._serial.port),
                    timestamp=time.time()
                ))
            except Exception as e:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_close_failed", error=str(e)),
                    timestamp=time.time()
                ))
            finally:
                self._serial = None
        return True

    def write(self, data: str, source: MessageSource = MessageSource.USER,
              encoding: str = "utf-8", newline: str = "\r\n") -> bool:
        """发送字符串数据到串口
        newline: 行尾换行符，默认 \\r\\n（兼容大多数串口设备）
               可选: \\n (LF), \\r\\n (CRLF), \\r (CR), "" (无)
        """
        with self._lock:
            ser = self._serial
            if ser is None or not ser.is_open:
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
                with self._io_lock:
                    ser.write(raw)
                    ser.flush()

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
            ser = self._serial
            if ser is None or not ser.is_open:
                self._notify(SerialMessage(
                    source=MessageSource.SYSTEM,
                    content=t("port_not_open"),
                    timestamp=time.time()
                ))
                return False

            try:
                with self._io_lock:
                    ser.write(data)
                    ser.flush()

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

    def register_callback(self, callback: Callable[[SerialMessage], None]):
        """注册数据接收回调"""
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[SerialMessage], None]):
        """注销回调"""
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def get_history(self, limit: int = 1000) -> List[SerialMessage]:
        """获取历史记录（最近 limit 条）"""
        with self._callbacks_lock:
            # deque 自带 maxlen 自动淘汰，直接取尾部即可
            snapshot = list(self._history)
        if limit and limit > 0:
            return snapshot[-limit:]
        return snapshot

    def _read_loop(self):
        """后台读取线程 - 带行缓冲。

        线程不获取 self._lock，仅用 self._io_lock 串行化实际读取，
        使 open/close 能够安全地 join 本线程。
        """
        buffer = bytearray()
        last_recv_time = 0.0
        LINE_TIMEOUT = 0.05  # 50ms 无新数据则发送缓冲区内容

        while not self._stop_event.is_set():
            try:
                # 快照串口句柄（open/close 在更换句柄前会 join 本线程，故快照安全）
                ser = self._serial
                if ser is None or not ser.is_open:
                    if self._stop_event.wait(0.05):
                        break
                    continue

                available = ser.in_waiting
                if available > 0:
                    with self._io_lock:
                        if self._stop_event.is_set() or ser is not self._serial:
                            break
                        chunk = ser.read(min(available, 4096))
                    if chunk:
                        buffer.extend(chunk)
                        last_recv_time = time.time()
                        # _drain_lines 通过 del 原地消费 buffer 中已完整的行
                        self._drain_lines(buffer)
                else:
                    # 检查缓冲区超时（设备输出不以换行结束的情况）
                    if buffer and last_recv_time > 0:
                        if (time.time() - last_recv_time) >= LINE_TIMEOUT:
                            self._flush_partial(buffer)
                            buffer.clear()
                            last_recv_time = 0.0
                    # 用 wait 替代 sleep，可被 stop_event 立即唤醒
                    if self._stop_event.wait(0.002):
                        break
            except Exception as e:
                if not self._stop_event.is_set():
                    self._notify(SerialMessage(
                        source=MessageSource.SYSTEM,
                        content=t("read_error", error=str(e)),
                        timestamp=time.time()
                    ))
                if self._stop_event.wait(0.05):
                    break

        # 退出前冲刷残余缓冲
        if buffer:
            self._flush_partial(buffer)
            buffer.clear()

    def _split_lines(self, buffer: bytearray):
        """从 buffer 头部不断切出完整行，返回 (lines, remaining_buffer)。

        lines: 每个元素为该行字节内容（不含换行符）；遇到空行则为 b''。
        优先匹配 \\r\\n，其次独立的 \\n 或 \\r，全部使用 C 级 bytes.find 实现。
        """
        lines = []
        while True:
            crlf = buffer.find(b'\r\n')
            lf = buffer.find(b'\n')
            cr = buffer.find(b'\r')

            candidates = []
            if crlf >= 0:
                candidates.append((crlf, 2))
            # 独立的 \n（非 \r\n 的后半段）
            if lf >= 0 and not (crlf >= 0 and lf == crlf + 1):
                candidates.append((lf, 1))
            # 独立的 \r（非 \r\n 的前半段）
            if cr >= 0 and not (crlf >= 0 and cr == crlf):
                candidates.append((cr, 1))

            if not candidates:
                break

            idx, newline_len = min(candidates)
            line_bytes = bytes(buffer[:idx])
            del buffer[:idx + newline_len]
            lines.append(line_bytes)
        return lines

    def _drain_lines(self, buffer: bytearray):
        """把 buffer 中已有的完整行解码并 notify"""
        for line_bytes in self._split_lines(buffer):
            try:
                text = line_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = line_bytes.hex()
            self._notify(SerialMessage(
                source=MessageSource.DEVICE,
                content=text + "\r\n",
                timestamp=time.time(),
                raw_bytes=line_bytes
            ))

    def _flush_partial(self, buffer: bytearray):
        """超时冲刷未结束的不完整行"""
        if not buffer:
            return
        try:
            text = buffer.decode("utf-8")
        except UnicodeDecodeError:
            text = buffer.hex()
        self._notify(SerialMessage(
            source=MessageSource.DEVICE,
            content=text,
            timestamp=time.time(),
            raw_bytes=bytes(buffer)
        ))

    def _notify(self, message: SerialMessage):
        """保存历史并通知所有回调（线程安全）"""
        with self._callbacks_lock:
            self._history.append(message)
            callbacks = list(self._callbacks)
        for cb in callbacks:
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
        self._callbacks_lock = threading.Lock()

    def list_ports(self) -> List[Dict[str, str]]:
        return _list_serial_ports()

    def get_open_ports(self) -> List[str]:
        """获取当前已打开的串口列表（仅端口名，供 MCP / REST 使用）"""
        with self._lock:
            return [p for p, sm in self._ports.items() if sm.is_open()]

    def get_open_ports_detail(self) -> List[Dict]:
        """获取已打开串口的详细信息（含波特率，供 Web UI 同步标签用）"""
        with self._lock:
            result = []
            for p, sm in self._ports.items():
                result.append({"port": p, "baudrate": sm.baudrate})
            return result

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
            sm.baudrate = baudrate  # 记录波特率供 detail 查询
            # 包装回调，带上 port 信息
            def make_callback(port_name: str):
                def callback(msg: SerialMessage):
                    with self._callbacks_lock:
                        cbs = list(self._callbacks)
                    for cb in cbs:
                        try:
                            cb(port_name, msg)
                        except Exception:
                            pass
                return callback
            sm.register_callback(make_callback(port))

            ok = sm.open(port, baudrate)
            if ok:
                self._ports[port] = sm
            else:
                # 打开失败则记录的 baudrate 无意义
                sm.baudrate = None
            return ok

    def close(self, port: str) -> bool:
        """关闭指定串口"""
        with self._lock:
            if port not in self._ports:
                return False
            sm = self._ports.pop(port)
        # 在 self._lock 之外执行实际关闭（close 内部会 join 读线程，避免长时间持锁）
        return sm.close()

    def write(self, port: str, data: str, source: MessageSource = MessageSource.USER,
              encoding: str = "utf-8", newline: str = "\r\n") -> bool:
        """向指定串口发送数据"""
        with self._lock:
            if port not in self._ports:
                return False
            sm = self._ports[port]
        return sm.write(data, source, encoding, newline)

    def write_raw(self, port: str, data: bytes, source: MessageSource = MessageSource.USER) -> bool:
        """向指定串口发送原始字节"""
        with self._lock:
            if port not in self._ports:
                return False
            sm = self._ports[port]
        return sm.write_raw(data, source)

    def get_history(self, port: str, limit: int = 1000) -> List[SerialMessage]:
        """获取指定串口的历史记录"""
        with self._lock:
            if port not in self._ports:
                return []
            sm = self._ports[port]
        return sm.get_history(limit)

    def register_callback(self, callback: Callable[[str, SerialMessage], None]):
        """注册数据接收回调，参数: (port, message)"""
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[str, SerialMessage], None]):
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)


serial_manager = SerialPortManager()
