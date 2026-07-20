# Engineering Roadmap

## Completed Hardening

- WebSocket Origin validation and HttpOnly browser sessions
- Removal of token disclosure from `/api/config`
- Validated WebSocket commands and UTF-8/base64 raw writes
- Acknowledged, bounded, cancellable file transfer
- Non-blocking API/WS serial operations and bounded event broadcast queue
- Serial write timeout, bounded read buffer, disconnect state handling, and message sequence IDs
- Safe managed-process shutdown and CI for backend/frontend
- MCP parameter validation and sequence-based response correlation
- Per-port single-writer leases with read-only Web UI/MCP observers
- Lossless raw-byte receive history alongside line-oriented terminal messages
- Structured event codes localized independently by Web UI and MCP
- Full serial framing, flow control, DTR, and RTS settings
- Extracted lease-aware `TerminalToolbar`
- Rotating, searchable persistent JSONL logs with exact raw-byte records
- XMODEM, XMODEM-1K, and YMODEM senders with CRC/checksum negotiation, retries, progress, and cancellation
- Hardware-ID keyed serial setting profiles in the Web UI
- Named profiles with opt-in HWID reconnect and bounded backoff
- XMODEM/YMODEM receive with Web and MCP downloads
- Log session queries and opt-in retention cleanup
- Multi-file YMODEM batch receive with bounded ZIP archives and SHA-256 manifests
- MCP batch extraction with path, size, overwrite, and hash verification
- Optional Fernet-encrypted rotating logs
- Paginated Web UI session log browser
- Vitest coverage, Playwright E2E, and extracted xterm lifecycle
- Device health rules, bounded command macros, scheduled diagnostics, and localized Web UI automation console
- Offline encrypted-log migration and Fernet key rotation with dry-run, backups, and rollback
- Authenticated COM17 @ 115200 read-only hardware automation verification

## Next Priorities

1. Expand hardware-backed E2E coverage for authenticated serial, leases, and batch transfers.
2. Add CI coverage for offline log migration on Windows and Linux.
3. Review automation definitions and diagnostic schedules with device-specific operators before enabling them in production.
