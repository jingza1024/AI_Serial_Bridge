# Final Optimization Task Plan

## Goal
Complete the remaining roadmap: device health rules, command macros, scheduled diagnostics, encrypted-log key migration, COM17 hardware verification, documentation, and a final verified commit.

## Current Phase
Phase 7: Final Verification and Delivery

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

## Notes
- Re-read this file before major decisions.
- Update after each phase and log every error.
