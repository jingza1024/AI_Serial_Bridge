"""Offline encrypted-log migration and rollback tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest

import log_store
from log_store import LogMigrationError, SerialLogStore, migrate_log_directory


def plaintext_line(content: str) -> bytes:
    return json.dumps({"kind": "message", "content": content}).encode("utf-8") + b"\n"


def encrypted_line(key: bytes, content: str) -> bytes:
    payload = plaintext_line(content).rstrip(b"\n")
    return b"enc:v1:" + Fernet(key).encrypt(payload) + b"\n"


def test_migrates_plaintext_logs_to_encryption_with_backup(tmp_path: Path):
    path = tmp_path / "COM17.jsonl"
    original = plaintext_line("Linux ready")
    path.write_bytes(original)
    new_key = Fernet.generate_key()

    result = migrate_log_directory(tmp_path, new_key=new_key)

    assert result["files"] == 1
    assert result["records"] == 1
    assert result["changed_files"] == 1
    assert path.read_bytes().startswith(b"enc:v1:")
    backup = Path(result["backups"][0])
    assert backup.read_bytes() == original
    assert SerialLogStore(tmp_path, encryption_key=new_key).query("COM17")[0]["content"] == "Linux ready"


def test_rotates_encrypted_logs_from_old_key_to_new_key(tmp_path: Path):
    path = tmp_path / "COM17.jsonl"
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    path.write_bytes(encrypted_line(old_key, "kernel healthy"))

    result = migrate_log_directory(tmp_path, old_key=old_key, new_key=new_key)

    assert SerialLogStore(tmp_path, encryption_key=new_key).query("COM17")[0]["content"] == "kernel healthy"
    assert SerialLogStore(tmp_path, encryption_key=old_key).query("COM17") == []
    assert SerialLogStore(Path(result["backups"][0]).parent, encryption_key=old_key)._decode_line(
        Path(result["backups"][0]).read_bytes(),
    )["content"] == "kernel healthy"


def test_wrong_old_key_rejects_rotation_without_modifying_files(tmp_path: Path):
    path = tmp_path / "COM17.jsonl"
    path.write_bytes(encrypted_line(Fernet.generate_key(), "secret"))
    original = path.read_bytes()

    with pytest.raises(LogMigrationError, match="cannot decrypt"):
        migrate_log_directory(
            tmp_path,
            old_key=Fernet.generate_key(),
            new_key=Fernet.generate_key(),
        )

    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.migration-backup-*"))


def test_dry_run_validates_without_writing_or_backups(tmp_path: Path):
    path = tmp_path / "COM17.jsonl"
    original = plaintext_line("dry run")
    path.write_bytes(original)

    result = migrate_log_directory(tmp_path, new_key=Fernet.generate_key(), dry_run=True)

    assert result["dry_run"] is True
    assert result["changed_files"] == 1
    assert result["backups"] == []
    assert path.read_bytes() == original


def test_replacement_failure_rolls_back_every_changed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = tmp_path / "COM16.jsonl"
    second = tmp_path / "COM17.jsonl"
    first.write_bytes(plaintext_line("first"))
    second.write_bytes(plaintext_line("second"))
    originals = {first: first.read_bytes(), second: second.read_bytes()}
    real_replace = log_store.os.replace
    failed = False

    def fail_second_replace(source, destination):
        nonlocal failed
        if Path(destination) == second and not failed:
            failed = True
            raise OSError("simulated replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(log_store.os, "replace", fail_second_replace)

    with pytest.raises(LogMigrationError, match="rolled back"):
        migrate_log_directory(tmp_path, new_key=Fernet.generate_key())

    assert first.read_bytes() == originals[first]
    assert second.read_bytes() == originals[second]


def test_rotation_cli_reads_keys_only_from_environment(tmp_path: Path):
    path = tmp_path / "COM17.jsonl"
    path.write_bytes(plaintext_line("cli dry run"))
    key = Fernet.generate_key().decode("ascii")
    environment = os.environ.copy()
    environment["AI_SERIAL_LOG_KEY"] = key
    environment.pop("AI_SERIAL_LOG_OLD_KEY", None)
    script = Path(__file__).resolve().parents[2] / "scripts" / "rotate_log_key.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--log-dir", str(tmp_path), "--dry-run"],
        cwd=script.parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"dry_run": true' in completed.stdout
    assert key not in completed.stdout
    assert path.read_bytes() == plaintext_line("cli dry run")
