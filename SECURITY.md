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

## Operational Safety

`manager.py stop` only terminates PIDs recorded by this repository and verified against their expected command. It does not kill arbitrary processes occupying ports 8000 or 5173.

File transfers are limited to 32 MiB and 8 KiB server-side chunks. Each chunk requires a sequence number and acknowledgement. These controls reduce accidental flooding but are not a substitute for device-specific transfer protocols.

Each open port has one renewable writer lease. Other Web UI or MCP clients remain read-only observers until the lease is released or expires. Clients must use a stable `X-AI-Serial-Client` identity; do not share one identity between unrelated processes to bypass lease conflicts.

Protocol transfers hold the port exclusively and reject normal writes until completion or cancellation. XMODEM/YMODEM does not authenticate firmware; verify hashes and device targets before sending files.

Persistent logs may contain credentials, console output, or proprietary device data. They default to `~/.ai-serial-bridge/logs`, rotate by size, and remain protected by the API authentication boundary. Set `AI_SERIAL_LOG_DIR`, `AI_SERIAL_LOG_MAX_BYTES`, and `AI_SERIAL_LOG_BACKUPS` to match local retention policy, and clear logs before sharing diagnostics.
Set `AI_SERIAL_LOG_RETENTION_DAYS` to a positive value for startup cleanup; `0` preserves logs until explicitly removed.

## Reporting

Report vulnerabilities privately to the repository maintainers. Include affected versions, reproduction steps, expected impact, and suggested mitigations. Avoid attaching real tokens, device credentials, or sensitive serial logs.
