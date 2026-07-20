# Security Policy

## Deployment Boundary

AI Serial Bridge controls physical hardware. Keep the backend bound to `127.0.0.1` unless remote access is explicitly required. Remote deployments must use a TLS reverse proxy, a strong `AI_SERIAL_TOKEN`, firewall restrictions, and an explicit `CORS_ORIGINS` allowlist.

## Authentication Model

- MCP clients send `AI_SERIAL_TOKEN` as a Bearer credential.
- Browsers exchange the master token at `POST /api/session` for a short-lived HttpOnly, SameSite session cookie.
- `/api/config` exposes only whether authentication is required; it never returns a token.
- Browser WebSocket upgrades validate `Origin` and authenticate with the session cookie.
- Desktop mode generates a random token per launch unless the user supplies one.

Do not place tokens in query strings. For browser bootstrap, use the URL fragment form `http://localhost:5173/#token=<token>`; fragments are removed after session creation and are not sent in HTTP requests.
External MCP clients cannot reuse the random desktop-only token. Set `AI_SERIAL_TOKEN` explicitly before launching `desktop.py` and provide the same value to the MCP process. If an HTTP proxy intercepts loopback requests, set `NO_PROXY=127.0.0.1,localhost` for the backend and MCP process rather than disabling authentication.

## Operational Safety

`manager.py stop` only terminates PIDs recorded by this repository and verified against their expected command. It does not kill arbitrary processes occupying ports 8000 or 5173.

File transfers are limited to 32 MiB per file and 8 KiB server-side chunks. YMODEM batches are limited to 64 files and 64 MiB total. Batch downloads contain SHA-256 hashes in `manifest.json`; the MCP tool validates names, sizes, paths, and hashes before writing. These controls reduce accidental flooding but are not a substitute for device-specific transfer protocols.

Each open port has one renewable writer lease. Other Web UI or MCP clients remain read-only observers until the lease is released or expires. Clients must use a stable `X-AI-Serial-Client` identity; do not share one identity between unrelated processes to bypass lease conflicts.

Protocol transfers hold the port exclusively and reject normal writes until completion or cancellation. XMODEM/YMODEM does not authenticate firmware; verify hashes and device targets before sending files.

Persistent logs may contain credentials, console output, or proprietary device data. They default to `~/.ai-serial-bridge/logs`, rotate by size, and remain protected by the API authentication boundary. Set `AI_SERIAL_LOG_DIR`, `AI_SERIAL_LOG_MAX_BYTES`, and `AI_SERIAL_LOG_BACKUPS` to match local retention policy, and clear logs before sharing diagnostics.
Set `AI_SERIAL_LOG_RETENTION_DAYS` to a positive value for startup cleanup; `0` preserves logs until explicitly removed.

Set `AI_SERIAL_LOG_KEY` to a Fernet key to encrypt newly written records at rest. An invalid configured key disables persistent logging instead of falling back to plaintext. Store the key outside the repository with restricted permissions and a backup; key loss makes encrypted records unrecoverable. Enabling encryption does not retroactively encrypt existing plaintext files.

To migrate existing plaintext logs or rotate a key, stop the backend and run `python scripts/rotate_log_key.py --dry-run` first. Set the destination key only in `AI_SERIAL_LOG_KEY`; for rotation, set the previous key in `AI_SERIAL_LOG_OLD_KEY`. The command validates every JSONL record before atomically replacing files, keeps migration backups, and rolls back replacements after an error. It never accepts or prints key material.

The real-device smoke probe is intentionally bounded and read-only: `python scripts/test_hardware_automation.py --port COM17 --baudrate 115200` opens one lease, runs `uname -a`, verifies a health rule event, and releases the port. Review the target port before running it on any other device.

## Reporting

Report vulnerabilities privately to the repository maintainers. Include affected versions, reproduction steps, expected impact, and suggested mitigations. Avoid attaching real tokens, device credentials, or sensitive serial logs.
