"""desktop_logging 的落盘行为测试。

打包桌面程序以 console=False 运行，日志文件是唯一的排障入口，
因此这里验证：路径可覆盖、日志可写、未捕获异常会落盘。
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import desktop_logging  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """每个测试使用独立状态目录，并重置 logger 的配置标记。"""
    monkeypatch.setenv("AI_SERIAL_STATE_DIR", str(tmp_path))
    logger = logging.getLogger(desktop_logging.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    if hasattr(logger, "_asb_configured"):
        delattr(logger, "_asb_configured")
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    if hasattr(logger, "_asb_configured"):
        delattr(logger, "_asb_configured")


def test_state_dir_honours_override(tmp_path):
    assert desktop_logging.state_dir() == tmp_path


def test_log_and_crash_paths_live_under_logs(tmp_path):
    assert desktop_logging.log_path() == tmp_path / "logs" / "desktop.log"
    assert desktop_logging.crash_path() == tmp_path / "logs" / "crash.log"


def test_configure_logging_creates_file_on_first_write():
    logger = desktop_logging.configure_logging()
    logger.info("hello from test")

    for handler in logger.handlers:
        handler.flush()

    assert desktop_logging.log_path().is_file()
    assert "hello from test" in desktop_logging.log_path().read_text(encoding="utf-8")


def test_configure_logging_is_idempotent():
    first = desktop_logging.configure_logging()
    count = len(first.handlers)
    second = desktop_logging.configure_logging()

    assert first is second
    assert len(second.handlers) == count


def test_uncaught_exception_hook_writes_crash_log(monkeypatch):
    desktop_logging.install_exception_hooks()

    try:
        raise ValueError("boom for crash log")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_value, exc_tb)

    content = desktop_logging.crash_path().read_text(encoding="utf-8")
    assert "ValueError" in content
    assert "boom for crash log" in content


def test_keyboard_interrupt_is_not_treated_as_crash(monkeypatch):
    desktop_logging.install_exception_hooks()
    called = {}

    def fake_hook(exc_type, exc_value, exc_tb):
        called["value"] = exc_type

    monkeypatch.setattr(sys, "__excepthook__", fake_hook)

    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_type, exc_value, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_value, exc_tb)

    assert called.get("value") is KeyboardInterrupt
    # 用户主动中断不应污染 crash.log
    assert not desktop_logging.crash_path().exists()


def test_log_path_display_is_absolute_string():
    display = desktop_logging.log_path_for_display()

    assert isinstance(display, str)
    assert display.endswith("desktop.log")


def test_installing_hooks_does_not_create_crash_log():
    """crash.log 的存在被冒烟测试当作崩溃信号，正常启动不得留下空文件。"""
    desktop_logging.install_exception_hooks()
    desktop_logging.configure_logging().info("normal operation")

    assert not desktop_logging.crash_path().exists()


def test_faulthandler_does_not_write_to_crash_log():
    """faulthandler 走独立的 fault.log，避免与 Python 层崩溃判定混淆。"""
    desktop_logging.install_exception_hooks()

    assert not desktop_logging.crash_path().exists()
