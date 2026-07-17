import { computed, ref, shallowRef } from 'vue'

export interface MacroStep {
  command: string
  newline: '' | '\r' | '\n' | '\r\n'
  wait_seconds: number
}

export interface MacroDefinition {
  id: string
  name: string
  steps: MacroStep[]
  enabled: boolean
}

export interface HealthRule {
  id: string
  name: string
  pattern: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  cooldown_seconds: number
  enabled: boolean
}

export interface DiagnosticSchedule {
  id: string
  name: string
  macro_id: string
  port: string
  interval_seconds: number
  enabled: boolean
}

export interface ScheduleState {
  schedule_id: string
  last_started: number
  last_finished: number
  last_status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled' | 'skipped'
  last_error: string
  last_run_id: string
}

export interface HealthEvent {
  event_id: string
  rule_id: string
  port: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  content: string
  timestamp: number
}

export interface MacroRunResult {
  run_id: string
  macro_id: string
  port: string
  owner_id: string
  status: 'completed' | 'failed' | 'cancelled'
  output: string
  steps_completed: number
  error: string
  started_at: number
  finished_at: number
}

export interface ActiveMacroRun {
  runId: string
  macroId: string
  port: string
}

interface AutomationPayload {
  macros: MacroDefinition[]
  rules: HealthRule[]
  schedules: DiagnosticSchedule[]
  schedule_status: Record<string, ScheduleState>
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

export function createAutomationsClient(
  fetcher: Fetcher = fetch,
  createRunId: () => string = () => `web-macro-${crypto.randomUUID().replaceAll('-', '')}`,
  getClientId: () => string = () => '',
) {
  const macros = ref<MacroDefinition[]>([])
  const rules = ref<HealthRule[]>([])
  const schedules = ref<DiagnosticSchedule[]>([])
  const scheduleStatus = ref<Record<string, ScheduleState>>({})
  const healthEvents = ref<HealthEvent[]>([])
  const runs = ref<MacroRunResult[]>([])
  const activeRuns = ref<ActiveMacroRun[]>([])
  const busy = shallowRef(false)
  const error = shallowRef('')

  function headers(json = false): HeadersInit {
    const value: Record<string, string> = {
      'X-AI-Serial-Client': getClientId() || 'web-automation',
      'X-AI-Serial-Client-Label': 'Web UI',
    }
    if (json) value['Content-Type'] = 'application/json'
    return value
  }

  async function request<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetcher(url, init)
    const payload = await response.json().catch(() => ({})) as { detail?: unknown } & T
    if (!response.ok) {
      const detail = typeof payload.detail === 'string'
        ? payload.detail
        : payload.detail ? JSON.stringify(payload.detail) : `HTTP ${response.status}`
      error.value = detail
      throw new Error(detail)
    }
    error.value = ''
    return payload
  }

  async function load() {
    busy.value = true
    try {
      const [definitions, health, recentRuns] = await Promise.all([
        request<AutomationPayload>('/api/automations'),
        request<HealthEvent[]>('/api/automations/health?limit=200'),
        request<MacroRunResult[]>('/api/automations/runs?limit=100'),
      ])
      macros.value = definitions.macros || []
      rules.value = definitions.rules || []
      schedules.value = definitions.schedules || []
      scheduleStatus.value = definitions.schedule_status || {}
      healthEvents.value = health
      runs.value = recentRuns
    } finally {
      busy.value = false
    }
  }

  async function saveMacro(macro: MacroDefinition) {
    const payload = await request<{ macro: MacroDefinition }>(
      `/api/automations/macros/${encodeURIComponent(macro.id)}`,
      { method: 'PUT', headers: headers(true), body: JSON.stringify(macro) },
    )
    macros.value = [...macros.value.filter(item => item.id !== macro.id), payload.macro]
      .sort((left, right) => left.id.localeCompare(right.id))
  }

  async function deleteMacro(macroId: string) {
    await request(`/api/automations/macros/${encodeURIComponent(macroId)}`, {
      method: 'DELETE', headers: headers(),
    })
    macros.value = macros.value.filter(item => item.id !== macroId)
  }

  async function saveRule(rule: HealthRule) {
    const payload = await request<{ rule: HealthRule }>(
      `/api/automations/rules/${encodeURIComponent(rule.id)}`,
      { method: 'PUT', headers: headers(true), body: JSON.stringify(rule) },
    )
    rules.value = [...rules.value.filter(item => item.id !== rule.id), payload.rule]
      .sort((left, right) => left.id.localeCompare(right.id))
  }

  async function deleteRule(ruleId: string) {
    await request(`/api/automations/rules/${encodeURIComponent(ruleId)}`, {
      method: 'DELETE', headers: headers(),
    })
    rules.value = rules.value.filter(item => item.id !== ruleId)
  }

  async function saveSchedule(schedule: DiagnosticSchedule) {
    const payload = await request<{ schedule: DiagnosticSchedule }>(
      `/api/automations/schedules/${encodeURIComponent(schedule.id)}`,
      { method: 'PUT', headers: headers(true), body: JSON.stringify(schedule) },
    )
    schedules.value = [...schedules.value.filter(item => item.id !== schedule.id), payload.schedule]
      .sort((left, right) => left.id.localeCompare(right.id))
  }

  async function deleteSchedule(scheduleId: string) {
    await request(`/api/automations/schedules/${encodeURIComponent(scheduleId)}`, {
      method: 'DELETE', headers: headers(),
    })
    schedules.value = schedules.value.filter(item => item.id !== scheduleId)
    const nextStatus = { ...scheduleStatus.value }
    delete nextStatus[scheduleId]
    scheduleStatus.value = nextStatus
  }

  async function runMacro(macroId: string, port: string) {
    const runId = createRunId()
    const params = new URLSearchParams({ port, run_id: runId })
    activeRuns.value = [...activeRuns.value, { runId, macroId, port }]
    try {
      const result = await request<MacroRunResult>(
        `/api/automations/macros/${encodeURIComponent(macroId)}/run?${params}`,
        { method: 'POST', headers: headers() },
      )
      runs.value = [result, ...runs.value].slice(0, 100)
      return result
    } finally {
      activeRuns.value = activeRuns.value.filter(run => run.runId !== runId)
    }
  }

  async function cancelMacro(runId: string) {
    return request<{ success: boolean; run_id: string }>(
      `/api/automations/runs/${encodeURIComponent(runId)}/cancel`,
      { method: 'POST', headers: headers() },
    )
  }

  return {
    macros: computed(() => macros.value),
    rules: computed(() => rules.value),
    schedules: computed(() => schedules.value),
    scheduleStatus: computed(() => scheduleStatus.value),
    healthEvents: computed(() => healthEvents.value),
    runs: computed(() => runs.value),
    activeRuns: computed(() => activeRuns.value),
    busy: computed(() => busy.value),
    error: computed(() => error.value),
    load,
    saveMacro,
    deleteMacro,
    saveRule,
    deleteRule,
    saveSchedule,
    deleteSchedule,
    runMacro,
    cancelMacro,
  }
}
