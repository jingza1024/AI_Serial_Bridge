"""桌面程序的崩溃与运行日志落盘。

打包后的桌面程序以 ``console=False`` 运行，``pythonw`` 更是完全没有控制台：
``print`` 与未捕获异常的 traceback 全部丢失，用户只能看到"窗口一闪而过"。
本模块把这类信息写进用户状态目录，使白屏/闪退类问题可以事后排查。
"""

from __future__ import annotations

import faulthandler
from logging.handlers import RotatingFileHandler
import logging
import os
from pathlib import Path
import sys
import traceback

LOGGER_NAME = "ai_serial_bridge.desktop"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 3


def state_dir() -> Path:
    """与 MCP/桌面共享的状态目录，可用 AI_SERIAL_STATE_DIR 覆盖。"""
    override = os.environ.get("AI_SERIAL_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ai-serial-bridge"


def log_path() -> Path:
    return state_dir() / "logs" / "desktop.log"


def crash_path() -> Path:
    return state_dir() / "logs" / "crash.log"


def _ensure_parent(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """配置轮转文件日志，并让未捕获异常写入 crash.log。

    重复调用是安全的（handler 只安装一次）。
    """
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_asb_configured", False):
        return logger

    logger.setLevel(level)
    logger.propagate = False

    path = log_path()
    if _ensure_parent(path):
        try:
            handler = RotatingFileHandler(
                path,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
            ))
            logger.addHandler(handler)
        except OSError:
            pass

    # 兜底：即使文件不可写，也别让日志调用本身抛异常
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    logger._asb_configured = True  # type: ignore[attr-defined]
    return logger


def log_path_for_display() -> str:
    """给用户看的日志位置（用于错误提示）。"""
    return str(log_path())


def _write_crash(text: str) -> None:
    """追加崩溃信息；仅在实际写入时才创建文件。

    crash.log 的存在本身被冒烟测试当作"发生过崩溃"的信号，
    因此绝不能因为打开句柄就留下空文件。
    """
    path = crash_path()
    if not _ensure_parent(path):
        return
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(text)
            stream.write("\n")
    except OSError:
        pass


def install_exception_hooks() -> None:
    """安装未捕获异常钩子，把 traceback 落盘。

    同时启用 faulthandler，使段错误等硬崩溃也能留下栈信息。
    """
    logger = configure_logging()

    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("未捕获异常:\n%s", text)
        _write_crash(f"=== {logging.Formatter().formatTime(logging.LogRecord('', 0, '', 0, '', (), None))} ===")
        _write_crash(text)

    sys.excepthook = handle_exception

    # 线程内的未捕获异常不会经过 sys.excepthook
    def handle_thread_exception(args):
        if args.exc_type is SystemExit:
            return
        text = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback
        ))
        logger.critical("线程 %s 未捕获异常:\n%s", args.thread.name if args.thread else "?", text)
        _write_crash(f"--- thread {getattr(args.thread, 'name', '?')} ---")
        _write_crash(text)

    threading_hook_available = hasattr(sys, "unraisablehook")
    try:
        import threading
        threading.excepthook = handle_thread_exception
    except Exception:
        logger.debug("无法安装 threading.excepthook", exc_info=True)

    # faulthandler 只写原生栈，用于诊断段错误等硬崩溃。
    # 它需要一个真实文件描述符，因此写到独立的 fault.log；
    # crash.log 保持"仅由 Python 层写入"，两者语义不混用。
    if not faulthandler.is_enabled():
        fault_file = None
        fault_path = state_dir() / "logs" / "fault.log"
        if _ensure_parent(fault_path):
            try:
                fault_file = open(fault_path, "a", encoding="utf-8")
            except OSError:
                fault_file = None
        try:
            faulthandler.enable(file=fault_file, all_threads=True)
        except (OSError, ValueError):
            if fault_file is not None:
                fault_file.close()

    if not threading_hook_available:
        logger.debug("当前解释器不支持 sys.unraisablehook")
