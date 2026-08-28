import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'
import TerminalPanel from './TerminalPanel.vue'

const mocks = vi.hoisted(() => {
  const terminal = {
    getSelection: vi.fn(() => 'selected output'),
    paste: vi.fn(),
    write: vi.fn(),
    clear: vi.fn(),
    scrollToBottom: vi.fn(),
    onData: vi.fn(() => ({ dispose: vi.fn() })),
    options: {},
  }
  return { terminal }
})

vi.mock('../composables/useTerminalSession', () => ({
  useTerminalSession: () => ({
    mount: vi.fn(() => mocks.terminal),
  }),
}))

vi.mock('../composables/useLocale', () => ({
  useLocale: () => ({
    t: (key: string) => ({
      'terminal.copy': 'Copy',
      'terminal.paste': 'Paste',
      'terminal.system': 'SYS',
    }[key] || key),
  }),
}))

vi.mock('../composables/useSerial', () => ({
  useSerial: () => ({
    portSettings: ref({ COM18: { baudrate: 115200 } }),
    leases: ref({ COM18: null }),
    clientId: shallowRef('client'),
    canWrite: vi.fn(() => true),
    isSerialOpen: ref({ COM18: true }),
    isConnected: shallowRef(true),
    messages: ref({ COM18: {} }),
    rawChunks: ref({ COM18: {} }),
    onMessage: vi.fn(),
    offMessage: vi.fn(),
    onRaw: vi.fn(),
    offRaw: vi.fn(),
    connect: vi.fn(),
    send: vi.fn(),
    sendRaw: vi.fn(),
    sendFile: vi.fn(),
    sendProtocolFile: vi.fn(),
    receiveProtocolFile: vi.fn(),
    receiveYmodemBatch: vi.fn(),
    loadHistory: vi.fn(),
    loadRawHistory: vi.fn(),
    getHistory: vi.fn(() => []),
    getRawHistory: vi.fn(() => []),
    acquireLease: vi.fn(),
    releaseLease: vi.fn(),
  }),
}))

describe('TerminalPanel clipboard context menu', () => {
  it('opens on terminal right click and copies/pastes clipboard text', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const readText = vi.fn().mockResolvedValue('echo pasted')
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText, readText },
    })

    const wrapper = mount(TerminalPanel, { props: { port: 'COM18' } })
    const panel = wrapper.get('.terminal-panel').element as HTMLDivElement
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 400,
      height: 300,
      right: 400,
      bottom: 300,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    await wrapper.get('.terminal-container').trigger('contextmenu', {
      clientX: 350,
      clientY: 250,
    })

    expect(wrapper.get('[role="menu"]')).toBeTruthy()
    const menuItems = () => wrapper.findAll('[role="menuitem"]')
    expect(menuItems()[0].attributes('disabled')).toBeUndefined()

    mocks.terminal.getSelection.mockReturnValue('')
    await menuItems()[0].trigger('click')
    expect(writeText).toHaveBeenCalledWith('selected output')
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)

    await wrapper.get('.terminal-container').trigger('contextmenu', { clientX: 120, clientY: 80 })
    await menuItems()[1].trigger('click')
    await vi.waitFor(() => {
      expect(readText).toHaveBeenCalledOnce()
      expect(mocks.terminal.paste).toHaveBeenCalledWith('echo pasted')
    })
  })
})
