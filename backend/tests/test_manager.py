"""服务管理器安全测试：只终止经过身份校验的本项目子进程。"""

from unittest.mock import Mock

import manager


def test_stop_by_pids_refuses_unverified_process(monkeypatch):
    monkeypatch.setattr(manager, "PID_FILE", Mock())
    monkeypatch.setattr(manager, "_load_pids", lambda: {
        "backend": {
            "pid": 1234,
            "command": str(manager.BACKEND_DIR / "main.py"),
        }
    })
    monkeypatch.setattr(manager, "_is_process_running", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches", lambda pid, marker: False)
    killed = []
    monkeypatch.setattr(manager, "_kill_process_tree", killed.append)

    assert manager._stop_by_pids() is False
    assert killed == []


def test_stop_by_pids_terminates_verified_process(monkeypatch):
    monkeypatch.setattr(manager, "PID_FILE", Mock())
    monkeypatch.setattr(manager, "_load_pids", lambda: {
        "backend": {
            "pid": 1234,
            "command": str(manager.BACKEND_DIR / "main.py"),
        }
    })
    monkeypatch.setattr(manager, "_is_process_running", lambda pid: True)
    monkeypatch.setattr(manager, "_process_matches", lambda pid, marker: True)
    killed = []
    monkeypatch.setattr(manager, "_kill_process_tree", killed.append)

    assert manager._stop_by_pids() is True
    assert killed == [1234]
