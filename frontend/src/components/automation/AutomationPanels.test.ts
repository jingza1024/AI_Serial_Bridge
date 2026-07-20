import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { currentLocale } from '../../composables/useLocale'
import MacroPanel from './MacroPanel.vue'
import HealthStatusPanel from './HealthStatusPanel.vue'
import SchedulePanel from './SchedulePanel.vue'

beforeEach(() => {
  currentLocale.value = 'en'
})

afterEach(() => {
  currentLocale.value = 'zh'
})

describe('automation panels', () => {
  it('emits a macro run for the selected port', async () => {
    const wrapper = mount(MacroPanel, {
      props: {
        macros: [{
          id: 'linux-health',
          name: 'Linux health',
          steps: [{ command: 'uname -a', newline: '\r', wait_seconds: 1 }],
          enabled: true,
        }],
        runs: [],
        busy: false,
      },
    })

    await wrapper.get('[aria-label="Macro run port"]').setValue('COM17')
    await wrapper.get('[data-testid="run-linux-health"]').trigger('click')

    expect(wrapper.text()).toContain('Linux health')
    expect(wrapper.emitted('run')?.[0]).toEqual(['linux-health', 'COM17'])
  })

  it('uses real serial control characters for macro newlines', () => {
    const wrapper = mount(MacroPanel, {
      props: { macros: [], runs: [], busy: false },
    })

    const values = wrapper.get('[aria-label="Newline"]').findAll('option')
      .map(option => (option.element as HTMLOptionElement).value)

    expect(values).toEqual(['\r', '\n', '\r\n', ''])
  })

  it('renders health severity and emits refresh', async () => {
    const wrapper = mount(HealthStatusPanel, {
      props: {
        rules: [],
        events: [{
          event_id: 'health-1',
          rule_id: 'kernel-panic',
          port: 'COM17',
          severity: 'critical',
          message: 'Kernel panic detected',
          content: 'kernel panic',
          timestamp: 1,
        }],
        busy: false,
      },
    })

    expect(wrapper.text()).toContain('Kernel panic detected')
    expect(wrapper.text()).toContain('critical')
    await wrapper.get('[data-testid="refresh-health"]').trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })

  it('shows schedule status and emits an enabled update', async () => {
    const schedule = {
      id: 'hourly-health',
      name: 'Hourly health',
      macro_id: 'linux-health',
      port: 'COM17',
      interval_seconds: 3600,
      enabled: false,
    }
    const wrapper = mount(SchedulePanel, {
      props: {
        schedules: [schedule],
        macros: [{
          id: 'linux-health',
          name: 'Linux health',
          steps: [{ command: 'uname -a', newline: '\r', wait_seconds: 1 }],
          enabled: true,
        }],
        status: {
          'hourly-health': {
            schedule_id: 'hourly-health',
            last_started: 1,
            last_finished: 2,
            last_status: 'skipped',
            last_error: 'writer lease is held by another client',
            last_run_id: '',
          },
        },
        busy: false,
      },
    })

    expect(wrapper.text()).toContain('writer lease is held by another client')
    await wrapper.get('[data-testid="toggle-hourly-health"]').setValue(true)
    expect(wrapper.emitted('save')?.[0]).toEqual([{ ...schedule, enabled: true }])
  })
})
