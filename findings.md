# Findings & Decisions

## Requirements
- Finish every remaining priority in `ROADMAP.md`.
- Add device health rules, command macros, and scheduled diagnostics.
- Verify authenticated, lease-aware diagnostics on COM17 at 115200.
- Add encrypted log key rotation/migration without exposing keys.
- Maintain documentation and preserve user changes.

## Research Findings
- Phase 1-5 are committed at `d85db3b`.
- Main worktree contains a user-staged `.claude/settings.json` deletion; implementation is isolated on `codex/final-optimization`.
- Baseline service was down when this phase started.
- Previous verified baseline: 72 backend tests, 4 frontend tests, production build, 2 Edge E2E tests, and 14 MCP tools.
- Clean worktree baseline rerun: 72 backend tests and 4 frontend tests pass; npm audit reports 0 vulnerabilities.
- `serial_manager` exposes thread-safe global message callbacks `(port, SerialMessage)` and raw callbacks, so health evaluation can observe the existing decoded message stream without opening or rereading ports.
- `main.on_serial_message` already records logs before queueing WebSocket events. Health observation should be attached there or as a second global callback, while WebSocket broadcasting must remain on the event loop.
- FastAPI lifespan owns the event loop, bounded serial event queue, worker task, and shutdown cleanup; the automation scheduler belongs in the same lifecycle.
- `PortLeaseManager.ensure_writer` renews or acquires a 5-300 second single-writer lease and rejects other owners. Scheduled diagnostics need a stable internal owner and must skip, not steal, a conflicting lease.
- `serial_transfers.active_for_port` is the existing exclusivity check that must block macro/schedule writes during X/YMODEM operations.
- `SerialPortManager.write` is the correct command path and already records non-device writes; automation should inject/call it rather than touch pyserial directly.
- Persistent logs encode each record independently as plaintext JSON or `enc:v1:<Fernet token>`. Migration can reuse line-level decode/encode semantics and rewrite each rotated file independently.
- The current log decoder silently skips encrypted lines when no/mismatched key is configured. Offline migration must use strict decoding and fail before replacement if any line cannot be decrypted.
- REST APIs are protected centrally by auth middleware. New endpoints still need Pydantic bodies, strict identifiers, bounded arrays/strings, and `_client_identity` for writer ownership.
- MCP tools are declared in one `list_tools()` array and dispatched in one guarded `call_tool()` chain; new tools should proxy REST rather than duplicate automation logic.
- The Vue app already composes independent dialogs from `App.vue`. Automation state should live in a new composable and dialog, with only a visibility flag in `App.vue`.
- Vitest uses jsdom and includes `src/**/*.test.ts`; Playwright already mocks API routes, making deterministic automation UI E2E possible without hardware.
- The automation REST surface can use imported Pydantic definition models directly; path/body ID mismatches return 400 and schedule references prevent deleting active macros.
- Macro execution is synchronous from the caller perspective but runs in `asyncio.to_thread`, so the event loop remains responsive and cancellation can arrive concurrently.
- Scheduled diagnostics use owner `automation-scheduler`, mark due before execution, skip closed/busy/user-owned ports, and release only their own lease after completion.
- Health rules observe device messages only, preventing user/AI command echoes from generating false alerts; matched events are queued to WebSocket without blocking the serial reader thread.
- Macro definitions cap aggregate wait at 240 seconds, below the 300-second maximum lease window.
- Phase 3 is fully green with 91 backend tests; the next boundary is a composable-owned Vue automation console.
- MCP macro runs use a no-timeout HTTP request because valid macros may wait up to 240 seconds; cancellation remains a separate short authenticated request.
- The user supplied a real hardware target for final verification: COM17 at 115200.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Persist bounded JSON with atomic replacement | Human-readable recovery and standard-library operation. |
| Inject serial/lease functions into automation runtime | Testability and preservation of current ownership rules. |
| Keep migration keys in environment variables | Avoid process-list and API disclosure. |
| Separate automation definitions from runtime state | Definitions persist; transient runs/events remain bounded in memory and cannot corrupt config. |
| Scheduler ticks at 250-500 ms and computes due work | One bounded task is simpler and safer than one timer/thread per schedule. |
| Macros do not auto-open ports | Opening a physical device is explicit; scheduled runs skip closed ports and record the reason. |
| Macro execution uses a stable owner but never steals leases | API runs use the caller identity; schedules use an internal identity and skip conflicts. |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| No brainstorming skill is installed | Used the repository roadmap plus file-based planning. |
| Plan update patch used stale context | Re-read the current files and split the update into exact smaller patches. |

## Resources
- `docs/plans/2026-07-17-final-optimization.md`
- `backend/main.py`, `serial_manager.py`, `leases.py`, `log_store.py`, `mcp_server.py`
- `frontend/src/composables/useSerial.ts`
