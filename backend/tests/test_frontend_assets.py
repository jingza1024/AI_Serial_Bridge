"""frontend_assets 的路径解析测试。

覆盖三种真实布局：
  - 源码运行（main.py 在 <root>/backend/）
  - PyInstaller onefile（资源在 sys._MEIPASS 下）
  - PyInstaller onedir（资源在 <exe_dir>/_internal 下）

这些路径在开发机上无法直接复现，必须用合成目录验证。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import frontend_assets  # noqa: E402


def _make_dist(root: Path) -> Path:
    """在 root 下建一个带 index.html 的 frontend/dist 目录。"""
    dist = root / "frontend" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return dist


# --- 源码布局 ---

def test_source_layout_resolves_from_backend_module(tmp_path):
    dist = _make_dist(tmp_path)
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    module_file = backend_dir / "main.py"
    module_file.write_text("", encoding="utf-8")

    resolved = frontend_assets.resolve_dist_dir(module_file=module_file)

    assert resolved == dist.resolve()


def test_source_layout_explains_missing_build(tmp_path):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    module_file = backend_dir / "main.py"
    module_file.write_text("", encoding="utf-8")

    assert frontend_assets.resolve_dist_dir(module_file=module_file) is None


# --- PyInstaller onefile ---

def test_onefile_layout_resolves_from_meipass(tmp_path):
    meipass = tmp_path / "_MEI12345"
    dist = _make_dist(meipass)

    resolved = frontend_assets.resolve_dist_dir(meipass=str(meipass))

    assert resolved == dist.resolve()


def test_meipass_takes_priority_over_stale_source_tree(tmp_path):
    """打包运行时若源码目录残留旧 dist，应优先使用 _MEIPASS 内的产物。"""
    meipass = tmp_path / "_MEI12345"
    bundled = _make_dist(meipass)

    source_root = tmp_path / "src"
    _make_dist(source_root)
    backend_dir = source_root / "backend"
    backend_dir.mkdir()
    module_file = backend_dir / "main.py"
    module_file.write_text("", encoding="utf-8")

    resolved = frontend_assets.resolve_dist_dir(
        meipass=str(meipass),
        module_file=module_file,
    )

    assert resolved == bundled.resolve()


# --- PyInstaller onedir ---

def test_onedir_layout_resolves_from_internal(tmp_path):
    exe_dir = tmp_path / "AI Serial Bridge"
    dist = _make_dist(exe_dir / "_internal")
    exe = exe_dir / "AI Serial Bridge.exe"
    exe.write_text("", encoding="utf-8")

    resolved = frontend_assets.resolve_dist_dir(
        executable=str(exe),
        frozen=True,
    )

    assert resolved == dist.resolve()


def test_onedir_layout_falls_back_to_exe_sibling(tmp_path):
    exe_dir = tmp_path / "AI Serial Bridge"
    dist = _make_dist(exe_dir)
    exe = exe_dir / "AI Serial Bridge.exe"
    exe.write_text("", encoding="utf-8")

    resolved = frontend_assets.resolve_dist_dir(
        executable=str(exe),
        frozen=True,
    )

    assert resolved == dist.resolve()


def test_exe_sibling_is_ignored_when_not_frozen(tmp_path):
    """源码模式下不应把无关的 exe 同级目录当成产物位置。"""
    exe_dir = tmp_path / "bin"
    _make_dist(exe_dir)
    exe = exe_dir / "python.exe"
    exe.write_text("", encoding="utf-8")

    resolved = frontend_assets.resolve_dist_dir(
        executable=str(exe),
        frozen=False,
    )

    assert resolved is None


# --- 通用性质 ---

def test_dist_dir_requires_index_html(tmp_path):
    """只存在空目录不算有效产物——这正是原先白屏的根因。"""
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)

    assert frontend_assets.resolve_dist_dir(meipass=str(tmp_path)) is None


def test_candidates_are_deduplicated(tmp_path):
    """同一路径的多种推导方式不应重复出现。"""
    dist = _make_dist(tmp_path)
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    module_file = backend_dir / "main.py"
    module_file.write_text("", encoding="utf-8")

    candidates = frontend_assets.candidate_dist_dirs(
        meipass=str(tmp_path),
        module_file=module_file,
    )

    assert len(candidates) == len(set(candidates))
    assert candidates[0] == dist.resolve()


def test_missing_dist_message_lists_checked_locations():
    message = frontend_assets.describe_missing_dist()

    assert "frontend" in message
    assert "npm run build" in message
    # 诊断信息必须能指导用户定位，而不是只抛一句"not found"
    assert "已检查以下位置" in message
