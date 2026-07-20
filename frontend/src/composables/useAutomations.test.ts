import { describe, expect, it, vi } from 'vitest'
import { createAutomationsClient, type MacroDefinition } from './useAutomations'

function jsonResponse(payload: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 400,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response
}

describe('automation client', () => {
  it('loads definitions, health events, and macro runs', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/automations') {
        return jsonResponse({
          macros: [{ id: 'health', name: 'Health', steps: [{ command: 'uptime', newline: '\r', wait_seconds: 1 }], enabled: true }],
          rules: [],
          schedules: [],
          schedule_status: {},
        })
      }
      if (url === '/api/automations/health?limit=200') return jsonResponse([{ event_id: 'h1', severity: 'warning' }])
      if (url === '/api/automations/runs?limit=100') return jsonResponse([{ run_id: 'r1', status: 'completed' }])
      throw new Error(`unexpected URL: ${url}`)
    })
    const client = createAutomationsClient(fetcher)

    await client.load()

    expect(client.macros.value[0].id).toBe('health')
    expect(client.healthEvents.value[0].event_id).toBe('h1')
    expect(client.runs.value[0].run_id).toBe('r1')
  })

  it('saves and runs a macro through explicit actions', async () => {
    const macro: MacroDefinition = {
      id: 'linux-health',
      name: 'Linux health',
      steps: [{ command: 'uname -a', newline: '\r', wait_seconds: 1 }],
      enabled: true,
    }
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/automations/macros/linux-health') {
        expect(init?.method).toBe('PUT')
        expect(JSON.parse(String(init?.body))).toEqual(macro)
        return jsonResponse({ success: true, macro })
      }
      if (url.startsWith('/api/automations/macros/linux-health/run?')) {
        expect(init?.method).toBe('POST')
        expect(url).toContain('port=COM14')
        return jsonResponse({
          run_id: 'web-run-1',
          macro_id: 'linux-health',
          port: 'COM14',
          owner_id: 'web',
          status: 'completed',
          output: 'Linux 5.4\n',
          steps_completed: 1,
          error: '',
          started_at: 1,
          finished_at: 2,
        })
      }
      throw new Error(`unexpected URL: ${url}`)
    })
    const client = createAutomationsClient(fetcher, () => 'web-run-1')

    await client.saveMacro(macro)
    const result = await client.runMacro('linux-health', 'COM14')

    expect(client.macros.value).toEqual([macro])
    expect(result.output).toBe('Linux 5.4\n')
    expect(client.runs.value[0]).toEqual(result)
  })

  it('surfaces backend errors without mutating definitions', async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ detail: 'macro is referenced by a schedule' }, false))
    const client = createAutomationsClient(fetcher)

    await expect(client.deleteMacro('health')).rejects.toThrow('macro is referenced by a schedule')
    expect(client.macros.value).toEqual([])
    expect(client.error.value).toBe('macro is referenced by a schedule')
  })

  it('exposes an active run until it completes so it can be cancelled', async () => {
    let finishRun: ((response: Response) => void) | undefined
    const runResponse = new Promise<Response>(resolve => { finishRun = resolve })
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/run?')) return runResponse
      if (url.includes('/cancel')) return jsonResponse({ success: true, run_id: 'web-run-active' })
      throw new Error(`unexpected URL: ${url}`)
    })
    const client = createAutomationsClient(fetcher, () => 'web-run-active')

    const pending = client.runMacro('linux-health', 'COM17')
    expect(client.activeRuns.value).toEqual([{
      runId: 'web-run-active',
      macroId: 'linux-health',
      port: 'COM17',
    }])

    await client.cancelMacro('web-run-active')
    finishRun?.(jsonResponse({
      run_id: 'web-run-active',
      macro_id: 'linux-health',
      port: 'COM17',
      owner_id: 'web',
      status: 'cancelled',
      output: '',
      steps_completed: 0,
      error: '',
      started_at: 1,
      finished_at: 2,
    }))
    await pending

    expect(client.activeRuns.value).toEqual([])
  })
})
