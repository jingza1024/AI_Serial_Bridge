"""port_config 的解析与校验测试。

端口配置原先散落在 manager.py、vite.config.ts 和 desktop.py 三处，
这里验证收敛后的单一来源行为一致且能拒绝非法输入。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import port_config  # noqa: E402


def test_defaults_match_historical_values():
    assert port_config.api_port({}) == 8000
    assert port_config.api_host({}) == "127.0.0.1"
    assert port_config.frontend_port({}) == 5173


def test_api_port_from_env():
    assert port_config.api_port({"AI_SERIAL_PORT": "9001"}) == 9001


def test_port_zero_is_allowed_for_os_assignment():
    """desktop.py 依赖端口 0 让操作系统分配。"""
    assert port_config.api_port({"AI_SERIAL_PORT": "0"}) == 0


def test_blank_env_falls_back_to_default():
    assert port_config.api_port({"AI_SERIAL_PORT": "   "}) == 8000
    assert port_config.api_host({"AI_SERIAL_HOST": "  "}) == "127.0.0.1"


def test_non_numeric_port_is_rejected():
    with pytest.raises(port_config.PortConfigError, match="必须是整数"):
        port_config.api_port({"AI_SERIAL_PORT": "eighty"})


def test_out_of_range_port_is_rejected():
    with pytest.raises(port_config.PortConfigError, match="必须在"):
        port_config.api_port({"AI_SERIAL_PORT": "70000"})
    with pytest.raises(port_config.PortConfigError, match="必须在"):
        port_config.api_port({"AI_SERIAL_PORT": "-1"})


def test_frontend_port_from_env():
    assert port_config.frontend_port({"AI_SERIAL_FRONTEND_PORT": "5199"}) == 5199


def test_api_base_url_combines_host_and_port():
    assert port_config.api_base_url({
        "AI_SERIAL_HOST": "0.0.0.0",
        "AI_SERIAL_PORT": "8123",
    }) == "http://0.0.0.0:8123"
