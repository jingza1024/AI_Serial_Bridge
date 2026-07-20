"""Persistent definitions for health rules, command macros, and diagnostics."""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
import secrets
import threading
import time
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import regex


AUTOMATION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
MAX_DEFINITIONS = 128
MAX_MACRO_OUTPUT = 64 * 1024


class MacroStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    command: str = Field(min_length=1, max_length=4096)
    newline: Literal["", "\r", "\n", "\r\n"] = "\r"
    wait_seconds: float = Field(default=1.0, ge=0, le=30)

    @field_validator("command")
    @classmethod
    def command_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must not be blank")
        return value


class MacroDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=AUTOMATION_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    steps: tuple[MacroStep, ...] = Field(min_length=1, max_length=32)
    enabled: bool = True

    @model_validator(mode="after")
    def total_wait_must_fit_lease_window(self):
        if sum(step.wait_seconds for step in self.steps) > 240:
            raise ValueError("macro total wait exceeds 240 seconds")
        return self


class HealthRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=AUTOMATION_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    pattern: str = Field(min_length=1, max_length=512)
    severity: Literal["info", "warning", "critical"] = "warning"
    message: str = Field(min_length=1, max_length=256)
    cooldown_seconds: float = Field(default=60, ge=0, le=86400)
    enabled: bool = True

    @field_validator("pattern")
    @classmethod
    def pattern_must_compile(cls, value: str) -> str:
        try:
            regex.compile(value)
        except regex.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return value


class DiagnosticSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=AUTOMATION_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    macro_id: str = Field(pattern=AUTOMATION_ID_PATTERN)
    port: str = Field(min_length=1, max_length=256)
    interval_seconds: float = Field(ge=5, le=604800)
    enabled: bool = False


class AutomationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[1] = 1
    macros: tuple[MacroDefinition, ...] = ()
    rules: tuple[HealthRule, ...] = ()
    schedules: tuple[DiagnosticSchedule, ...] = ()


class HealthEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    rule_id: str
    port: str
    severity: Literal["info", "warning", "critical"]
    message: str
    content: str
    timestamp: float


class MacroRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    macro_id: str
    port: str
    owner_id: str
    status: Literal["completed", "failed", "cancelled"]
    output: str = ""
    steps_completed: int = 0
    error: str = ""
    started_at: float
    finished_at: float


class ScheduleState(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule_id: str
    last_started: float = 0
    last_finished: float = 0
    last_status: Literal["idle", "running", "completed", "failed", "cancelled", "skipped"] = "idle"
    last_error: str = ""
    last_run_id: str = ""


class ActiveMacro:
    def __init__(self, run_id: str, port: str, owner_id: str):
        self.run_id = run_id
        self.port = port
        self.owner_id = owner_id
        self.cancel = threading.Event()


class AutomationStore:
    def __init__(self, path: Path | str | None = None):
        default_path = Path.home() / ".ai-serial-bridge" / "automations.json"
        self.path = Path(path or os.environ.get("AI_SERIAL_AUTOMATION_FILE") or default_path)
        self._lock = threading.RLock()
        self._config = self._load()

    def _load(self) -> AutomationConfig:
        if not self.path.is_file():
            return AutomationConfig()
        return AutomationConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write(self, config: AutomationConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)
        self._config = config

    @staticmethod
    def _upsert(items: tuple, item) -> tuple:
        values = {existing.id: existing for existing in items}
        if item.id not in values and len(values) >= MAX_DEFINITIONS:
            raise ValueError("automation definition limit exceeded")
        values[item.id] = item
        return tuple(values[key] for key in sorted(values))

    def list_macros(self) -> list[MacroDefinition]:
        with self._lock:
            return list(self._config.macros)

    def list_rules(self) -> list[HealthRule]:
        with self._lock:
            return list(self._config.rules)

    def list_schedules(self) -> list[DiagnosticSchedule]:
        with self._lock:
            return list(self._config.schedules)

    def get_macro(self, macro_id: str) -> MacroDefinition | None:
        with self._lock:
            return next((item for item in self._config.macros if item.id == macro_id), None)

    def save_macro(self, macro: MacroDefinition) -> None:
        with self._lock:
            self._write(self._config.model_copy(update={"macros": self._upsert(self._config.macros, macro)}))

    def save_rule(self, rule: HealthRule) -> None:
        with self._lock:
            self._write(self._config.model_copy(update={"rules": self._upsert(self._config.rules, rule)}))

    def save_schedule(self, schedule: DiagnosticSchedule) -> None:
        with self._lock:
            if not any(macro.id == schedule.macro_id for macro in self._config.macros):
                raise ValueError("macro does not exist")
            self._write(self._config.model_copy(update={
                "schedules": self._upsert(self._config.schedules, schedule),
            }))

    def delete_macro(self, macro_id: str) -> bool:
        with self._lock:
            if any(schedule.macro_id == macro_id for schedule in self._config.schedules):
                raise ValueError("macro is referenced by a schedule")
            values = tuple(item for item in self._config.macros if item.id != macro_id)
            if len(values) == len(self._config.macros):
                return False
            self._write(self._config.model_copy(update={"macros": values}))
            return True

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock:
            values = tuple(item for item in self._config.rules if item.id != rule_id)
            if len(values) == len(self._config.rules):
                return False
            self._write(self._config.model_copy(update={"rules": values}))
            return True

    def delete_schedule(self, schedule_id: str) -> bool:
        with self._lock:
            values = tuple(item for item in self._config.schedules if item.id != schedule_id)
            if len(values) == len(self._config.schedules):
                return False
            self._write(self._config.model_copy(update={"schedules": values}))
            return True


class HealthMonitor:
    def __init__(
        self,
        store: AutomationStore,
        clock=time.time,
        max_events: int = 500,
    ):
        self.store = store
        self.clock = clock
        self._events: deque[HealthEvent] = deque(maxlen=max(1, min(int(max_events), 5000)))
        self._last_match: dict[tuple[str, str], float] = {}
        self._lock = threading.RLock()

    def observe(self, port: str, content: str) -> list[HealthEvent]:
        now = float(self.clock())
        matches: list[HealthEvent] = []
        with self._lock:
            for rule in self.store.list_rules():
                if not rule.enabled:
                    continue
                try:
                    matched = regex.search(
                        rule.pattern,
                        content,
                        flags=regex.IGNORECASE,
                        timeout=0.01,
                    )
                except TimeoutError:
                    continue
                if matched is None:
                    continue
                key = (rule.id, port)
                last_match = self._last_match.get(key)
                if last_match is not None and now - last_match < rule.cooldown_seconds:
                    continue
                event = HealthEvent(
                    event_id=f"health-{int(now * 1000)}-{secrets.token_urlsafe(6)}",
                    rule_id=rule.id,
                    port=port,
                    severity=rule.severity,
                    message=rule.message,
                    content=content[:4096],
                    timestamp=now,
                )
                self._last_match[key] = now
                self._events.append(event)
                matches.append(event)
        return matches

    def history(self, port: str = "", limit: int = 100) -> list[HealthEvent]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._lock:
            events = [event for event in self._events if not port or event.port == port]
            return events[-safe_limit:]


class MacroRuntime:
    def __init__(
        self,
        store: AutomationStore,
        is_open: Callable[[str], bool],
        write: Callable[[str, str, str], bool],
        get_history: Callable[[str, int], list],
        clock=time.time,
        max_runs: int = 200,
    ):
        self.store = store
        self.is_open = is_open
        self.write = write
        self.get_history = get_history
        self.clock = clock
        self._active: dict[str, ActiveMacro] = {}
        self._runs: deque[MacroRunResult] = deque(maxlen=max(1, min(int(max_runs), 2000)))
        self._lock = threading.RLock()

    def active(self, run_id: str) -> ActiveMacro | None:
        with self._lock:
            return self._active.get(run_id)

    def cancel(self, run_id: str, owner_id: str) -> bool:
        with self._lock:
            active = self._active.get(run_id)
            if active is None or active.owner_id != owner_id:
                return False
            active.cancel.set()
            return True

    def history(self, port: str = "", limit: int = 100) -> list[MacroRunResult]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._lock:
            runs = [run for run in self._runs if not port or run.port == port]
            return runs[-safe_limit:]

    @staticmethod
    def _sequence(message) -> int:
        return int(getattr(message, "sequence", 0))

    @staticmethod
    def _source(message) -> str:
        source = getattr(message, "source", "")
        return str(getattr(source, "value", source))

    def run_macro(
        self,
        run_id: str,
        macro_id: str,
        port: str,
        owner_id: str,
    ) -> MacroRunResult:
        macro = self.store.get_macro(macro_id)
        if macro is None:
            raise ValueError("macro does not exist")
        if not macro.enabled:
            raise ValueError("macro is disabled")
        if not self.is_open(port):
            raise ValueError("port is not open")

        with self._lock:
            if run_id in self._active:
                raise ValueError("run id is already active")
            if any(active.port == port for active in self._active.values()):
                raise ValueError("another macro is active on this port")
            active = ActiveMacro(run_id, port, owner_id)
            self._active[run_id] = active

        started = float(self.clock())
        output_parts: list[str] = []
        steps_completed = 0
        status: Literal["completed", "failed", "cancelled"] = "completed"
        error = ""
        try:
            for step in macro.steps:
                if active.cancel.is_set():
                    status = "cancelled"
                    break
                before = self.get_history(port, 1000)
                cursor = max((self._sequence(message) for message in before), default=0)
                if not self.write(port, step.command, step.newline):
                    status = "failed"
                    error = "serial write failed"
                    break
                if active.cancel.wait(step.wait_seconds):
                    status = "cancelled"
                    break
                after = self.get_history(port, 1000)
                for message in after:
                    if self._sequence(message) > cursor and self._source(message) == "device":
                        output_parts.append(str(getattr(message, "content", "")))
                steps_completed += 1
        finally:
            result = MacroRunResult(
                run_id=run_id,
                macro_id=macro_id,
                port=port,
                owner_id=owner_id,
                status=status,
                output="".join(output_parts)[:MAX_MACRO_OUTPUT],
                steps_completed=steps_completed,
                error=error,
                started_at=started,
                finished_at=float(self.clock()),
            )
            with self._lock:
                self._active.pop(run_id, None)
                self._runs.append(result)
        return result


class SchedulePlanner:
    def __init__(self, store: AutomationStore, clock=time.time):
        self.store = store
        self.clock = clock
        self._last_started: dict[str, float] = {}
        self._states: dict[str, ScheduleState] = {}
        self._lock = threading.RLock()

    def due(self) -> list[DiagnosticSchedule]:
        now = float(self.clock())
        with self._lock:
            return [
                schedule
                for schedule in self.store.list_schedules()
                if schedule.enabled
                and (
                    schedule.id not in self._last_started
                    or now - self._last_started[schedule.id] >= schedule.interval_seconds
                )
            ]

    def mark_started(self, schedule_id: str) -> None:
        with self._lock:
            now = float(self.clock())
            self._last_started[schedule_id] = now
            prior = self._states.get(schedule_id, ScheduleState(schedule_id=schedule_id))
            self._states[schedule_id] = prior.model_copy(update={
                "last_started": now,
                "last_status": "running",
                "last_error": "",
            })

    def record_result(
        self,
        schedule_id: str,
        status: Literal["completed", "failed", "cancelled", "skipped"],
        error: str = "",
        run_id: str = "",
    ) -> None:
        with self._lock:
            prior = self._states.get(schedule_id, ScheduleState(schedule_id=schedule_id))
            self._states[schedule_id] = prior.model_copy(update={
                "last_finished": float(self.clock()),
                "last_status": status,
                "last_error": error[:512],
                "last_run_id": run_id,
            })

    def status(self) -> dict[str, ScheduleState]:
        with self._lock:
            return dict(self._states)
