"""端口与监听地址的单一配置来源。

原先 ``manager.py`` 写死 8000/5173，``vite.config.ts`` 写死代理目标，
``desktop.py`` 又会动态换端口，三者各说各话。这里集中收敛：

  - 后端监听端口：``AI_SERIAL_PORT``（默认 8000）
  - 后端监听地址：``AI_SERIAL_HOST``（默认 127.0.0.1）
  - 前端开发端口：``AI_SERIAL_FRONTEND_PORT``（默认 5173）

桌面模式出于安全考虑始终绑定回环地址；此处只负责解析与校验，
不改变"远程部署需显式配置"的既有约定。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_API_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
DEFAULT_HOST = "127.0.0.1"

# 允许的最大端口号
_MAX_PORT = 65535


class PortConfigError(ValueError):
    """端口配置非法。"""


def _parse_port(raw: str, *, name: str, default: int) -> int:
    text = (raw or "").strip()
    if not text:
        return default
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise PortConfigError(f"{name} 必须是整数，收到 {raw!r}") from exc
    if not (0 <= value <= _MAX_PORT):
        raise PortConfigError(f"{name} 必须在 0-{_MAX_PORT} 之间，收到 {value}")
    return value


def api_port(env: dict[str, str] | None = None) -> int:
    """后端监听端口；``0`` 表示由操作系统分配。"""
    values = os.environ if env is None else env
    return _parse_port(
        values.get("AI_SERIAL_PORT", ""),
        name="AI_SERIAL_PORT",
        default=DEFAULT_API_PORT,
    )


def api_host(env: dict[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    host = (values.get("AI_SERIAL_HOST", "") or "").strip()
    return host or DEFAULT_HOST


def frontend_port(env: dict[str, str] | None = None) -> int:
    values = os.environ if env is None else env
    return _parse_port(
        values.get("AI_SERIAL_FRONTEND_PORT", ""),
        name="AI_SERIAL_FRONTEND_PORT",
        default=DEFAULT_FRONTEND_PORT,
    )


def api_base_url(env: dict[str, str] | None = None) -> str:
    """回环 API 的基地址，供 Vite 代理与文档使用。"""
    return f"http://{api_host(env)}:{api_port(env)}"


def repo_root() -> Path:
    """仓库根目录（本文件位于 <root>/backend/）。"""
    return Path(__file__).resolve().parent.parent
