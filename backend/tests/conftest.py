"""Pytest 配置：将 backend 目录加入 sys.path，使测试可直接 import 顶层模块。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pytest


@pytest.fixture(autouse=True)
def _cleanup_open_ports():
    """每个测试结束后关闭遗留的串口，避免全局单例状态泄漏。"""
    yield
    from serial_manager import serial_manager
    from leases import port_leases
    for p in list(serial_manager.get_open_ports()):
        try:
            serial_manager.close(p)
        except Exception:
            pass
    port_leases.clear_all()
