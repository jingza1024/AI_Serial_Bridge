# Repository Guidelines

## Project Structure & Module Organization

- `backend/` contains the FastAPI service, serial/lease management, rotating logs, transfer protocols, and stdio MCP proxy. Tests live in `backend/tests/`; `fakeserial.py` avoids physical hardware dependencies.
- `frontend/src/` is the Vue 3 client: reusable state in `composables/`, UI in `components/`, translations in `locales/`, and shared CSS in `styles/`.
- Root scripts coordinate services, pywebview, and PyInstaller.
- `mcp-config/` holds client examples; `assets/` holds documentation images. Do not commit `frontend/dist/`, `node_modules/`, logs, or virtual environments.

## Build, Test, and Development Commands

```bash
pip install -r backend/requirements.txt
pip install -r backend/requirements-mcp.txt
pip install -r backend/requirements-dev.txt
cd frontend && npm install
python manager.py start                 # backend + Vite development server
python manager.py status                # report managed service state
python -m pytest backend/tests          # run backend regression tests
python scripts/smoke_test_mcp.py        # verify MCP tools and connectivity
python scripts/test_linux_serial_mcp.py # run a read-only Linux console probe
python scripts/test_xmodem_mcp_loopback.py # verify MCP XMODEM over COM4/COM5
cd frontend && npm run build            # type-check and build frontend/dist
cd frontend && npm test                 # run Vitest tests
cd frontend && npm run test:e2e         # run Playwright tests
python desktop.py                       # run the desktop shell in development
pyinstaller ai-serial-bridge.spec       # create the desktop distribution
```

Run `python manager.py stop` when finished.

## Coding Style & Naming Conventions

Use Python 3.10+, four-space indentation, PEP 8 naming, public API type hints, and focused docstrings. Avoid emoji in Python console output.

Vue code uses TypeScript, `<script setup>`, Composition API, two-space indentation, single quotes, and no semicolons. Name components `PascalCase.vue`, composables `useThing.ts`, and tests `test_<behavior>.py`. Keep English and Chinese translation keys synchronized.

## Testing Guidelines

Pytest is the automated framework. Add regression tests beside related suites and use `FakeSerial`/`monkeypatch` instead of COM hardware. Prioritize APIs, parsing, thread lifecycle, WebSocket actions, and localization. Frontend changes require `npm run build` plus manual checks for terminal input, tab synchronization, and console errors.

## Commit & Pull Request Guidelines

History follows Conventional Commits: `feat:`, `fix:`, `refactor:`, or `docs:`. Keep commits scoped. In PRs, explain motivation, link issues, list reproducible tests and platforms, and include UI screenshots. Verify Web UI, MCP, port release, and multi-port behavior when relevant.

## Security & Configuration

Never commit tokens or machine-specific MCP paths. `/api/config` must not return secrets. Browsers use an HttpOnly session created from `AI_SERIAL_TOKEN`; MCP uses a Bearer credential. Keep origins narrow and require TLS beyond loopback.
Treat `AI_SERIAL_LOG_KEY` as a secret; never print or commit it. Batch receive changes must preserve the 32 MiB/file, 64 MiB/batch, and basename-only extraction limits.
