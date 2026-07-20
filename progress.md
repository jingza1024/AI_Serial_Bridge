# Progress Log

## Session: 2026-07-20

### Phase 10: Python 3.10 CI Compatibility
- **Status:** in progress
- Evidence:
  - Backend CI exits during test collection at `backend/main.py:334`.
  - Frontend CI jobs pass.
  - Local runtime is Python 3.13; GitHub Actions is Python 3.10.
- Approved action:
  - Defer annotations in `backend/main.py`, verify on Python 3.10, and push a focused fix.
- Environment:
  - `uv` installed Python 3.10.20 successfully.
  - Full isolated dependency setup was blocked by repeated timeout downloading `pyserial` from the configured PyPI mirror; GitHub CI remains the full Python 3.10 verifier.
  - A second full attempt reached Windows-only `pywin32` and timed out; the focused environment then matched the failing API job without MCP platform dependencies.
- Fix:
  - Added `from __future__ import annotations` to `backend/main.py` without changing runtime behavior.
- Verification:
  - Python 3.10 annotation reproduction changed from the exact CI `TypeError` to deferred string annotations.
  - Python 3.10 `test_api.py`: 32 passed, one existing Starlette deprecation warning.
  - Local backend: 100 passed.
  - Frontend: 15 passed; production build passed; Playwright 3/3 passed.
- Publishing:
  - Two HTTPS push attempts reached GitHub but hit the configured 30-second low-speed threshold; retrying through a third official node without that threshold.

### Phase 9: Serial Reopen Receive Regression
- **Status:** complete
- Evidence:
  - COM17 at 115200 works on first desktop connection.
  - After close/reopen, writes still reach the Linux device but receive output is not shown.
  - A second serial terminal reveals the queued command output, isolating the first investigation to read delivery/UI subscription lifecycle.
- Root cause:
  - Reopened backend sessions restart per-port sequence numbers while Vue retained old session caches and dropped reused sequence values as duplicates.
- Fix:
  - Clear per-port transient caches when the authoritative `open_ports` update confirms closure, while preserving persistent server-side history.
- Verification:
  - Focused lifecycle tests: 3 passed.
  - Full frontend: 15 tests passed, production build passed, Playwright 3/3 passed.
  - Backend: 100 tests passed.
  - COM17@115200 authenticated hardware probe passed and released the port.

### Phase 8: Release Documentation and Publishing
- **Status:** complete
- Actions:
  - Added source-install prerequisites and separate Web, MCP, desktop, and contributor profiles.
  - Documented desktop frontend build requirements, MCP token sharing, and loopback proxy exclusions.
  - Updated English/Chinese MCP inventories to all 19 tools and refreshed project trees.
  - Corrected contributor working-directory and test commands.
  - Added `automations` and `regex` to explicit PyInstaller hidden imports.
- Verification:
  - Python dependency dry-run and `npm ci --dry-run` pass.
  - Backend: 100 tests pass; frontend: 13 tests pass.
  - Production build and Playwright 3/3 pass.
  - Dependency audit reports 0 vulnerabilities.

## Session: 2026-07-17

### Phase 1: Architecture Discovery
- **Status:** complete
- Actions:
  - Loaded planning, execution, worktree, and TDD workflows.
  - Created `codex/final-optimization` in a global isolated worktree.
  - Established the remaining roadmap as final scope.
  - Installed frontend dependencies; audit found 0 vulnerabilities.
  - Verified clean baseline: 72 backend and 4 frontend tests pass.
  - Located serial callback, FastAPI lifespan, lease, transfer, and write integration points.
  - Mapped log encryption, API/MCP extension patterns, and Vue dialog/composable boundaries.
  - Chose bounded JSON definitions, one scheduler task, explicit port opening, and non-stealing leases.
- Files:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`
  - `docs/plans/2026-07-17-final-optimization.md`

## Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Backend baseline | 72 tests pass | 72 passed | pass |
| Frontend baseline | 4 tests pass | 4 passed | pass |
| Dependency audit | 0 vulnerabilities | 0 vulnerabilities | pass |

### Phase 2: Automation Domain
- **Status:** complete
- Actions:
  - Defined the first TDD slice: persisted macros, health rules, and schedules.
  - Implemented atomic JSON persistence, definition bounds, regex validation, health cooldown/history, macro execution/cancellation/output, and schedule planning/status.
  - Integrated REST CRUD, caller-owned macro runs, health observation, and non-stealing scheduled diagnostics.
- Files:
  - `backend/tests/test_automations.py` (next)
  - `backend/automations.py` (after RED)
  - `backend/main.py`
  - `backend/tests/test_api.py`

### Phase 3: API and MCP Integration
- **Status:** complete
- Actions:
  - REST and lifespan portion is GREEN: 38 focused automation/API tests pass.
  - Added automation REST CRUD, run/cancel/history/health endpoints, scheduler lifecycle, and 5 MCP tools.
  - Full backend suite passes: 91 tests.

### Phase 4: Web UI
- **Status:** complete
- Actions:
  - Added tested automation composable, macro/health/schedule panels, and the localized automation dialog.
  - Integrated the automation entry into the application shell.
  - Added API-mocked Playwright coverage for opening, navigating, and closing the console.

### Phase 5: Encrypted Log Migration
- **Status:** complete
- Actions:
  - Added strict shared JSONL decode/encode helpers.
  - Added plaintext-to-encrypted migration and old-to-new Fernet key rotation.
  - Added dry-run, full pre-validation, atomic replacement, persistent backups, and rollback on failure.
  - Added an offline CLI that reads keys only from environment variables.
- Verification:
  - 10 focused log store and migration tests pass.
  - Automation Playwright flow passes.

### Phase 6: Hardware Verification
- **Status:** complete
- Target: COM17 at 115200 baud, Linux, non-destructive commands only.
- Result:
  - Authenticated loopback backend started with isolated temporary logs and automation definitions.
  - MCP stdio opened COM17 at 115200 and its lease label was verified.
  - One `uname -a` macro step completed through MCP and triggered the Linux health rule read through MCP.
  - MCP closed the port; a REST status check confirmed it was released.

### Phase 7: Final Verification and Delivery
- **Status:** complete
- Actions:
  - Updated AGENTS, README, README.zh-CN, SECURITY, ROADMAP, and planning records.
  - Addressed independent review findings: macro/transfer mutual exclusion, regex timeouts, scheduler exception isolation, real control-character newlines, and reachable macro cancellation.
- Verification:
  - Backend: 100 tests pass.
  - Frontend: 13 tests pass.
  - Production Vue build passes.
  - Playwright app-shell suite: 3 tests pass.
  - Dependency audit: 0 vulnerabilities.
  - Authenticated MCP hardware probe on COM17 @ 115200 passes and releases the port.

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-07-17 | No worktree directory preference | 1 | Used global worktree path. |
| 2026-07-17 | `ModuleNotFoundError: automations` | 1 | Expected RED result before creating the production module. |
| 2026-07-17 | `ImportError: HealthMonitor` | 1 | Expected RED result before implementing health evaluation. |
| 2026-07-17 | `ImportError: MacroRuntime` | 1 | Expected RED result before implementing macro execution and planning. |
| 2026-07-17 | Automation API globals/routes missing | 1 | Expected RED result before REST integration. |
| 2026-07-17 | Scheduler/health lifecycle behaviors missing | 1 | Expected RED result before lifecycle integration. |
| 2026-07-17 | MCP automation tools unknown | 1 | Expected RED result before MCP registration and proxy implementation. |
| 2026-07-17 | Planning patch context mismatch | 1 | Re-read actual files and used smaller exact-context patches. |
| 2026-07-17 | Backend test path missing from frontend workdir | 1 | Run backend verification from worktree root. |
| 2026-07-17 | `useAutomations` import missing | 1 | Expected RED result before composable implementation. |
| 2026-07-17 | Automation panel imports missing | 1 | Expected RED result before panel implementation. |

## Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 4 Web UI |
| Where am I going? | Automation, integrations, UI, migration, hardware, delivery |
| What's the goal? | Finish the remaining roadmap safely |
| What have I learned? | See `findings.md` |
| What have I done? | See this log |
