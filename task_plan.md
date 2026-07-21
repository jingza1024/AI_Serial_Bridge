# Final Optimization Task Plan

## Goal
Complete the remaining roadmap: device health rules, command macros, scheduled diagnostics, encrypted-log key migration, COM17 hardware verification, documentation, and a final verified commit.

## Current Phase
Phase 12: Zero-config local MCP pairing (complete)

## Phases

### Phase 1: Architecture Discovery
- [x] Map serial callbacks, leases, persistence, API, MCP, and Vue boundaries.
- [x] Define bounded automation contracts and hardware-safe behavior.
- **Status:** complete

### Phase 2: Automation Domain
- [x] RED/GREEN tests for persistence, rules, macros, cancellation, and schedules.
- [x] Implement the persistent automation store and runtime engine.
- **Status:** complete

### Phase 3: API and MCP Integration
- [x] RED/GREEN API and MCP tests.
- [x] Add CRUD, run, cancel, status, and health surfaces with lease guards.
- **Status:** complete

### Phase 4: Web UI
- [x] Load Vue skills and write failing composable/component tests.
- [x] Add the localized automation console and E2E coverage.
- **Status:** complete

### Phase 5: Encrypted Log Migration
- [x] RED/GREEN tests for plaintext migration, key rotation, dry-run, and rollback.
- [x] Add an offline atomic migration CLI.
- **Status:** complete

### Phase 6: Hardware Verification
- [x] Start the authenticated service and test COM17 at 115200 non-destructively.
- [x] Verify lease, diagnostic macro, health observation, and port release.
- **Status:** complete

### Phase 7: Final Verification and Delivery
- [x] Run full backend/frontend/build/E2E/MCP/hardware verification.
- [x] Update all contributor/security/roadmap documentation.
- [x] Commit without touching `.claude/settings.json`.
- **Status:** complete

### Phase 8: Release Documentation and Publishing
- [x] Audit source, MCP, desktop, and contributor installation instructions.
- [x] Synchronize the 19-tool MCP inventory and current project structure.
- [x] Verify dependency resolution, backend/frontend tests, build, E2E, and audit.
- [x] Prepare the verified documentation corrections and confirm the remote target branch.
- **Status:** complete

### Phase 9: Serial Reopen Receive Regression
- [x] Trace close/reopen across serial reader threads, WebSocket events, and Vue terminal subscriptions.
- [x] Add failing regression tests that reproduce missing receive data after reopen.
- [x] Implement the smallest lifecycle fix and verify COM17 at 115200.
- [x] Update regression documentation and run final verification.
- **Status:** complete

### Phase 10: Python 3.10 CI Compatibility
- [x] Reproduce the backend import failure under Python 3.10.
- [x] Defer runtime annotation evaluation in `backend/main.py`.
- [x] Run Python 3.10 and full local verification.
- [x] Commit, push, and confirm green CI.
- **Status:** complete

### Phase 11: Desktop serial reopen interaction
- [x] Reproduce the same-process COM18 close/reopen flow at 115200.
- [x] Confirm the stale desktop bundle and Linux Enter newline mismatch.
- [x] Add regression coverage for interactive newline normalization and stale builds.
- [x] Rebuild the desktop frontend and verify COM18 after close/reopen.
- [x] Run the full verification suite and update documentation.
- **Status:** complete

### Phase 12: Zero-config local MCP pairing
- [x] Add a user-scoped persistent credential store with atomic writes and safe permissions.
- [x] Add a runtime manifest for the active desktop API URL and process identity.
- [x] Make MCP discover credentials and endpoint dynamically with bounded retries.
- [x] Preserve explicit environment-variable overrides and reject stale/malformed runtime state safely.
- [x] Add integration tests, migrate documentation/examples, and verify desktop-visible MCP calls.
- **Status:** complete

## Key Decisions
| Decision | Rationale |
|----------|-----------|
| Global isolated worktree | Required by execution workflow and isolates the user-staged deletion. |
| JSON-backed automation definitions | Bounded, recoverable, and no database dependency. |
| Existing serial/lease managers remain authoritative | Scheduled work must not bypass writer or transfer ownership. |
| Offline log migration only | Encryption keys must never cross HTTP or WebSocket APIs. |
| COM17 diagnostics are read-only | Protect the attached Linux device. |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| No project worktree preference | 1 | Used the safe global worktree location. |
| `ModuleNotFoundError: automations` in first RED test | 1 | Expected missing-feature failure; implement the minimal module next. |
| `ImportError: HealthMonitor` in health RED test | 1 | Expected missing-feature failure; implement evaluator and regex validation. |
| `ImportError: MacroRuntime` in runtime RED test | 1 | Expected missing-feature failure; implement runtime and planner. |
| Four automation API RED failures | 1 | Expected missing globals/routes; implement CRUD, run guards, and health endpoint. |
| Five scheduler/health lifecycle RED failures | 1 | Expected missing wait bound, status, observation, and due-run function. |
| Three MCP automation RED failures | 1 | Expected missing tool registrations and dispatch branches. |
| Planning patch context mismatch | 1 | Re-read current files and applied smaller exact-context patches. |
| Backend test path not found from `frontend/` | 1 | Wrong working directory; keep backend and frontend verification commands separate. |
| Vue import resolution failed for `useAutomations` | 1 | Expected RED result before creating the composable. |
| Automation panel imports missing | 1 | Expected RED result before creating the three Vue components. |
| MCP hardware probe returned HTTP 502 | 1 | Forced the child MCP process to bypass environment proxies for loopback requests. |
| MCP lease test expected internal owner ID | 1 | Verified the public owner label returned by the MCP tool instead. |
| Pathological regex blocked focused pytest | 1 | Added the `regex` engine with a 10 ms match timeout. |
| Desktop COM17 receives no visible output after close/reopen | 1 | Cleared per-port session caches when `open_ports` confirms closure so reset sequence numbers are accepted. |
| Python 3.10 CI cannot import `backend/main.py` | 1 | `threading.Lock` is a factory function before Python 3.13; defer annotation evaluation. |
| Python 3.10 uv dependency environment timed out downloading `pyserial` | 1 | Do not repeat mirror install; reproduce the annotation directly and use GitHub CI for the complete 3.10 environment. |
| Python 3.10 full MCP environment timed out downloading Windows `pywin32` | 1 | Switched to the exact failing API suite with backend dependencies and `httpx`; GitHub Ubuntu CI does not require `pywin32`. |
| Focused Python 3.10 API environment lacked `httpx` | 1 | Added the CI-equivalent `httpx>=0.27` dependency; 32 API tests passed. |
| Two GitHub Web nodes hit the 30-second Git low-speed threshold | 2 | Use a third official node without the aggressive threshold for the small push. |
| `ModuleNotFoundError: local_runtime` in Phase 12 RED tests | 1 | Expected missing-module failure; implement the shared runtime configuration layer next. |
| Pytest cache directory is not writable in the current workspace | 1 | Run focused and full tests with `-p no:cacheprovider`; test execution itself remains available. |
| Workspace `--basetemp` parent directory did not exist | 1 | Create `E:\\AI_Serial\\.test-tmp` before rerunning focused tests. |
| Pytest-created workspace temp directory became unreadable under the managed Windows sandbox | 2 | Rerun the focused pytest command with controlled escalation; do not treat setup errors as product failures. |
| Multi-file planning patch used an invalid update marker | 2 | Stop combining planning-file patches; apply one file per patch. |
| Desktop test patched the shared stdlib `secrets` module | 1 | Remove the global monkeypatch and assert the generated instance ID dynamically. |

## Notes
- Re-read this file before major decisions.
- Update after each phase and log every error.

