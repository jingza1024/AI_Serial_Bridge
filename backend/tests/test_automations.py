"""Automation definitions, persistence, rule evaluation, and runtime tests."""

from pathlib import Path
from types import SimpleNamespace
import time
import uuid

import pytest

from automations import (
    AutomationStore,
    DiagnosticSchedule,
    HealthMonitor,
    HealthRule,
    MacroDefinition,
    MacroRuntime,
    MacroStep,
    SchedulePlanner,
)


@pytest.fixture
def automation_path():
    base = Path.cwd() / ".test-artifacts"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"automations-{uuid.uuid4().hex}.json"
    yield path
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)


def test_store_persists_bounded_automation_definitions(automation_path):
    store = AutomationStore(automation_path)
    macro = MacroDefinition(
        id="linux-health",
        name="Linux health",
        steps=(MacroStep(command="uname -a", newline="\r", wait_seconds=1.0),),
    )
    rule = HealthRule(
        id="kernel-panic",
        name="Kernel panic",
        pattern=r"kernel panic",
        severity="critical",
        message="Kernel panic detected",
        cooldown_seconds=60,
    )
    schedule = DiagnosticSchedule(
        id="hourly-linux-health",
        name="Hourly Linux health",
        macro_id=macro.id,
        port="COM14",
        interval_seconds=3600,
        enabled=True,
    )

    store.save_macro(macro)
    store.save_rule(rule)
    store.save_schedule(schedule)

    reloaded = AutomationStore(automation_path)
    assert reloaded.list_macros() == [macro]
    assert reloaded.list_rules() == [rule]
    assert reloaded.list_schedules() == [schedule]


def test_store_rejects_schedule_for_missing_macro(automation_path):
    store = AutomationStore(automation_path)
    schedule = DiagnosticSchedule(
        id="orphan",
        name="Orphan schedule",
        macro_id="missing",
        port="COM14",
        interval_seconds=60,
    )

    with pytest.raises(ValueError, match="macro does not exist"):
        store.save_schedule(schedule)


def test_health_monitor_matches_rules_with_cooldown_and_bounded_history(automation_path):
    now = [100.0]
    store = AutomationStore(automation_path)
    store.save_rule(HealthRule(
        id="kernel-panic",
        name="Kernel panic",
        pattern=r"kernel\s+panic",
        severity="critical",
        message="Kernel panic detected",
        cooldown_seconds=30,
    ))
    monitor = HealthMonitor(store, clock=lambda: now[0], max_events=2)

    first = monitor.observe("COM14", "KERNEL PANIC: fatal exception")
    assert len(first) == 1
    assert first[0].rule_id == "kernel-panic"
    assert first[0].port == "COM14"
    assert first[0].severity == "critical"
    assert first[0].message == "Kernel panic detected"

    now[0] = 110.0
    assert monitor.observe("COM14", "kernel panic again") == []

    now[0] = 131.0
    assert len(monitor.observe("COM14", "kernel panic after cooldown")) == 1
    now[0] = 162.0
    assert len(monitor.observe("COM14", "kernel panic newest")) == 1
    assert [event.timestamp for event in monitor.history()] == [131.0, 162.0]


def test_health_rule_rejects_invalid_regex():
    with pytest.raises(ValueError, match="invalid regex"):
        HealthRule(
            id="bad-regex",
            name="Bad regex",
            pattern="[",
            message="Never valid",
        )


def test_health_monitor_bounds_pathological_regex_runtime(automation_path):
    store = AutomationStore(automation_path)
    store.save_rule(HealthRule(
        id="bounded-regex",
        name="Bounded regex",
        pattern=r"(a+)+$",
        message="Must not block serial reads",
        cooldown_seconds=0,
    ))
    monitor = HealthMonitor(store)

    started = time.monotonic()
    events = monitor.observe("COM17", "a" * 10000 + "!")

    assert events == []
    assert time.monotonic() - started < 0.2


def test_macro_runtime_executes_steps_and_captures_device_output(automation_path):
    store = AutomationStore(automation_path)
    store.save_macro(MacroDefinition(
        id="linux-health",
        name="Linux health",
        steps=(
            MacroStep(command="uname -a", newline="\r", wait_seconds=0),
            MacroStep(command="uptime", newline="\r", wait_seconds=0),
        ),
    ))
    messages = []
    writes = []

    def write(port: str, command: str, newline: str):
        writes.append((port, command, newline))
        messages.append(SimpleNamespace(
            sequence=len(messages) + 1,
            source="device",
            content=f"response:{command}\n",
        ))
        return True

    runtime = MacroRuntime(
        store,
        is_open=lambda port: port == "COM14",
        write=write,
        get_history=lambda port, limit: list(messages),
        clock=lambda: 100.0,
        max_runs=2,
    )
    result = runtime.run_macro("run-1", "linux-health", "COM14", "client-a")

    assert result.status == "completed"
    assert result.steps_completed == 2
    assert result.output == "response:uname -a\nresponse:uptime\n"
    assert writes == [("COM14", "uname -a", "\r"), ("COM14", "uptime", "\r")]
    assert runtime.history() == [result]


def test_macro_runtime_cancels_only_for_owner(automation_path):
    store = AutomationStore(automation_path)
    store.save_macro(MacroDefinition(
        id="cancel-me",
        name="Cancel me",
        steps=(MacroStep(command="first", wait_seconds=1), MacroStep(command="second", wait_seconds=0)),
    ))
    runtime = None
    writes = []

    def write(port: str, command: str, newline: str):
        writes.append(command)
        assert runtime is not None
        assert runtime.cancel("run-cancel", "other-client") is False
        assert runtime.cancel("run-cancel", "owner-client") is True
        return True

    runtime = MacroRuntime(
        store,
        is_open=lambda port: True,
        write=write,
        get_history=lambda port, limit: [],
        clock=lambda: 200.0,
    )
    result = runtime.run_macro("run-cancel", "cancel-me", "COM14", "owner-client")

    assert result.status == "cancelled"
    assert writes == ["first"]
    assert runtime.active("run-cancel") is None


def test_schedule_planner_returns_each_due_schedule_once_per_interval(automation_path):
    now = [100.0]
    store = AutomationStore(automation_path)
    store.save_macro(MacroDefinition(
        id="health",
        name="Health",
        steps=(MacroStep(command="uptime", wait_seconds=0),),
    ))
    schedule = DiagnosticSchedule(
        id="health-every-minute",
        name="Health every minute",
        macro_id="health",
        port="COM14",
        interval_seconds=60,
        enabled=True,
    )
    store.save_schedule(schedule)
    planner = SchedulePlanner(store, clock=lambda: now[0])

    assert planner.due() == [schedule]
    planner.mark_started(schedule.id)
    assert planner.due() == []
    now[0] = 159.0
    assert planner.due() == []
    now[0] = 160.0
    assert planner.due() == [schedule]
    planner.record_result(schedule.id, "completed", run_id="scheduled-1")
    state = planner.status()[schedule.id]
    assert state.last_status == "completed"
    assert state.last_run_id == "scheduled-1"


def test_macro_definition_rejects_total_wait_beyond_lease_window():
    with pytest.raises(ValueError, match="total wait"):
        MacroDefinition(
            id="too-long",
            name="Too long",
            steps=tuple(MacroStep(command=f"step-{index}", wait_seconds=30) for index in range(9)),
        )
