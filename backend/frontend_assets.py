"""前端构建产物的定位逻辑。

单独成模块的原因：桌面打包（PyInstaller）与源码运行的资源根目录不同，
这是最容易出错、也最难在开发机上复现的路径计算。抽成纯函数后可以直接
对三种布局做单元测试，而不必真的执行一次打包。
"""

from __future__ import annotations

import os
from pathlib import Path

# 前端构建产物的相对位置（相对于各自布局的资源根）
_DIST_RELATIVE = Path("frontend") / "dist"

# 判断"这是一个可用的前端产物目录"的标记文件
_ENTRY_FILE = "index.html"


def _is_dist_dir(candidate: Path) -> bool:
    """目录内存在入口页时才视为有效产物。"""
    try:
        return (candidate / _ENTRY_FILE).is_file()
    except OSError:
        return False


def candidate_dist_dirs(
    *,
    meipass: str | os.PathLike[str] | None = None,
    module_file: str | os.PathLike[str] | None = None,
    executable: str | os.PathLike[str] | None = None,
    frozen: bool = False,
) -> list[Path]:
    """按优先级返回所有候选的前端产物目录。

    参数全部显式传入（而非直接读 sys），使该函数可以被测试替换。

    布局：
      1. PyInstaller 解包目录：``sys._MEIPASS/frontend/dist``
         onedir 模式下即 ``<exe_dir>/_internal/frontend/dist``。
      2. 源码模式：``main.py`` 位于 ``<root>/backend/``，
         因此根目录是上一级。
      3. onedir 兜底：可执行文件同级的 ``_internal`` 或直接同级。
    """
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            normalized = path.resolve()
        except OSError:
            normalized = path
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    if meipass:
        add(Path(meipass) / _DIST_RELATIVE)

    if module_file:
        try:
            add(Path(module_file).resolve().parent.parent / _DIST_RELATIVE)
        except OSError:
            pass

    if frozen and executable:
        try:
            exe_dir = Path(executable).resolve().parent
        except OSError:
            exe_dir = Path(executable).parent
        add(exe_dir / "_internal" / _DIST_RELATIVE)
        add(exe_dir / _DIST_RELATIVE)

    return candidates


def resolve_dist_dir(
    *,
    meipass: str | os.PathLike[str] | None = None,
    module_file: str | os.PathLike[str] | None = None,
    executable: str | os.PathLike[str] | None = None,
    frozen: bool = False,
) -> Path | None:
    """返回第一个包含 ``index.html`` 的候选目录；都不存在时返回 ``None``。"""
    for candidate in candidate_dist_dirs(
        meipass=meipass,
        module_file=module_file,
        executable=executable,
        frozen=frozen,
    ):
        if _is_dist_dir(candidate):
            return candidate
    return None


def resolve_dist_dir_from_runtime() -> Path | None:
    """基于当前解释器状态解析前端产物目录。

    仅在导入期调用一次；测试应使用 :func:`resolve_dist_dir` 并显式传参。
    """
    import sys

    return resolve_dist_dir(
        meipass=getattr(sys, "_MEIPASS", None),
        module_file=globals().get("__file__"),
        executable=getattr(sys, "executable", None),
        frozen=bool(getattr(sys, "frozen", False)),
    )


def describe_missing_dist() -> str:
    """资源缺失时给出可操作的诊断文本。"""
    import sys

    checked = candidate_dist_dirs(
        meipass=getattr(sys, "_MEIPASS", None),
        module_file=globals().get("__file__"),
        executable=getattr(sys, "executable", None),
        frozen=bool(getattr(sys, "frozen", False)),
    )
    lines = [
        "桌面模式未找到前端构建产物 frontend/dist（缺少 index.html）。",
        "已检查以下位置：",
    ]
    for candidate in checked:
        lines.append(f"  - {candidate}")
    if not checked:
        lines.append("  （未能推导出任何候选路径）")
    lines.extend([
        "源码运行请先执行：cd frontend && npm run build",
        "打包运行时请确认执行过完整构建（前端 dist 会被打进 _internal/frontend/dist）。",
    ])
    return "\n".join(lines)
