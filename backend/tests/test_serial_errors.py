"""串口打开失败分类的测试。

这些分类直接决定用户看到的处置建议，因此必须覆盖真实 pyserial 抛出的
异常形态（含中英文消息与 errno）。
"""

import errno
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serial_errors  # noqa: E402


# --- 异常分类 ---

def test_permission_error_is_treated_as_busy():
    """Windows 上被占用报的是 PermissionError(13)。"""
    assert serial_errors.classify_exception(PermissionError(13, "拒绝访问")) == "busy"


def test_file_not_found_means_device_missing():
    assert serial_errors.classify_exception(
        FileNotFoundError(2, "系统找不到指定的文件")
    ) == "not_found"


def test_enoent_errno_is_not_found():
    exc = OSError(errno.ENOENT, "no such file")
    assert serial_errors.classify_exception(exc) == "not_found"


def test_eacces_errno_is_busy():
    exc = OSError(errno.EACCES, "access denied")
    assert serial_errors.classify_exception(exc) == "busy"


def test_serial_exception_wrapping_chinese_enoent_is_not_found():
    """pyserial 把 ENOENT 包成 SerialException，消息内嵌中文底层文本。"""
    exc = Exception(
        "could not open port 'COM3': FileNotFoundError(2, '系统找不到指定的文件。', None, 2)"
    )
    assert serial_errors.classify_exception(exc) == "not_found"


def test_serial_exception_with_english_no_such_file_is_not_found():
    exc = Exception("could not open port '/dev/ttyUSB9': [Errno 2] No such file or directory")
    assert serial_errors.classify_exception(exc) == "not_found"


def test_explicit_busy_message_is_busy():
    exc = Exception("could not open port 'COM4': Access is denied.")
    assert serial_errors.classify_exception(exc) == "busy"


def test_unsupported_parameters():
    exc = Exception("Unsupported baudrate: 12345678")
    assert serial_errors.classify_exception(exc) == "unsupported"


def test_unknown_exception_falls_back():
    assert serial_errors.classify_exception(Exception("weird failure")) == "unknown"


# --- 结合枚举结果的修正 ---

def test_absent_device_reported_as_busy_is_reclassified_not_found():
    """幻影端口（不在枚举里）报 PermissionError 时，结论应是"不存在"。"""
    failure = serial_errors.build_failure(
        "COM3",
        PermissionError(13, "拒绝访问"),
        present_in_enumeration=False,
        available_ports=["COM1", "COM4"],
    )
    assert failure.kind == "not_found"
    assert "不存在" in failure.hint


def test_present_device_reported_as_not_found_is_reclassified_busy():
    """枚举里有但打不开，说明被占用而非不存在。"""
    failure = serial_errors.build_failure(
        "COM4",
        FileNotFoundError(2, "not found"),
        present_in_enumeration=True,
        available_ports=["COM4"],
    )
    assert failure.kind == "busy"


def test_unknown_enumeration_keeps_original_classification():
    failure = serial_errors.build_failure(
        "COM3",
        FileNotFoundError(2, "not found"),
        present_in_enumeration=None,
    )
    assert failure.kind == "not_found"


# --- 展示形态 ---

def test_message_includes_underlying_error_and_available_ports():
    """原始实现只输出"打开串口失败: COM3"，丢失了全部可用信息。"""
    failure = serial_errors.build_failure(
        "COM3",
        FileNotFoundError(2, "系统找不到指定的文件"),
        present_in_enumeration=False,
        available_ports=["COM1", "COM4"],
    )

    message = failure.to_message()

    assert "COM3" in message
    assert "FileNotFoundError" in message
    assert "系统找不到指定的文件" in message
    assert "COM1, COM4" in message
    assert failure.hint in message


def test_message_handles_empty_port_list():
    failure = serial_errors.build_failure("COM9", None)
    assert "当前没有可用串口" in failure.to_message()


def test_to_dict_is_json_friendly():
    failure = serial_errors.build_failure(
        "COM3",
        FileNotFoundError(2, "missing"),
        present_in_enumeration=False,
        available_ports=["COM1"],
    )

    payload = failure.to_dict()

    assert payload["port"] == "COM3"
    assert payload["kind"] == "not_found"
    assert payload["exception"] == "FileNotFoundError"
    assert payload["available_ports"] == ["COM1"]
    assert payload["present_in_enumeration"] is False


def test_available_ports_list_is_copied():
    """避免调用方后续修改源列表污染诊断信息。"""
    source = ["COM1"]
    failure = serial_errors.build_failure("COM2", None, available_ports=source)
    source.append("COM9")

    assert failure.to_dict()["available_ports"] == ["COM1"]
