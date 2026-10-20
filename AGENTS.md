# Repository Guidelines

## Project Structure & Module Organization

- `backend/` contains FastAPI, serial and lease management, automation, transfers, logs, and the stdio MCP proxy. Backend tests are in `backend/tests/`; use `fakeserial.py` when hardware is unnecessary.
- Supporting backend modules isolate deployment-sensitive logic: `frontend_assets.py` (bundle location across source/onefile/onedir), `serial_errors.py` (open-failure classification), `desktop_logging.py` (log and crash trail), `build_manifest.py` (content fingerprint), `port_config.py` (ports and bind address).
- `frontend/src/` contains Vue components, composables, translations, and shared styles.
- Root scripts manage services, desktop packaging, MCP smoke tests, hardware probes, and log migration. MCP client examples live in `mcp-config/`; documentation images live in `assets/`.
- Desktop entry points are `desktop.py` plus the `start_desktop.bat` / `start_desktop.ps1` launchers, which pin the project `.venv`.

## Build, Test, and Development Commands

```bash
python scripts/check_python_version.py  # verify interpreter is in range (3.10-3.14)
python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci
python manager.py start                 # backend + Vite
python -m pytest backend/tests          # backend tests
python scripts/smoke_test_mcp.py        # MCP connectivity
python scripts/test_hardware_automation.py --port <PORT> --baudrate 115200
cd frontend && npm test && npm run build && npm run test:e2e
python scripts/stamp_frontend_build.py  # record build fingerprint after frontend build
python desktop.py                       # or .\start_desktop.ps1
python -m pip install -r backend/requirements-build.txt && python -m PyInstaller ai-serial-bridge.spec
pwsh -File scripts/smoke_packaged_desktop.ps1   # packaged-build startup smoke test
```

Run commands from the repository root unless shown otherwise. Build `frontend/dist/` before desktop launch or packaging, then stamp its fingerprint. Use `python manager.py status` to inspect services and `python manager.py stop` when finished. Run `python scripts/rotate_log_key.py --dry-run` before any encrypted-log migration. Ports come from `backend/port_config.py`; override with `AI_SERIAL_PORT`, `AI_SERIAL_HOST`, `AI_SERIAL_FRONTEND_PORT`.

## Coding Style & Naming Conventions

Use Python 3.10+, four-space indentation, PEP 8 names, public API type hints, and focused docstrings. Vue uses TypeScript, `<script setup>`, Composition API, two-space indentation, single quotes, and no semicolons. Name components `PascalCase.vue`, composables `useThing.ts`, and Python tests `test_<behavior>.py`. Keep English and Chinese translation keys synchronized.

Keep script and launcher output free of encoding assumptions: Windows consoles may be cp1252/cp936, so `.py` scripts that print non-ASCII call `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`, `.bat` files stay pure ASCII (cmd.exe parses them in the OEM code page), and `.ps1` files are saved with a UTF-8 BOM.

## Testing Guidelines

Use pytest, Vitest, and Playwright. Add regression tests beside related suites and prefer `FakeSerial`/`monkeypatch` over COM hardware. Hardware scripts must be explicit and read-only unless a protocol loopback is documented. Frontend changes require a production build and checks for terminal input, tab synchronization, and console errors.

Run the backend suite with `frontend/dist` **absent** as well as present: a developer machine with a built bundle can mask failures that CI (which has no `dist`) will surface. CI runs three jobs — backend tests, frontend build/e2e, and a Windows `desktop-package` job that actually packages and launches the app.

## Commit & Pull Request Guidelines

Use scoped Conventional Commits such as `feat:`, `fix:`, `refactor:`, and `docs:`. PRs must explain motivation, link issues, list reproducible tests and platforms, and include screenshots for UI changes. Verify Web UI, MCP, port release, and multi-port behavior when relevant.

Changes under `.github/workflows/` require a token with the `workflow` scope; a token lacking it is rejected at push time with "refusing to allow a Personal Access Token to create or update workflow".

## Security & Configuration

Never commit tokens or machine-specific MCP paths. Default desktop/MCP pairing stores the token in `credentials.json`; `runtime.json` must remain token-free and owner-cleaned. `/api/config` may expose service and instance identity, never secrets. Explicit remote URLs must not reuse saved local credentials. Require TLS beyond loopback. Never print `AI_SERIAL_LOG_KEY`. Preserve batch receive limits: 32 MiB per file, 64 MiB per batch, and basename-only extraction. Stop the backend before offline log migration and pass keys only through environment variables.

Desktop runtime logs (`desktop.log`, `crash.log`, `fault.log` under `~/.ai-serial-bridge/logs/`) may contain device output; treat them like serial logs when sharing diagnostics. `crash.log` is created only by an actual unhandled exception, so its presence is itself a failure signal — do not create it speculatively.
