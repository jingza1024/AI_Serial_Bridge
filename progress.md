# Progress Log

## Session: 2026-07-21 (Phase 12 live MCP)

### Desktop + MCP zero-config live check
- **Status:** pass (non-hardware + shared history)
- Desktop runtime live: instance matched `/api/config`.
- MCP without `AI_SERIAL_TOKEN`/`AI_SERIAL_API_URL`:
  - `scripts/smoke_test_mcp.py`: 19 tools + `serial_list_ports` OK
  - `serial_is_open`/`serial_get_lease` on COM16/17/18 OK
  - `serial_list_macros` / schedules / health OK
  - `serial_get_history` on user-opened COM18 returned shared Linux shell session (`ls` listing visible)
- Hardware write probe later completed on COM18 after user authorization.

### COM18 live write/read (authorized)
- **Status:** pass
- Port left open for desktop user session; MCP released write lease.
- Commands: `printf MCP_OK`, `uname -a`, `echo CODEX_COM18_PROBE` all returned device output.
- Device: Linux ubuntu 5.15.185-tegra aarch64; shell `bliiot@ubuntu`.
- History source labeled as AI for MCP writes; visible in shared history.

## Session: 2026-07-21 (handoff resume)

### Resume from session 019f5e8c
- **Status:** backend verification complete; live desktop+MCP still pending
- Read start-here and full handoff for session `019f5e8c-0a58-7921-9d23-79ccb76b0bbc`.
- Branch: `codex/desktop-build-freshness` at `37ec1e8` with uncommitted Phase 11/12 work (local_runtime, desktop lock/generation, MCP discovery, serial input normalization, docs).
- Full backend suite (escalated, no cacheprovider): **139 passed** in 6.30s.
- Sandbox note: workspace basetemp under managed FS still hits `PermissionError` on cleanup; use escalated pytest or a writable basetemp.
- Do not re-implement lock/generation protocol unless a regression appears.
- Next: desktop GUI + MCP live pairing verification; then commit/docs polish and remote publish only with `gh` auth (never chat tokens).

## Session: 2026-07-21 (Phase 12)

### Phase 12: Zero-config local MCP pairing
- **Status:** in progress
- User-approved direction: running the desktop program should be sufficient for an Agent MCP client to connect without manually copying a token.
- Initial evidence: desktop used an ephemeral token while the configured MCP used a different fixed token; direct MCP calls returned HTTP 401, while an API call using the desktop token succeeded.
- Planned implementation: user-scoped credential storage, atomic runtime endpoint manifest, dynamic MCP config loading, bounded retry/error classification, compatibility overrides, and integration/documentation tests.
- Test environment note: the default pytest temp root is inaccessible, and the first workspace `--basetemp` retry failed because `.test-tmp` did not yet exist. Create the parent directory before rerunning; no Phase 12 test body executed in that attempt.
- The precreated-parent retry still failed during pytest temp cleanup with `PermissionError` on the generated base directory. This is a managed-sandbox filesystem issue; obtain the first real test result via a controlled unsandboxed pytest invocation.
- Focused runtime-state verification reached the test bodies: one valid explicit remote URL with a path prefix was over-rejected. The normalizer now permits paths only for explicit URLs; runtime manifests remain root-only. Result: 8 Phase 12 runtime tests passed.
- Desktop integration audit identified a manifest cleanup TOCTOU race and a stronger readiness requirement: publish only after `/api/config` reports this process's service and instance ID.
- Added RED/GREEN coverage for explicit remote isolation and concurrent manifest replacement. Remote targets no longer inspect local pairing files, and a shared manifest lock prevents an older desktop cleanup from deleting a newer instance's manifest. Focused result: 10 passed.
- Desktop startup now loads or creates the persistent token before importing the backend, sets a unique instance ID, verifies `/api/config` identity before publishing, and removes only its own manifest in `finally`. `/api/config` exposes only service, instance ID, and auth state. Combined Phase 12 runtime/desktop/API result: 18 passed.
- Later hardening (same day): generation-bound save-token, loopback proxy bypass, native OS desktop lock with two-phase byte locks (gate + active), generation at offset >= 64 for Windows msvcrt, real subprocess regression for cross-process generation reads. Focused Phase 12 suite historically 84 passed.

## Session: 2026-07-21

### Phase 11: Desktop serial reopen interaction
- **Status:** complete
- Reproduction:
  - The desktop process stayed open while COM18 at 115200 was opened, used, closed, and opened again.
  - Before the fix, xterm Enter sent CR; the Linux shell displayed `^M` and did not execute the command. A direct LF probe returned `CODEX_LF_OK`.
  - The previously published Vue session-cache fix was present in source but absent from the 2026-07-14 `frontend/dist` loaded by the desktop launcher.
- Fix:
  - Added interactive CR/CRLF/LF normalization with LF as the Linux-console default and a visible per-terminal selector.
  - Added a desktop development guard that refuses to serve `frontend/dist` when frontend inputs are newer than the bundle.
- Verification:
  - RED/GREEN utility tests cover CR, LF, CRLF, and unchanged input.
  - Rebuilt `frontend/dist` and verified the same-process COM18 flow: first `ls` worked, close/reopen completed, and second `ls` returned the Linux directory listing and prompt.
  - User manually repeated the close/reopen workflow and confirmed normal interaction.
  - Backend: 102 passed; frontend: 18 passed; production build passed; Playwright: 3/3 passed.

## Session: 2026-07-20

### Phase 10: Python 3.10 CI Compatibility
- **Status:** complete
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
  - Pushed `fb5caaa` to `codex/final-optimization` through a reachable official GitHub node.
  - GitHub Actions run `29721719293` completed successfully: backend and frontend jobs passed.

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
| Backend full (handoff 2026-07-21) | all pass | 139 passed | pass |

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
| 2026-07-21 | Sandboxed pytest basetemp PermissionError | 1 | Rerun full suite with escalated permissions; 139 passed. |

## Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 12 zero-config MCP pairing; backend suite green |
| Where am I going? | Desktop+MCP live pairing verify, then finalize Phase 12 and publish |
| What's the goal? | Desktop start alone is enough for Agent MCP pairing |
| What have I learned? | See `findings.md` |
| What have I done? | See this log |


