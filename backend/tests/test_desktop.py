"""Desktop launcher tests."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

import desktop
import local_runtime


def _touch(path, timestamp: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test", encoding="utf-8")
    os.utime(path, (timestamp, timestamp))


def test_frontend_build_is_stale_when_source_is_newer(tmp_path):
    _touch(tmp_path / "frontend" / "dist" / "index.html", 100)
    _touch(tmp_path / "frontend" / "src" / "App.vue", 200)

    assert desktop._frontend_build_is_stale(tmp_path) is True


def test_frontend_build_is_current_when_bundle_is_newer(tmp_path):
    _touch(tmp_path / "frontend" / "src" / "App.vue", 100)
    _touch(tmp_path / "frontend" / "package.json", 150)
    _touch(tmp_path / "frontend" / "dist" / "index.html", 200)

    assert desktop._frontend_build_is_stale(tmp_path) is False


class _HttpResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_wait_for_server_requires_matching_public_identity(monkeypatch):
    requests = []
    payloads = iter([
        [],
        {"service": "other-service", "instance_id": "desktop-a"},
        {"service": "ai-serial-bridge", "instance_id": "desktop-a"},
    ])

    def fake_urlopen(request, timeout):
        requests.append(request)
        return _HttpResponse(next(payloads))

    monkeypatch.setattr(desktop, "_open_loopback_url", fake_urlopen)

    assert desktop._wait_for_server(
        "127.0.0.1",
        8123,
        "desktop-a",
        timeout=0.5,
    ) is True
    assert len(requests) == 3
    assert requests[0].full_url == "http://127.0.0.1:8123/api/config"
    assert requests[0].get_header("Authorization") is None


def _install_desktop_fakes(monkeypatch, on_start=None):
    servers = []
    windows = []

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            servers.append(self)

        def run(self):
            return None

    class ClosedEvent:
        def __init__(self):
            self.callback = None

        def __iadd__(self, callback):
            self.callback = callback
            return self

    def create_window(**kwargs):
        window = SimpleNamespace(events=SimpleNamespace(closed=ClosedEvent()))
        windows.append((window, kwargs))
        return window

    def start(*, debug):
        if on_start is not None:
            on_start()

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(
            Config=lambda *args, **kwargs: SimpleNamespace(args=args, kwargs=kwargs),
            Server=FakeServer,
        ),
    )
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(app=object()))
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(create_window=create_window, start=start),
    )
    return servers, windows


def _prepare_desktop_run(monkeypatch, tmp_path, *, wait_result=True, on_start=None):
    base_dir = tmp_path / "application"
    # 真实的构建产物必然包含入口页；仅创建目录不足以代表可用产物，
    # 因为启动器以 index.html 是否存在来判定资源是否就绪。
    dist_dir = base_dir / "frontend" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    state_dir = tmp_path / "state"
    monkeypatch.setattr(desktop, "_get_base_dir", lambda: str(base_dir))
    monkeypatch.setattr(desktop, "_frontend_build_is_stale", lambda base: False)
    monkeypatch.setattr(desktop, "_find_free_port", lambda preferred=8000: 8123)
    monkeypatch.setattr(
        desktop,
        "_wait_for_server",
        lambda host, port, instance_id, timeout=10.0: wait_result,
    )
    monkeypatch.setenv("AI_SERIAL_STATE_DIR", str(state_dir))
    monkeypatch.delenv("AI_SERIAL_TOKEN", raising=False)
    servers, windows = _install_desktop_fakes(monkeypatch, on_start=on_start)
    return state_dir, servers, windows


def test_desktop_publishes_manifest_after_readiness_and_cleans_on_exit(
    monkeypatch,
    tmp_path,
):
    observed = {}
    state_dir = tmp_path / "state"

    def on_start():
        payload = json.loads(
            (state_dir / "runtime.json").read_text(encoding="utf-8")
        )
        observed.update(payload)

    _, servers, windows = _prepare_desktop_run(
        monkeypatch,
        tmp_path,
        on_start=on_start,
    )

    desktop.main()

    saved_token = local_runtime.load_token(state_dir)
    assert saved_token
    assert observed == {
        "version": 1,
        "service": "ai-serial-bridge",
        "api_url": "http://127.0.0.1:8123",
        "pid": os.getpid(),
        "instance_id": observed["instance_id"],
        "started_at": observed["started_at"],
    }
    assert observed["instance_id"]
    assert saved_token not in json.dumps(observed)
    assert local_runtime.read_runtime_manifest(state_dir) is None
    assert servers[0].should_exit is True
    assert windows[0][1]["url"].startswith("http://127.0.0.1:8123/#token=")


def test_desktop_readiness_failure_stops_server_without_manifest(
    monkeypatch,
    tmp_path,
):
    state_dir, servers, _ = _prepare_desktop_run(
        monkeypatch,
        tmp_path,
        wait_result=False,
    )

    with pytest.raises(SystemExit):
        desktop.main()

    assert not (state_dir / "runtime.json").exists()
    assert servers[0].should_exit is True


def test_second_desktop_instance_exits_before_starting_server(
    monkeypatch,
    tmp_path,
):
    state_dir, servers, _ = _prepare_desktop_run(monkeypatch, tmp_path)

    with local_runtime.desktop_instance_lock(state_dir=state_dir):
        with pytest.raises(SystemExit):
            desktop.main()

    assert servers == []


def test_old_desktop_exit_preserves_new_instance_manifest(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"

    def on_start():
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:9009",
            pid=9009,
            instance_id="new-instance",
            state_dir=state_dir,
        )
        raise RuntimeError("window startup failed")

    _, servers, _ = _prepare_desktop_run(
        monkeypatch,
        tmp_path,
        on_start=on_start,
    )

    with pytest.raises(RuntimeError, match="window startup failed"):
        desktop.main()

    manifest = local_runtime.read_runtime_manifest(state_dir)
    assert manifest is not None
    assert manifest.instance_id == "new-instance"
    assert servers[0].should_exit is True
