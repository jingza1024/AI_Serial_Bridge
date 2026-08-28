"""串口并发与生命周期测试。

核心目标：验证重写后的并发模型
- open -> 注入数据 -> 回调触发 -> close 干净退出（不超时/不死锁）
- 重开同一串口不会产生孤儿读线程
- 多串口管理器回调正确分发
- write / write_raw 真实写入
"""
import time

import pytest

import serial_manager as sm_mod
from serial_manager import SerialManager, SerialPortManager, MessageSource
from fakeserial import FakeSerial


@pytest.fixture(autouse=True)
def _patch_serial(monkeypatch):
    """把 pyserial.Serial 替换为 FakeSerial。"""
    monkeypatch.setattr(sm_mod.serial, "Serial", FakeSerial)


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_open_and_receive_device_data():
    mgr = SerialManager()
    received = []
    mgr.register_callback(lambda m: received.append(m))
    assert mgr.open("COM_TEST", 115200) is True
    assert mgr.is_open() is True

    fake = mgr._serial
    fake.feed(b"hello\r\nworld\r\n")

    assert _wait_until(lambda: any(
        m.source == MessageSource.DEVICE and "hello" in m.content for m in received
    ))
    assert any(m.source == MessageSource.DEVICE and "world" in m.content for m in received)

    assert mgr.close() is True
    assert mgr.is_open() is False


def test_partial_device_output_flushes_before_key_repeat_interval():
    mgr = SerialManager()
    received = []
    mgr.register_callback(received.append)
    assert mgr.open("COM_KEY_REPEAT") is True

    mgr._serial.feed(b"b")

    assert _wait_until(
        lambda: any(
            m.source == MessageSource.DEVICE and m.content == "b"
            for m in received
        ),
        timeout=0.04,
        interval=0.005,
    )
    mgr.close()


def test_close_returns_promptly_no_deadlock():
    mgr = SerialManager()
    mgr.open("COM_TO")
    fake = mgr._serial
    # 持续灌数据，模拟读线程忙碌
    fake.feed(b"x" * 10000 + b"\r\n")
    start = time.time()
    ok = mgr.close()
    elapsed = time.time() - start
    assert ok is True
    assert elapsed < 3.0, f"close 耗时 {elapsed:.2f}s，疑似死锁"


def test_reopen_stops_old_thread_no_orphan():
    mgr = SerialManager()
    mgr.open("COM_REOPEN")
    first_thread = mgr._read_thread
    assert first_thread is not None and first_thread.is_alive()

    start = time.time()
    assert mgr.open("COM_REOPEN") is True  # 重开：先关旧的
    elapsed = time.time() - start
    assert elapsed < 5.0

    # 旧读线程应已退出（无孤儿）
    assert _wait_until(lambda: not first_thread.is_alive(), timeout=2.0)
    # 新读线程在运行
    assert mgr._read_thread is not None and mgr._read_thread.is_alive()
    assert mgr._read_thread is not first_thread

    mgr.close()
    # close 后 _read_thread 会被置 None（无残留线程）
    assert _wait_until(lambda: mgr._read_thread is None or not mgr._read_thread.is_alive())


def test_write_actually_writes_bytes():
    mgr = SerialManager()
    mgr.open("COM_WR")
    assert mgr.write("ABC", newline="") is True
    assert mgr._serial.written == b"ABC"
    # 默认追加 \r\n
    assert mgr.write("D") is True
    assert mgr._serial.written == b"ABC" + b"D\r\n"
    mgr.close()


def test_write_raw_bytes():
    mgr = SerialManager()
    mgr.open("COM_RAW")
    assert mgr.write_raw(b"\x01\x02\x03") is True
    assert mgr._serial.written == b"\x01\x02\x03"
    mgr.close()


def test_raw_receive_callback_preserves_exact_stream_bytes():
    mgr = SerialManager()
    chunks = []
    mgr.register_raw_callback(lambda chunk: chunks.append(chunk.data))
    mgr.open("COM_RAW_RX")
    payload = b"a\r\nb\x00\xff\n"
    mgr._serial.feed(payload)

    assert _wait_until(lambda: b"".join(chunks) == payload)
    mgr.close()


def test_advanced_serial_settings_are_applied():
    mgr = SerialManager()
    assert mgr.open(
        "COM_CFG",
        baudrate=57600,
        bytesize=7,
        parity="E",
        stopbits=2,
        xonxoff=True,
        rtscts=True,
        dsrdtr=True,
        dtr=False,
        rts=True,
    )
    fake = mgr._serial
    assert (fake.baudrate, fake.bytesize, fake.parity, fake.stopbits) == (57600, 7, "E", 2)
    assert (fake.xonxoff, fake.rtscts, fake.dsrdtr) == (True, True, True)
    assert (fake.dtr, fake.rts) == (False, True)
    mgr.close()


def test_write_when_closed_fails():
    mgr = SerialManager()
    assert mgr.write("X") is False


def test_multiport_manager_dispatch():
    pm = SerialPortManager()
    seen = []
    pm.register_callback(lambda port, msg: seen.append((port, msg.source)))
    try:
        assert pm.open("COM_A") is True
        assert pm.open("COM_B") is True
        assert set(pm.get_open_ports()) == {"COM_A", "COM_B"}

        detail = {d["port"]: d["baudrate"] for d in pm.get_open_ports_detail()}
        assert set(detail) == {"COM_A", "COM_B"}

        pm._ports["COM_A"]._serial.feed(b"hi\r\n")
        assert _wait_until(lambda: any(p == "COM_A" and s == MessageSource.DEVICE for p, s in seen))

        assert pm.close("COM_A") is True
        assert "COM_A" not in pm.get_open_ports()
        assert "COM_B" in pm.get_open_ports()
    finally:
        pm.close("COM_A")
        pm.close("COM_B")
        pm.unregister_callback(seen.append)  # best-effort


def test_reopen_via_port_manager():
    pm = SerialPortManager()
    assert pm.open("COM_R") is True
    # 再次 open 同一端口应直接返回成功（幂等）
    assert pm.open("COM_R") is True
    assert pm.get_open_ports() == ["COM_R"]
    pm.close("COM_R")


def test_read_failure_marks_port_closed_and_reports_once(monkeypatch):
    class FailingSerial(FakeSerial):
        @property
        def in_waiting(self):
            raise sm_mod.serial.SerialException("device disconnected")

    monkeypatch.setattr(sm_mod.serial, "Serial", FailingSerial)
    mgr = SerialManager()
    received = []
    mgr.register_callback(received.append)

    assert mgr.open("COM_FAIL") is True
    assert _wait_until(lambda: not mgr.is_open())
    time.sleep(0.15)

    failures = [
        message for message in received
        if message.event_code == "serial.read_error"
        and "device disconnected" in message.event_params.get("error", "")
    ]
    assert len(failures) == 1
    mgr.close()
