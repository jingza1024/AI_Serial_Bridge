"""串口打开失败的分类与诊断文本。

背景：``serial.Serial(...)`` 抛出的异常种类能区分出三种截然不同的原因，
但原始实现只把异常吞成 ``return False``，调用方只能看到"打开串口失败"，
无法判断是设备没插、被别的程序占用，还是参数不支持。三者对应的处置
方式完全不同，因此这里统一做分类，并给出可操作的建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import errno
from typing import Literal

# 失败类别
#   not_found      设备不存在（未插/驱动未装/端口号写错）
#   busy           设备存在但被占用（其他终端程序持有句柄）
#   permission     权限不足
#   unsupported    参数组合或平台不支持
#   unknown        其它
ErrorKind = Literal["not_found", "busy", "permission", "unsupported", "unknown"]

_HINTS: dict[str, str] = {
    "not_found": "设备不存在或未被系统枚举；请确认已插好、驱动已安装，并检查端口名是否正确。",
    "busy": "设备可能已被其他程序占用（终端工具、上一次会话未释放，或另一个 MCP 客户端）。",
    "permission": "当前用户无权打开该设备；Linux 上通常需要将用户加入 dialout/uucp 组。",
    "unsupported": "该串口参数组合不被设备或驱动支持。",
    "unknown": "请检查设备连接与串口参数。",
}


@dataclass(frozen=True)
class OpenFailure:
    """一次串口打开失败的完整诊断信息。"""

    port: str
    kind: ErrorKind
    # 底层异常的类名与消息（保留原始信息，便于排障）
    exception: str = ""
    detail: str = ""
    # 设备是否出现在系统枚举中——区分"不存在"与"被占用"的关键
    present_in_enumeration: bool | None = None
    available_ports: list[str] = field(default_factory=list)

    @property
    def hint(self) -> str:
        return _HINTS.get(self.kind, _HINTS["unknown"])

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "kind": self.kind,
            "exception": self.exception,
            "detail": self.detail,
            "present_in_enumeration": self.present_in_enumeration,
            "available_ports": list(self.available_ports),
        }

    def to_message(self) -> str:
        """面向用户/模型的一行摘要。"""
        parts = [f"打开串口失败: {self.port}"]
        if self.exception:
            parts.append(f"[{self.exception}]")
        if self.detail:
            parts.append(self.detail)
        parts.append(self.hint)
        if self.available_ports:
            parts.append("可用串口: " + ", ".join(self.available_ports))
        else:
            parts.append("当前没有可用串口")
        return " ".join(parts)


def classify_exception(exc: BaseException) -> ErrorKind:
    """把 pyserial 抛出的异常归类。

    依据：
      - ``FileNotFoundError`` / ``SerialException("could not open port")`` 且底层为
        ENOENT -> 设备不存在。
      - ``PermissionError``（Windows 上被占用会报 EPERM/EACCES）-> 需要结合枚举判断，
        因此这里返回 busy，由调用方结合 present_in_enumeration 修正。
      - ``serial.SerialException`` 中的 "busy" / "exclusive access" -> busy。
    """
    # PermissionError 在 Windows 上既可能是占用也可能是权限
    if isinstance(exc, PermissionError):
        return "busy"
    if isinstance(exc, FileNotFoundError):
        return "not_found"

    err = getattr(exc, "errno", None)
    if err == errno.ENOENT:
        return "not_found"
    if err in (errno.EACCES, errno.EPERM):
        return "busy"

    text = str(exc).lower()
    if "could not open port" in text or "filenotfound" in text:
        # pyserial 把 ENOENT 包成 SerialException，消息里带底层文本
        if "permission" in text or "access is denied" in text or "拒绝访问" in text:
            return "busy"
        if "系统找不到指定的文件" in text or "no such file" in text:
            return "not_found"
        return "not_found"
    if "busy" in text or "exclusive access" in text or "被占用" in text:
        return "busy"
    if "permission" in text or "access is denied" in text or "拒绝访问" in text:
        return "permission"
    if "not supported" in text or "unsupported" in text or "不支持" in text:
        return "unsupported"
    return "unknown"


def build_failure(
    port: str,
    exc: BaseException | None,
    *,
    present_in_enumeration: bool | None = None,
    available_ports: list[str] | None = None,
) -> OpenFailure:
    """构造诊断对象，并在"设备确实存在"时把 busy 修正为 permission。"""
    kind: ErrorKind = classify_exception(exc) if exc is not None else "unknown"

    # 设备不在枚举里却报 PermissionError，通常意味着端口名被别的设备残留占用，
    # 或驱动枚举异常；此时"设备不存在"是更准确的结论。
    if kind == "busy" and present_in_enumeration is False:
        kind = "not_found"
    # 设备在枚举里但报 ENOENT，说明枚举与打开所使用的名字不一致
    elif kind == "not_found" and present_in_enumeration is True:
        kind = "busy"

    return OpenFailure(
        port=port,
        kind=kind,
        exception=type(exc).__name__ if exc is not None else "",
        detail=str(exc) if exc is not None else "",
        present_in_enumeration=present_in_enumeration,
        available_ports=list(available_ports or []),
    )
