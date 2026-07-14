"""Persistent serial log rotation and query tests."""

from pathlib import Path
import shutil
import uuid

import pytest

from log_store import SerialLogStore
from serial_manager import MessageSource, SerialMessage, SerialRawChunk


@pytest.fixture
def log_dir():
    base = Path.cwd() / ".test-artifacts"
    path = base / f"logs-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    if path.resolve().parent == base.resolve():
        shutil.rmtree(path, ignore_errors=True)


def test_log_store_persists_message_and_exact_raw_chunk(log_dir):
    store = SerialLogStore(log_dir, max_bytes=64 * 1024)
    store.start()
    store.record_message("COM/14", SerialMessage(
        source=MessageSource.DEVICE,
        content="Linux\r\n",
        timestamp=1.5,
        raw_bytes=b"Linux\r\n",
        sequence=7,
    ))
    store.record_raw("COM/14", SerialRawChunk(data=b"\x00\xff\r\n", timestamp=2.0, sequence=3))
    store.stop()

    records = store.query("COM/14", limit=10)
    assert [record["kind"] for record in records] == ["message", "raw"]
    assert records[1]["raw_hex"] == "00ff0d0a"
    assert store.list_ports()[0]["port"] == "COM_14"
    sessions = store.list_sessions("COM/14")
    assert len(sessions) == 1
    assert sessions[0]["records"] == 2


def test_log_store_rotates_and_searches(log_dir):
    store = SerialLogStore(log_dir, max_bytes=64 * 1024, backups=2)
    store.start()
    for sequence in range(800):
        store.record_message("COM14", SerialMessage(
            source=MessageSource.DEVICE,
            content=f"line-{sequence}-" + "x" * 100,
            timestamp=float(sequence),
            sequence=sequence,
        ))
    store.stop(timeout=5)

    assert (log_dir / "COM14.jsonl.1").exists()
    matches = store.query("COM14", limit=10, search="line-799", kind="message")
    assert len(matches) == 1
    assert matches[0]["sequence"] == 799
