# Repository Guidelines

## Project Structure & Module Organization

- `backend/` contains FastAPI, serial and lease management, automation, transfers, logs, and the stdio MCP proxy. Backend tests are in `backend/tests/`; use `fakeserial.py` when hardware is unnecessary.
- `frontend/src/` contains Vue components, composables, translations, and shared styles.
- Root scripts manage services, desktop packaging, MCP smoke tests, hardware probes, and log migration. MCP client examples live in `mcp-config/`; documentation images live in `assets/`.

## Build, Test, and Development Commands

```bash
python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci
python manager.py start                 # backend + Vite
python -m pytest backend/tests          # backend tests
python scripts/smoke_test_mcp.py        # MCP connectivity
python scripts/test_hardware_automation.py --port <PORT> --baudrate 115200
cd frontend && npm test && npm run build && npm run test:e2e
python desktop.py
python -m PyInstaller ai-serial-bridge.spec
```

Run commands from the repository root unless shown otherwise. Build `frontend/dist/` before desktop launch or packaging. Use `python manager.py status` to inspect services and `python manager.py stop` when finished. Run `python scripts/rotate_log_key.py --dry-run` before any encrypted-log migration.

## Coding Style & Naming Conventions

Use Python 3.10+, four-space indentation, PEP 8 names, public API type hints, and focused docstrings. Vue uses TypeScript, `<script setup>`, Composition API, two-space indentation, single quotes, and no semicolons. Name components `PascalCase.vue`, composables `useThing.ts`, and Python tests `test_<behavior>.py`. Keep English and Chinese translation keys synchronized.

## Testing Guidelines

Use pytest, Vitest, and Playwright. Add regression tests beside related suites and prefer `FakeSerial`/`monkeypatch` over COM hardware. Hardware scripts must be explicit and read-only unless a protocol loopback is documented. Frontend changes require a production build and checks for terminal input, tab synchronization, and console errors.

## Commit & Pull Request Guidelines

Use scoped Conventional Commits such as `feat:`, `fix:`, `refactor:`, and `docs:`. PRs must explain motivation, link issues, list reproducible tests and platforms, and include screenshots for UI changes. Verify Web UI, MCP, port release, and multi-port behavior when relevant.

## Security & Configuration

Never commit tokens or machine-specific MCP paths. Default desktop/MCP pairing stores the token in `credentials.json`; `runtime.json` must remain token-free and owner-cleaned. `/api/config` may expose service and instance identity, never secrets. Explicit remote URLs must not reuse saved local credentials. Require TLS beyond loopback. Never print `AI_SERIAL_LOG_KEY`. Preserve batch receive limits: 32 MiB per file, 64 MiB per batch, and basename-only extraction. Stop the backend before offline log migration and pass keys only through environment variables.
