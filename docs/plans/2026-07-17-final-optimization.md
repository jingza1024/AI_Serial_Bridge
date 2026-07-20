# Final Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Finish the roadmap with safe device automation, offline encrypted-log migration, COM17 verification, documentation, and a verified commit.

**Architecture:** Add a bounded JSON-backed automation domain that observes existing serial messages and runs macros/schedules only through current serial, lease, and transfer guards. Add REST, MCP, and Vue surfaces. Keep key rotation in an offline atomic CLI.

**Tech Stack:** Python, FastAPI, Pydantic, pyserial, pytest, MCP, Vue 3, TypeScript, Vitest, Playwright, Fernet.

---

### Task 1: Discover Integration Boundaries
Read serial callbacks, lease guards, lifespan hooks, logging, MCP, and Vue state ownership. Record exact integration points in `findings.md`.

### Task 2: Automation Domain with TDD
Create `backend/automations.py` and `backend/tests/test_automations.py`. RED/GREEN persistence, regex health rules with cooldown, bounded history, sequential macro execution, cancellation, output capture, and interval scheduling.

### Task 3: REST and Lifespan with TDD
Modify `backend/main.py` and `backend/tests/test_api.py`. RED/GREEN CRUD, run/cancel/status/health endpoints; lifecycle startup/shutdown; lease and active-transfer enforcement.

### Task 4: MCP with TDD
Modify `backend/mcp_server.py` and `backend/tests/test_mcp_server.py`. RED/GREEN list/run macro, health, schedule status tools.

### Task 5: Vue Console with TDD
Create `useAutomations.ts`, tests, `AutomationDialog.vue`, and `HealthStatusPanel.vue`; integrate `App.vue`, synchronized locales, and Playwright API-mocked coverage. Load Vue skills before edits.

### Task 6: Offline Log Migration with TDD
Modify `backend/log_store.py`; create `scripts/rotate_log_key.py` and `backend/tests/test_log_migration.py`. RED/GREEN plaintext migration, old/new key rotation, wrong-key rejection, dry-run, atomic replacement, and backups. Keys come only from environment variables.

### Task 7: COM17 Hardware Verification
Start authenticated service, open COM17 at 115200, run one bounded non-destructive Linux diagnostic, verify lease/health/macro/port release, and stop after one recovery attempt if only echo is returned.

### Task 8: Documentation, Full Verification, Commit
Update README files, ROADMAP, SECURITY, AGENTS, and planning records. Run all backend/frontend/build/E2E/MCP/hardware checks, audit diffs, and commit without `.claude/settings.json`.
