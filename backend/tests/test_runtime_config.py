"""Tests for local desktop/MCP pairing state."""

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

import local_runtime


def test_first_token_is_persisted_and_reused(tmp_path):
    first = local_runtime.load_or_create_token(state_dir=tmp_path)
    second = local_runtime.load_or_create_token(state_dir=tmp_path)

    assert len(first) >= 32
    assert second == first
    payload = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
    assert payload == {"version": 1, "token": first}


def test_concurrent_first_starters_share_one_token(tmp_path):
    def load():
        return local_runtime.load_or_create_token(state_dir=tmp_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: load(), range(8)))

    assert len(set(tokens)) == 1


def test_preexisting_unlocked_lock_file_does_not_block_token_creation(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".credentials.lock").write_text("orphaned", encoding="utf-8")

    token = local_runtime.load_or_create_token(state_dir=tmp_path)

    assert token


def test_state_lock_file_persists_and_can_be_reacquired(tmp_path):
    lock_path = tmp_path / ".runtime.lock"

    with local_runtime._state_lock(lock_path):
        assert lock_path.exists()

    assert lock_path.exists()
    with local_runtime._state_lock(lock_path):
        assert lock_path.exists()


def test_second_desktop_instance_lock_is_rejected(tmp_path):
    with local_runtime.desktop_instance_lock(state_dir=tmp_path):
        with pytest.raises(local_runtime.DesktopAlreadyRunning):
            with local_runtime.desktop_instance_lock(
                state_dir=tmp_path,
                timeout=0.05,
            ):
                pytest.fail("second desktop lock unexpectedly acquired")


def test_active_desktop_lock_identity_is_visible_cross_process(tmp_path):
    script = """
import sys
from local_runtime import desktop_instance_lock

with desktop_instance_lock(state_dir=sys.argv[1]) as instance_id:
    print(instance_id, flush=True)
    sys.stdin.readline()
"""
    env = os.environ.copy()
    backend_dir = str(Path.cwd() / "backend")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (backend_dir, env.get("PYTHONPATH", "")) if value
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path.cwd(),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        instance_id = process.stdout.readline().strip()
        assert instance_id
        assert local_runtime._desktop_instance_is_active(
            instance_id,
            state_dir=tmp_path,
        ) is True
        saved = local_runtime.load_or_create_token(state_dir=tmp_path)
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:9345",
            pid=process.pid,
            instance_id=instance_id,
            state_dir=tmp_path,
        )
        assert local_runtime.resolve_connection_targets(env={}, state_dir=tmp_path)[0] == (
            local_runtime.ConnectionTarget(
                "http://127.0.0.1:9345",
                saved,
                "desktop-runtime",
                instance_id,
            )
        )
    finally:
        if process.stdin is not None:
            process.stdin.write("\n")
            process.stdin.flush()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0


def test_explicit_token_overrides_without_replacing_saved_token(tmp_path):
    saved = local_runtime.load_or_create_token(state_dir=tmp_path)
    explicit = "explicit-token-for-test"

    assert local_runtime.load_or_create_token(
        explicit_token=explicit,
        state_dir=tmp_path,
    ) == explicit
    assert local_runtime.load_token(state_dir=tmp_path) == saved


def test_manifest_round_trip_and_owner_only_cleanup(tmp_path):
    manifest = local_runtime.write_runtime_manifest(
        "http://127.0.0.1:9123",
        pid=1234,
        instance_id="instance-a",
        state_dir=tmp_path,
        started_at=10.5,
    )

    assert local_runtime.read_runtime_manifest(state_dir=tmp_path) == manifest
    assert local_runtime.remove_runtime_manifest("instance-b", state_dir=tmp_path) is False
    assert local_runtime.read_runtime_manifest(state_dir=tmp_path) == manifest
    assert local_runtime.remove_runtime_manifest("instance-a", state_dir=tmp_path) is True
    assert local_runtime.read_runtime_manifest(state_dir=tmp_path) is None


def test_manifest_rejects_non_loopback_endpoint(tmp_path):
    with pytest.raises(local_runtime.RuntimeConfigError):
        local_runtime.write_runtime_manifest(
            "http://attacker.example:8080",
            pid=1234,
            instance_id="instance-a",
            state_dir=tmp_path,
        )


def test_connection_targets_do_not_send_local_token_to_remote_url(tmp_path):
    local_runtime.load_or_create_token(state_dir=tmp_path)

    targets = local_runtime.resolve_connection_targets(
        env={
            "AI_SERIAL_API_URL": "https://remote.example/api",
            "AI_SERIAL_TOKEN": "remote-secret",
        },
        state_dir=tmp_path,
    )

    assert len(targets) == 1
    assert targets[0].api_url == "https://remote.example/api"
    assert targets[0].token == "remote-secret"


def test_explicit_remote_target_does_not_read_local_pairing_state(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        local_runtime,
        "read_runtime_manifest",
        lambda *args, **kwargs: pytest.fail("remote target read runtime manifest"),
    )
    monkeypatch.setattr(
        local_runtime,
        "load_token",
        lambda *args, **kwargs: pytest.fail("remote target read saved token"),
    )

    targets = local_runtime.resolve_connection_targets(
        env={"AI_SERIAL_API_URL": "https://remote.example/bridge"},
        state_dir=tmp_path,
    )

    assert targets == [
        local_runtime.ConnectionTarget(
            "https://remote.example/bridge",
            "",
            "environment",
        )
    ]


def test_loopback_env_target_can_fall_back_to_active_manifest(tmp_path):
    saved = local_runtime.load_or_create_token(state_dir=tmp_path)
    with local_runtime.desktop_instance_lock(state_dir=tmp_path) as instance_id:
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:9345",
            pid=os.getpid(),
            instance_id=instance_id,
            state_dir=tmp_path,
        )
        targets = local_runtime.resolve_connection_targets(
            env={
                "AI_SERIAL_API_URL": "http://127.0.0.1:8000",
                "AI_SERIAL_TOKEN": "stale-token",
            },
            state_dir=tmp_path,
        )

    assert [(item.api_url, item.token) for item in targets] == [
        ("http://127.0.0.1:8000", "stale-token"),
        ("http://127.0.0.1:9345", "stale-token"),
        ("http://127.0.0.1:9345", saved),
    ]


def test_url_only_loopback_target_does_not_receive_saved_token(tmp_path):
    saved = local_runtime.load_or_create_token(state_dir=tmp_path)
    with local_runtime.desktop_instance_lock(state_dir=tmp_path) as instance_id:
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:9345",
            pid=os.getpid(),
            instance_id=instance_id,
            state_dir=tmp_path,
        )
        targets = local_runtime.resolve_connection_targets(
            env={"AI_SERIAL_API_URL": "http://127.0.0.1:8000"},
            state_dir=tmp_path,
        )

    assert targets == [
        local_runtime.ConnectionTarget(
            "http://127.0.0.1:8000",
            "",
            "environment",
        ),
        local_runtime.ConnectionTarget(
            "http://127.0.0.1:9345",
            saved,
            "desktop-runtime",
            instance_id,
        ),
    ]


def test_default_target_without_manifest_does_not_receive_saved_token(tmp_path):
    local_runtime.load_or_create_token(state_dir=tmp_path)

    targets = local_runtime.resolve_connection_targets(env={}, state_dir=tmp_path)

    assert targets == [
        local_runtime.ConnectionTarget(
            local_runtime.DEFAULT_API_URL,
            "",
            "default",
        )
    ]


def test_explicit_loopback_override_survives_corrupt_local_state(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "credentials.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "runtime.json").write_text("not-json", encoding="utf-8")

    targets = local_runtime.resolve_connection_targets(
        env={
            "AI_SERIAL_API_URL": "http://127.0.0.1:8123",
            "AI_SERIAL_TOKEN": "explicit-token",
        },
        state_dir=tmp_path,
    )

    assert targets == [
        local_runtime.ConnectionTarget(
            "http://127.0.0.1:8123",
            "explicit-token",
            "environment",
        )
    ]


def test_explicit_token_override_survives_corrupt_local_state(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "credentials.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "runtime.json").write_text("not-json", encoding="utf-8")

    targets = local_runtime.resolve_connection_targets(
        env={"AI_SERIAL_TOKEN": "explicit-token"},
        state_dir=tmp_path,
    )

    assert targets == [
        local_runtime.ConnectionTarget(
            local_runtime.DEFAULT_API_URL,
            "explicit-token",
            "default",
        )
    ]


def test_url_only_loopback_override_survives_corrupt_local_state(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "credentials.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "runtime.json").write_text("not-json", encoding="utf-8")

    targets = local_runtime.resolve_connection_targets(
        env={"AI_SERIAL_API_URL": "http://127.0.0.1:8123"},
        state_dir=tmp_path,
    )

    assert targets == [
        local_runtime.ConnectionTarget(
            "http://127.0.0.1:8123",
            "",
            "environment",
        )
    ]


def test_corrupt_pairing_state_degrades_to_tokenless_default(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "credentials.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "runtime.json").write_text("not-json", encoding="utf-8")

    targets = local_runtime.resolve_connection_targets(env={}, state_dir=tmp_path)

    assert targets == [
        local_runtime.ConnectionTarget(
            local_runtime.DEFAULT_API_URL,
            "",
            "default",
        )
    ]


def test_manifest_target_keeps_tokenless_default_fallback(tmp_path):
    saved = local_runtime.load_or_create_token(state_dir=tmp_path)
    with local_runtime.desktop_instance_lock(state_dir=tmp_path) as instance_id:
        local_runtime.write_runtime_manifest(
            "http://127.0.0.1:9345",
            pid=os.getpid(),
            instance_id=instance_id,
            state_dir=tmp_path,
        )
        targets = local_runtime.resolve_connection_targets(env={}, state_dir=tmp_path)

    assert targets == [
        local_runtime.ConnectionTarget(
            "http://127.0.0.1:9345",
            saved,
            "desktop-runtime",
            instance_id,
        ),
        local_runtime.ConnectionTarget(
            local_runtime.DEFAULT_API_URL,
            "",
            "default",
        ),
    ]


def test_dead_manifest_is_removed_before_resolving_targets(tmp_path):
    local_runtime.load_or_create_token(state_dir=tmp_path)
    local_runtime.write_runtime_manifest(
        "http://127.0.0.1:9345",
        pid=9345,
        instance_id="dead-instance",
        state_dir=tmp_path,
    )
    targets = local_runtime.resolve_connection_targets(env={}, state_dir=tmp_path)

    assert targets == [
        local_runtime.ConnectionTarget(
            local_runtime.DEFAULT_API_URL,
            "",
            "default",
        )
    ]
    assert local_runtime.read_runtime_manifest(state_dir=tmp_path) is None


def test_new_desktop_lock_does_not_activate_stale_manifest(tmp_path):
    local_runtime.load_or_create_token(state_dir=tmp_path)
    local_runtime.write_runtime_manifest(
        "http://127.0.0.1:9345",
        pid=9345,
        instance_id="stale-instance",
        state_dir=tmp_path,
    )

    with local_runtime.desktop_instance_lock(state_dir=tmp_path):
        targets = local_runtime.resolve_connection_targets(env={}, state_dir=tmp_path)

    assert targets == [
        local_runtime.ConnectionTarget(
            local_runtime.DEFAULT_API_URL,
            "",
            "default",
        )
    ]


def test_corrupt_credentials_are_not_silently_replaced(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "credentials.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(local_runtime.RuntimeConfigError):
        local_runtime.load_token(state_dir=tmp_path)


def test_old_manifest_cleanup_cannot_delete_a_newer_manifest(
    tmp_path,
    monkeypatch,
):
    local_runtime.write_runtime_manifest(
        "http://127.0.0.1:9001",
        pid=1001,
        instance_id="old-instance",
        state_dir=tmp_path,
    )
    original_read = local_runtime.read_runtime_manifest
    removal_read = threading.Event()
    release_removal = threading.Event()
    writer_finished = threading.Event()
    errors = []

    def delayed_read(state_dir=None):
        manifest = original_read(state_dir)
        if threading.current_thread().name == "remove-old-manifest":
            removal_read.set()
            if not release_removal.wait(timeout=2):
                raise AssertionError("timed out coordinating manifest cleanup")
        return manifest

    monkeypatch.setattr(local_runtime, "read_runtime_manifest", delayed_read)

    def remove_old():
        try:
            local_runtime.remove_runtime_manifest(
                "old-instance",
                state_dir=tmp_path,
            )
        except BaseException as exc:
            errors.append(exc)

    def write_new():
        try:
            local_runtime.write_runtime_manifest(
                "http://127.0.0.1:9002",
                pid=1002,
                instance_id="new-instance",
                state_dir=tmp_path,
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            writer_finished.set()

    remover = threading.Thread(target=remove_old, name="remove-old-manifest")
    writer = threading.Thread(target=write_new, name="write-new-manifest")
    remover.start()
    assert removal_read.wait(timeout=2)
    writer.start()
    writer_finished.wait(timeout=0.2)
    release_removal.set()
    remover.join(timeout=2)
    writer.join(timeout=2)

    assert not remover.is_alive()
    assert not writer.is_alive()
    assert errors == []
    manifest = original_read(tmp_path)
    assert manifest is not None
    assert manifest.instance_id == "new-instance"
    assert manifest.api_url == "http://127.0.0.1:9002"
