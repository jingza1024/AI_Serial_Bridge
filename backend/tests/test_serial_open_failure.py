"""SerialManager 打开失败时的错误记录测试。

回归点：``open()`` 曾在失败路径调用未定义的 ``list_ports()``，
导致 ``NameError`` 被上层包装成 HTTP 500，而不是返回结构化的失败原因。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serial_manager as sm_module  # noqa: E402


@pytest.fixture
def manager(monkeypatch):
    """构造一个不受真实硬件影响的 SerialManager。"""
    instance = sm_module.SerialManager()

    def fake_list_ports(self):
        return [
            {"device": "COM1", "description": "fake", "hwid": ""},
            {"device": "COM4", "description": "fake", "hwid": ""},
        ]

    monkeypatch.setattr(sm_module.SerialManager, "list_ports", fake_list_ports, raising=False)

    def failing_serial(**kwargs):
        raise FileNotFoundError(2, "系统找不到指定的文件")

    monkeypatch.setattr(sm_module.serial, "Serial", failing_serial)
    return instance


def test_open_failure_records_structured_error(manager):
    ok = manager.open("COM3", 115200)

    assert ok is False
    failure = manager.last_error
    assert failure is not None
    assert failure.port == "COM3"
    # COM3 不在枚举里 -> 应判定为设备不存在，而不是被占用
    assert failure.kind == "not_found"


def test_open_failure_lists_available_ports(manager):
    manager.open("COM3", 115200)

    failure = manager.last_error
    assert failure is not None
    message = failure.to_message()
    assert "COM1" in message and "COM4" in message


def test_open_failure_does_not_raise(manager):
    """失败必须返回 False 并留下诊断，绝不能把 NameError 抛给调用方。"""
    assert manager.open("COM9", 115200) is False


def test_successful_open_clears_previous_error(manager, monkeypatch):
    manager.open("COM3", 115200)
    assert manager.last_error is not None

    class FakeSerial:
        is_open = True
        port = "COM4"

        def __init__(self, **kwargs):
            self.port = kwargs.get("port", "COM4")

        def read(self, size=1):
            return b""

        def close(self):
            self.is_open = False

    monkeypatch.setattr(sm_module.serial, "Serial", lambda **kwargs: FakeSerial(**kwargs))
    monkeypatch.setattr(
        sm_module.SerialManager, "_read_loop", lambda self: None, raising=False
    )

    assert manager.open("COM4", 115200) is True
    assert manager.last_error is None
