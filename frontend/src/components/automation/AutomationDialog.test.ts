import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { currentLocale } from '../../composables/useLocale'
import AutomationDialog from './AutomationDialog.vue'

beforeEach(() => {
  currentLocale.value = 'en'
})

afterEach(() => {
  currentLocale.value = 'zh'
  vi.restoreAllMocks()
})

describe('AutomationDialog', () => {
  it('loads automation data and emits close from the visible dialog', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/automations')) {
        return new Response(JSON.stringify({ macros: [], rules: [], schedules: [], schedule_status: {} }), { status: 200 })
      }
      if (url.includes('/health?')) return new Response('[]', { status: 200 })
      if (url.includes('/runs?')) return new Response('[]', { status: 200 })
      return new Response('{}', { status: 200 })
    })

    const wrapper = mount(AutomationDialog, {
      props: { visible: true, clientId: 'web-test' },
    })

    await flushPromises()

    expect(fetcher).toHaveBeenCalled()
    expect(wrapper.get('[role="dialog"]').text()).toContain('Device Automations')
    await wrapper.get('[data-testid="automation-close"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
