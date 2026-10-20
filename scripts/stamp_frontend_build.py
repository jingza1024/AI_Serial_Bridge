"""前端构建后写入指纹清单。

用法（在 frontend 构建完成之后执行）：
    python scripts/stamp_frontend_build.py

``desktop.py`` 会比对清单中的指纹与当前源码哈希来判断产物是否过期，
不再依赖 mtime——后者在 git checkout、跨机器同步、CI 缓存恢复时都不可靠。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def _configure_stdout() -> None:
    """让输出不受控制台代码页限制。

    Windows 的默认 stdout 编码可能是 cp1252/cp936，直接 print 中文会抛
    UnicodeEncodeError（CI 上即如此）。用 errors="replace" 兜底，
    保证脚本在任何代码页下都不会因为日志文本而失败。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


_configure_stdout()

from build_manifest import source_fingerprint, write_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="写入前端构建指纹清单")
    parser.add_argument(
        "--frontend-dir",
        default=str(PROJECT_ROOT / "frontend"),
        help="前端目录（默认 <repo>/frontend）",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只比对指纹，不写文件；过期时以退出码 1 结束",
    )
    args = parser.parse_args()

    frontend_dir = Path(args.frontend_dir).resolve()
    dist_dir = frontend_dir / "dist"

    if not (dist_dir / "index.html").is_file():
        print(f"[ERROR] 未找到前端产物: {dist_dir / 'index.html'}")
        print("        请先执行: cd frontend && npm run build")
        return 1

    fingerprint = source_fingerprint(frontend_dir)

    if args.check_only:
        from build_manifest import read_manifest

        manifest = read_manifest(dist_dir)
        recorded = (manifest or {}).get("fingerprint")
        if recorded is None:
            print("[ERROR] 缺少构建指纹清单，请重新运行（不带 --check-only）")
            return 1
        if recorded != fingerprint:
            print("[ERROR] 前端产物已过期")
            print(f"        记录: {recorded}")
            print(f"        当前: {fingerprint}")
            return 1
        print("[OK] 前端产物与源码一致")
        return 0

    path = write_manifest(dist_dir, fingerprint)
    print(f"[OK] 已写入构建指纹: {path}")
    print(f"     fingerprint = {fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
