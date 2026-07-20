"""Bounded, rotating JSONL persistence for serial events and raw receive chunks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import tempfile
import threading
import time

from cryptography.fernet import Fernet, InvalidToken

from serial_manager import SerialMessage, SerialRawChunk


_SAFE_PORT = re.compile(r"[^A-Za-z0-9_.-]+")
_LOG_FILE = re.compile(r".+\.jsonl(?:\.\d+)?$")
_ENCRYPTION_PREFIX = b"enc:v1:"


class LogMigrationError(RuntimeError):
    """Raised when an offline log migration cannot complete safely."""


def _create_fernet(key: str | bytes | None, name: str) -> Fernet | None:
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except (ValueError, UnicodeEncodeError) as exc:
        raise LogMigrationError(f"invalid {name}: {exc}") from exc


def decode_log_line(line: bytes, decryptor: Fernet | None = None) -> dict:
    """Decode one JSONL record and raise instead of silently dropping corruption."""
    payload = line.strip()
    if not payload:
        raise LogMigrationError("empty log record")
    if payload.startswith(_ENCRYPTION_PREFIX):
        if decryptor is None:
            raise LogMigrationError("cannot decrypt encrypted log record without the old key")
        try:
            payload = decryptor.decrypt(payload[len(_ENCRYPTION_PREFIX):])
        except InvalidToken as exc:
            raise LogMigrationError("cannot decrypt encrypted log record with the old key") from exc
    try:
        record = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LogMigrationError(f"invalid JSON log record: {exc}") from exc
    if not isinstance(record, dict):
        raise LogMigrationError("log record must be a JSON object")
    return record


def encode_log_line(record: dict, encryptor: Fernet | None = None) -> bytes:
    """Encode one validated log record in the store's canonical JSONL format."""
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if encryptor is not None:
        payload = _ENCRYPTION_PREFIX + encryptor.encrypt(payload)
    return payload + b"\n"


def _migration_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_file() and _LOG_FILE.fullmatch(path.name))


def _backup_path(path: Path, stamp: str) -> Path:
    candidate = path.with_name(f"{path.name}.migration-backup-{stamp}")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.migration-backup-{stamp}-{index}")
        index += 1
    return candidate


def migrate_log_directory(
    root: Path | str,
    *,
    new_key: str | bytes,
    old_key: str | bytes | None = None,
    dry_run: bool = False,
) -> dict:
    """Encrypt plaintext logs or rotate encrypted logs without partial updates."""
    directory = Path(root)
    new_fernet = _create_fernet(new_key, "new log key")
    if new_fernet is None:
        raise LogMigrationError("new log key is required")
    old_fernet = _create_fernet(old_key, "old log key")
    paths = _migration_paths(directory)
    staged: dict[Path, bytes] = {}
    records = 0

    for path in paths:
        output = bytearray()
        for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
            try:
                record = decode_log_line(line, old_fernet)
            except LogMigrationError as exc:
                raise LogMigrationError(f"{path.name}:{line_number}: {exc}") from exc
            output.extend(encode_log_line(record, new_fernet))
            records += 1
        staged[path] = bytes(output)

    result = {
        "files": len(paths),
        "records": records,
        "changed_files": len(paths),
        "dry_run": bool(dry_run),
        "backups": [],
    }
    if dry_run or not paths:
        return result

    directory.mkdir(parents=True, exist_ok=True)
    stamp = f"{time.time_ns()}-{os.getpid()}"
    temporary: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, payload in staged.items():
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.migration-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temporary[path] = Path(handle.name)
            os.chmod(temporary[path], path.stat().st_mode)

        for path in paths:
            backup = _backup_path(path, stamp)
            shutil.copy2(path, backup)
            backups[path] = backup

        for path in paths:
            os.replace(temporary[path], path)
            replaced.append(path)
    except OSError as exc:
        rollback_errors: list[str] = []
        for path in reversed(replaced):
            backup = backups.get(path)
            if backup is None:
                continue
            try:
                os.replace(backup, path)
            except OSError as rollback_exc:
                rollback_errors.append(f"{path.name}: {rollback_exc}")
        for path, backup in backups.items():
            if path not in replaced and backup.exists():
                backup.unlink()
        detail = f"migration failed; changes were rolled back: {exc}"
        if rollback_errors:
            detail += f"; rollback errors: {'; '.join(rollback_errors)}"
        raise LogMigrationError(detail) from exc
    finally:
        for path in temporary.values():
            if path.exists():
                path.unlink()

    result["backups"] = [str(backups[path]) for path in paths]
    return result


class SerialLogStore:
    def __init__(
        self,
        root: Path | str | None = None,
        max_bytes: int = 10 * 1024 * 1024,
        backups: int = 5,
        queue_size: int = 5000,
        retention_days: int = 0,
        encryption_key: str | bytes | None = None,
    ):
        default_root = Path.home() / ".ai-serial-bridge" / "logs"
        self.root = Path(root or os.environ.get("AI_SERIAL_LOG_DIR") or default_root)
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.backups = min(max(int(backups), 1), 20)
        self.retention_days = max(int(retention_days), 0)
        key = encryption_key if encryption_key is not None else os.environ.get("AI_SERIAL_LOG_KEY", "")
        self._fernet: Fernet | None = None
        self._key_error = ""
        if key:
            try:
                self._fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)
            except (ValueError, UnicodeEncodeError) as exc:
                self._key_error = f"invalid AI_SERIAL_LOG_KEY: {exc}"
        self._queue: queue.Queue[tuple[str, dict] | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._available = False
        self._last_error = ""
        self._dropped = 0
        self._lock = threading.Lock()
        self._io_lock = threading.RLock()
        self._sessions: dict[str, str] = {}

    @property
    def dropped_records(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def available(self) -> bool:
        return self._available

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def encrypted(self) -> bool:
        return self._fernet is not None

    @staticmethod
    def safe_port(port: str) -> str:
        value = _SAFE_PORT.sub("_", port.strip())[:128]
        return value or "unknown"

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        if self._key_error:
            self._available = False
            self._last_error = self._key_error
            return False
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._available = False
            self._last_error = str(exc)
            return False
        self._available = True
        self._last_error = ""
        self._running.set()
        if self.retention_days:
            self.purge_older_than(self.retention_days)
        self._thread = threading.Thread(target=self._worker, name="serial-log-writer", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 3.0) -> None:
        if self._thread is None:
            return
        self._running.clear()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        self._thread = None
        self._available = False

    def record_message(self, port: str, message: SerialMessage) -> None:
        safe = self.safe_port(port)
        if message.event_code == "port.opened" or safe not in self._sessions:
            self._sessions[safe] = f"{int(message.timestamp * 1000)}-{safe}"
        record = {
            "kind": "message",
            "port": port,
            "source": message.source.value,
            "content": message.content,
            "raw_hex": message.raw_bytes.hex() if message.raw_bytes else "",
            "sequence": message.sequence,
            "event_code": message.event_code,
            "event_params": message.event_params,
            "timestamp": message.timestamp,
            "session_id": self._sessions[safe],
        }
        self._enqueue(port, record)
        if message.event_code == "port.closed":
            self._sessions.pop(safe, None)

    def record_raw(self, port: str, chunk: SerialRawChunk) -> None:
        safe = self.safe_port(port)
        session_id = self._sessions.setdefault(safe, f"{int(chunk.timestamp * 1000)}-{safe}")
        self._enqueue(port, {
            "kind": "raw",
            "port": port,
            "raw_hex": chunk.data.hex(),
            "sequence": chunk.sequence,
            "timestamp": chunk.timestamp,
            "session_id": session_id,
        })

    def _enqueue(self, port: str, record: dict) -> None:
        if not self._running.is_set():
            return
        try:
            self._queue.put_nowait((self.safe_port(port), record))
        except queue.Full:
            with self._lock:
                self._dropped += 1

    def _worker(self) -> None:
        while self._running.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                continue
            port, record = item
            try:
                self._append(port, record)
            except OSError as exc:
                self._last_error = str(exc)
            finally:
                self._queue.task_done()

    def _append(self, port: str, record: dict) -> None:
        with self._io_lock:
            path = self.root / f"{port}.jsonl"
            encoded = encode_log_line(record, self._fernet)
            if path.exists() and path.stat().st_size + len(encoded) > self.max_bytes:
                self._rotate(path)
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()

    def _rotate(self, path: Path) -> None:
        oldest = path.with_suffix(path.suffix + f".{self.backups}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backups - 1, 0, -1):
            source = path.with_suffix(path.suffix + f".{index}")
            if source.exists():
                source.replace(path.with_suffix(path.suffix + f".{index + 1}"))
        if path.exists():
            path.replace(path.with_suffix(path.suffix + ".1"))

    def list_ports(self) -> list[dict]:
        with self._io_lock:
            if not self.root.exists():
                return []
            result = []
            for path in sorted(self.root.glob("*.jsonl")):
                stat = path.stat()
                result.append({
                    "port": path.stem,
                    "size": stat.st_size,
                    "updated_at": stat.st_mtime,
                })
            return result

    def _decode_line(self, line: bytes) -> dict | None:
        try:
            return decode_log_line(line, self._fernet)
        except LogMigrationError:
            return None

    def _records(self, port: str) -> list[dict]:
        safe = self.safe_port(port)
        paths = [self.root / f"{safe}.jsonl"]
        paths.extend(self.root / f"{safe}.jsonl.{index}" for index in range(1, self.backups + 1))
        records: list[dict] = []
        for path in reversed(paths):
            if not path.is_file():
                continue
            for line in path.read_bytes().splitlines():
                record = self._decode_line(line)
                if record is not None:
                    records.append(record)
        return records

    def query(
        self,
        port: str,
        limit: int = 1000,
        search: str = "",
        kind: str = "",
        session_id: str = "",
    ) -> list[dict]:
        with self._io_lock:
            records: list[dict] = []
            needle = search.casefold()
            for record in self._records(port):
                if kind and record.get("kind") != kind:
                    continue
                if session_id and record.get("session_id") != session_id:
                    continue
                if needle:
                    searchable = json.dumps(record, ensure_ascii=False, separators=(",", ":")).casefold()
                    if needle not in searchable:
                        continue
                records.append(record)
            return records[-max(1, min(int(limit), 10000)):]

    def list_sessions(self, port: str) -> list[dict]:
        with self._io_lock:
            records = self._records(port)
        sessions: dict[str, dict] = {}
        for record in records:
            session_id = record.get("session_id")
            if not session_id:
                continue
            session = sessions.setdefault(session_id, {
                "session_id": session_id,
                "started_at": record.get("timestamp", 0),
                "ended_at": record.get("timestamp", 0),
                "records": 0,
            })
            session["started_at"] = min(session["started_at"], record.get("timestamp", 0))
            session["ended_at"] = max(session["ended_at"], record.get("timestamp", 0))
            session["records"] += 1
        return sorted(sessions.values(), key=lambda item: item["started_at"], reverse=True)

    def page_sessions(self, port: str, offset: int = 0, limit: int = 50) -> dict:
        sessions = self.list_sessions(port)
        safe_offset = max(int(offset), 0)
        safe_limit = max(1, min(int(limit), 200))
        return {
            "items": sessions[safe_offset:safe_offset + safe_limit],
            "total": len(sessions),
            "offset": safe_offset,
            "limit": safe_limit,
        }

    def purge_older_than(self, days: int) -> int:
        cutoff = time.time() - max(int(days), 0) * 86400
        removed = 0
        with self._io_lock:
            if not self.root.exists() or days <= 0:
                return 0
            for path in self.root.glob("*.jsonl*"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
        return removed

    def clear(self, port: str) -> int:
        with self._io_lock:
            safe = self.safe_port(port)
            removed = 0
            for path in [self.root / f"{safe}.jsonl", *(
                self.root / f"{safe}.jsonl.{index}" for index in range(1, self.backups + 1)
            )]:
                if path.exists():
                    path.unlink()
                    removed += 1
            return removed


serial_logs = SerialLogStore(
    max_bytes=int(os.environ.get("AI_SERIAL_LOG_MAX_BYTES", 10 * 1024 * 1024)),
    backups=int(os.environ.get("AI_SERIAL_LOG_BACKUPS", 5)),
    retention_days=int(os.environ.get("AI_SERIAL_LOG_RETENTION_DAYS", 0)),
    encryption_key=os.environ.get("AI_SERIAL_LOG_KEY", ""),
)
