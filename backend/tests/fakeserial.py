"""模拟 pyserial.Serial 的最小实现，用于在不连接真实硬件的情况下测试读线程与并发。

复现 SerialManager 依赖的接口：is_open / in_waiting / read(n) / write / flush / close / port。
"""
import threading


class FakeSerial:
    def __init__(self, port=None, baudrate=115200, bytesize=8, parity="N",
                 stopbits=1, timeout=0.1, **kwargs):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.write_timeout = kwargs.get("write_timeout")
        self.xonxoff = kwargs.get("xonxoff", False)
        self.rtscts = kwargs.get("rtscts", False)
        self.dsrdtr = kwargs.get("dsrdtr", False)
        self.dtr = None
        self.rts = None
        self.is_open = True
        self._rx = bytearray()
        self._written = bytearray()
        self._lock = threading.Lock()

    # ---- 测试辅助 ----
    def feed(self, data: bytes):
        """向"设备 -> 主机"方向注入数据（模拟设备发送）。"""
        with self._lock:
            self._rx.extend(data)

    @property
    def written(self) -> bytes:
        with self._lock:
            return bytes(self._written)

    # ---- pyserial 兼容接口 ----
    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._rx)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            chunk = bytes(self._rx[:size])
            del self._rx[:size]
            return chunk

    def write(self, data) -> int:
        with self._lock:
            self._written.extend(data)
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.is_open = False
