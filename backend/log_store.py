"""Bounded, rotating JSONL persistence for serial events and raw receive chunks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import threading
import time

from serial_manager import SerialMessage, SerialRawChunk


_SAFE_PORT = re.compile(r"[^A-Za-z0-9_.-]+")


class SerialLogStore:
    def __init__(
        self,
        root: Path | str | None = None,
        max_bytes: int = 10 * 1024 * 1024,
        backups: int = 5,
        queue_size: int = 5000,
        retention_days: int = 0,
    ):
        default_root = Path.home() / ".ai-serial-bridge" / "logs"
        self.root = Path(root or os.environ.get("AI_SERIAL_LOG_DIR") or default_root)
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.backups = min(max(int(backups), 1), 20)
        self.retention_days = max(int(retention_days), 0)
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

    @staticmethod
    def safe_port(port: str) -> str:
        value = _SAFE_PORT.sub("_", port.strip())[:128]
        return value or "unknown"

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
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
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            encoded = line.encode("utf-8")
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

    def query(
        self,
        port: str,
        limit: int = 1000,
        search: str = "",
        kind: str = "",
        session_id: str = "",
    ) -> list[dict]:
        with self._io_lock:
            safe = self.safe_port(port)
            paths = [self.root / f"{safe}.jsonl"]
            paths.extend(self.root / f"{safe}.jsonl.{index}" for index in range(1, self.backups + 1))
            records: list[dict] = []
            needle = search.casefold()
            for path in reversed(paths):
                if not path.is_file():
                    continue
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if kind and record.get("kind") != kind:
                        continue
                    if session_id and record.get("session_id") != session_id:
                        continue
                    if needle and needle not in line.casefold():
                        continue
                    records.append(record)
            return records[-max(1, min(int(limit), 10000)):]

    def list_sessions(self, port: str) -> list[dict]:
        records = self.query(port, limit=10000)
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
)
