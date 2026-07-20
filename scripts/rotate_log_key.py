"""Offline plaintext migration and Fernet key rotation for persistent logs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from log_store import LogMigrationError, migrate_log_directory  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encrypt plaintext serial logs or rotate their Fernet key offline.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(os.environ.get("AI_SERIAL_LOG_DIR") or Path.home() / ".ai-serial-bridge" / "logs"),
        help="Persistent log directory (defaults to AI_SERIAL_LOG_DIR).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate every record and report changes without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    new_key = os.environ.get("AI_SERIAL_LOG_KEY", "")
    old_key = os.environ.get("AI_SERIAL_LOG_OLD_KEY", "") or None
    if not new_key:
        print("AI_SERIAL_LOG_KEY must contain the destination Fernet key.", file=sys.stderr)
        return 2
    try:
        result = migrate_log_directory(
            args.log_dir,
            old_key=old_key,
            new_key=new_key,
            dry_run=args.dry_run,
        )
    except LogMigrationError as exc:
        print(f"Log migration failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
