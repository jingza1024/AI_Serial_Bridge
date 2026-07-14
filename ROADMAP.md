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
- Vitest coverage, Playwright E2E, and extracted xterm lifecycle

## Next Priorities

1. Add multi-file YMODEM batch receive and transfer manifests with hashes.
2. Add encrypted-at-rest logs and a paginated session browser.
3. Add device health rules, command macros, and scheduled diagnostics.
4. Expand E2E coverage to authenticated serial, lease, and transfer flows.
