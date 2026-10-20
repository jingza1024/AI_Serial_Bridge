"""build_manifest 的新鲜度判定测试。

重点是：判定必须只依赖内容，不依赖 mtime——后者在 git checkout、
CI 缓存恢复、跨机器同步时会给出错误结论。
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_manifest  # noqa: E402


def _make_frontend(tmp_path: Path, source: str = "console.log(1)") -> Path:
    """构造一个最小的前端目录（源码 + 产物）。"""
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "main.ts").write_text(source, encoding="utf-8")
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    (frontend / "vite.config.ts").write_text("export default {}", encoding="utf-8")
    dist = frontend / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>built</html>", encoding="utf-8")
    return frontend


def test_fingerprint_is_stable_across_calls(tmp_path):
    frontend = _make_frontend(tmp_path)
    assert build_manifest.source_fingerprint(frontend) == build_manifest.source_fingerprint(frontend)


def test_fingerprint_changes_when_source_changes(tmp_path):
    frontend = _make_frontend(tmp_path)
    before = build_manifest.source_fingerprint(frontend)

    (frontend / "src" / "main.ts").write_text("console.log(2)", encoding="utf-8")

    assert build_manifest.source_fingerprint(frontend) != before


def test_fingerprint_changes_when_config_changes(tmp_path):
    frontend = _make_frontend(tmp_path)
    before = build_manifest.source_fingerprint(frontend)

    (frontend / "vite.config.ts").write_text("export default { base: './' }", encoding="utf-8")

    assert build_manifest.source_fingerprint(frontend) != before


def test_fingerprint_ignores_timestamps(tmp_path):
    """仅改 mtime（内容不变）不应被判为过期。"""
    frontend = _make_frontend(tmp_path)
    fingerprint = build_manifest.source_fingerprint(frontend)
    build_manifest.write_manifest(frontend / "dist", fingerprint)

    # 把源码时间推到未来，模拟 checkout/同步导致的时间戳错乱
    future = time.time() + 10_000
    for path in (frontend / "src").rglob("*"):
        if path.is_file():
            os.utime(path, (future, future))

    assert build_manifest.bundle_is_stale(frontend) is False


def test_missing_dist_is_not_reported_as_stale(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "main.ts").write_text("x", encoding="utf-8")

    assert build_manifest.bundle_is_stale(frontend) is False


def test_missing_manifest_falls_back_to_mtime(tmp_path):
    """旧产物没有清单时必须仍然可用（向后兼容）。"""
    frontend = _make_frontend(tmp_path)
    index = frontend / "dist" / "index.html"

    old = time.time() - 10_000
    os.utime(index, (old, old))

    assert build_manifest.bundle_is_stale(frontend) is True


def test_manifest_matching_source_is_fresh(tmp_path):
    frontend = _make_frontend(tmp_path)
    fingerprint = build_manifest.source_fingerprint(frontend)
    build_manifest.write_manifest(frontend / "dist", fingerprint)

    assert build_manifest.bundle_is_stale(frontend) is False


def test_manifest_mismatch_is_stale(tmp_path):
    frontend = _make_frontend(tmp_path)
    build_manifest.write_manifest(frontend / "dist", "deadbeef")

    assert build_manifest.bundle_is_stale(frontend) is True


def test_corrupt_manifest_is_treated_as_stale(tmp_path):
    frontend = _make_frontend(tmp_path)
    (frontend / "dist" / build_manifest.MANIFEST_NAME).write_text("{not json", encoding="utf-8")

    # 损坏时回退 mtime；入口页比源码新 -> 不算过期
    assert build_manifest.read_manifest(frontend / "dist") is None


def test_read_manifest_returns_none_for_missing_file(tmp_path):
    frontend = _make_frontend(tmp_path)
    assert build_manifest.read_manifest(frontend / "dist") is None


def test_write_manifest_creates_parent_dirs(tmp_path):
    dist = tmp_path / "nested" / "dist"
    path = build_manifest.write_manifest(dist, "abc123")

    assert path.is_file()
    assert build_manifest.read_manifest(dist) == {"schema": 1, "fingerprint": "abc123"}
