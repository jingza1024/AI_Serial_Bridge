"""前端构建产物的新鲜度判定。

原先只比较 ``index.html`` 与源文件的 mtime。这在以下场景会失效：
git checkout 重置时间戳、跨机器/网盘同步、CI 缓存恢复、时钟不同步。
本模块改用内容指纹：构建时写入 ``.build-manifest.json``，运行时比对
源文件哈希，从而不依赖时间戳。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_NAME = ".build-manifest.json"

# 参与指纹计算的源文件/配置
_TRACKED_FILES = (
    "index.html",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.ts",
)

# 参与指纹计算的源目录
_TRACKED_DIRS = ("src",)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def source_fingerprint(frontend_dir: Path) -> str:
    """计算前端源码的稳定指纹（与 mtime 无关）。

    文件按相对路径排序，保证不同文件系统枚举顺序下结果一致。
    """
    entries: list[tuple[str, str]] = []

    for name in _TRACKED_FILES:
        path = frontend_dir / name
        if path.is_file():
            entries.append((name, _hash_file(path)))

    for dirname in _TRACKED_DIRS:
        root = frontend_dir / dirname
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            entries.append((path.relative_to(frontend_dir).as_posix(), _hash_file(path)))

    entries.sort(key=lambda item: item[0])

    digest = hashlib.sha256()
    for name, file_hash in entries:
        digest.update(f"{name}\0{file_hash}\n".encode("utf-8"))
    return digest.hexdigest()


def manifest_path(dist_dir: Path) -> Path:
    return dist_dir / MANIFEST_NAME


def read_manifest(dist_dir: Path) -> dict | None:
    path = manifest_path(dist_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_manifest(dist_dir: Path, fingerprint: str) -> Path:
    """构建完成后写入指纹；供打包脚本调用。"""
    path = manifest_path(dist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": 1, "fingerprint": fingerprint}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def bundle_is_stale(frontend_dir: Path) -> bool:
    """判断前端产物是否落后于源码。

    判定顺序：
      1. 产物不存在 -> 不算"陈旧"（由调用方按缺失处理）。
      2. 存在指纹清单 -> 比对指纹，不一致即陈旧。
      3. 无指纹清单（旧产物）-> 回退到 mtime 比较，保持向后兼容。
    """
    dist_dir = frontend_dir / "dist"
    index = dist_dir / "index.html"
    if not index.is_file():
        return False

    manifest = read_manifest(dist_dir)
    if manifest is not None:
        recorded = manifest.get("fingerprint")
        if isinstance(recorded, str) and recorded:
            return recorded != source_fingerprint(frontend_dir)
        # 清单损坏：视为陈旧，提示重新构建
        return True

    return _mtime_is_stale(frontend_dir, index)


def _mtime_is_stale(frontend_dir: Path, index: Path) -> bool:
    inputs = [path for path in (frontend_dir / "src").rglob("*") if path.is_file()]
    inputs.extend(
        path for path in (frontend_dir / name for name in _TRACKED_FILES) if path.is_file()
    )
    if not inputs:
        return False
    try:
        newest = max(path.stat().st_mtime for path in inputs)
        return newest > index.stat().st_mtime
    except OSError:
        return False
