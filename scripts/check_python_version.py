"""Python 版本兼容性检查。

本项目依赖若干需要预编译 wheel 的包（PyYAML、pydantic-core、cryptography、
pythonnet 等）。上游通常滞后于最新 CPython 版本发布 wheel，一旦解释器过新，
pip 会回退到源码编译并要求本机安装 C/C++ 工具链，失败信息与项目本身无关，
非常容易误判。

因此这里显式声明受支持的版本区间，并在安装/启动前给出可操作的提示。
"""

from __future__ import annotations

import sys

# 支持的区间（含端点）
MIN_VERSION = (3, 10)
MAX_VERSION_EXCLUSIVE = (3, 15)

MIN_TEXT = "3.10"
MAX_TEXT = "3.14"


class UnsupportedPythonError(RuntimeError):
    """当前 Python 版本不在支持区间。"""


def current_version() -> tuple[int, int, int]:
    return (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)


def is_supported(version: tuple[int, ...] | None = None) -> bool:
    major, minor = (version or current_version())[:2]
    return MIN_VERSION <= (major, minor) < MAX_VERSION_EXCLUSIVE


def describe_requirement() -> str:
    return f"Python {MIN_TEXT} - {MAX_TEXT}"


def check_or_raise(version: tuple[int, ...] | None = None) -> None:
    if is_supported(version):
        return
    major, minor, *_ = version or current_version()
    raise UnsupportedPythonError(
        f"当前 Python {major}.{minor} 不在受支持范围（{describe_requirement()}）。\n"
        "较新的 Python 版本可能缺少 PyYAML / pydantic-core / pythonnet 等依赖的\n"
        "预编译 wheel，pip 会尝试源码编译并要求安装 Visual C++ Build Tools。\n"
        "\n"
        "建议改用受支持的版本创建虚拟环境，例如：\n"
        "  py -3.13 -m venv .venv\n"
        "  .venv\\Scripts\\python.exe -m pip install -r backend\\requirements-dev.txt\n"
    )


def main() -> int:
    try:
        check_or_raise()
    except UnsupportedPythonError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] Python {current_version()[0]}.{current_version()[1]} 在支持范围内"
          f"（{describe_requirement()}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
