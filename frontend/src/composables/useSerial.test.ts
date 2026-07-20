import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSerial, type SerialMessage } from './useSerial'

afterEach(() => {
  useSerial().disconnect()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('useSerial batch receive', () => {
  it('downloads the YMODEM batch archive using the server filename', async () => {
    const response = {
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="ymodem-COM14-batch.zip"' }),
      blob: vi.fn().mockResolvedValue(new Blob(['archive'], { type: 'application/zip' })),
    }
    const fetchMock = vi.fn().mockResolvedValue(response)
    vi.stubGlobal('fetch', fetchMock)
    const createObjectURL = vi.fn().mockReturnValue('blob:batch')
    const revokeObjectURL = vi.fn()
    class BrowserURL extends URL {
      static createObjectURL = createObjectURL
      static revokeObjectURL = revokeObjectURL
    }
    vi.stubGlobal('URL', BrowserURL)
    let downloaded = ''
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloaded = this.download
    })

    const transfer = useSerial().receiveYmodemBatch('COM14')
    await transfer.promise

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/^\/api\/transfer\/receive-batch\?port=COM14&transfer_id=web-rxb-/),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(downloaded).toBe('ymodem-COM14-batch.zip')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:batch')
  })
})

describe('useSerial port session lifecycle', () => {
  class FakeWebSocket {
    static OPEN = 1
    static instances: FakeWebSocket[] = []
    readyState = 1
    sent: string[] = []
    onopen: (() => void) | null = null
    onmessage: ((event: MessageEvent) => void) | null = null
    onclose: ((event: CloseEvent) => void) | null = null
    onerror: ((event: Event) => void) | null = null

    constructor() {
      FakeWebSocket.instances.push(this)
    }

    send(value: string) {
      this.sent.push(value)
    }

    close() {
      this.readyState = 3
      this.onclose?.({ code: 1000, reason: '' } as CloseEvent)
    }
  }

  function message(sequence: number, content: string): SerialMessage {
    return {
      type: 'serial_message',
      source: 'device',
      content,
      sequence,
      timestamp: sequence,
      time_str: '',
    }
  }

  async function connectedSerial() {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ auth_required: false }),
    }))
    const serial = useSerial()
    await serial.connect()
    const socket = FakeWebSocket.instances.at(-1)
    expect(socket).toBeDefined()
    socket?.onopen?.()
    return { serial, socket: socket as FakeWebSocket }
  }

  it('accepts new sequence numbers after the UI closes and reopens a port', async () => {
    const { serial, socket } = await connectedSerial()
    const received: string[] = []
    serial.onMessage('COM17', msg => received.push(msg.content))

    socket.onmessage?.({ data: JSON.stringify({
      type: 'open_ports',
      ports: [{ port: 'COM17', baudrate: 115200, settings: {}, lease: null }],
    }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({ ...message(1, 'first\r\n'), port: 'COM17' }) } as MessageEvent)
    serial.closePort('COM17')
    socket.onmessage?.({ data: JSON.stringify({ type: 'open_ports', ports: [] }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({
      type: 'open_ports',
      ports: [{ port: 'COM17', baudrate: 115200, settings: {}, lease: null }],
    }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({ ...message(1, 'second\r\n'), port: 'COM17' }) } as MessageEvent)

    expect(received).toEqual(['first\r\n', 'second\r\n'])
  })

  it('clears cached messages when another client closes the port', async () => {
    const { serial, socket } = await connectedSerial()
    socket.onmessage?.({ data: JSON.stringify({
      type: 'open_ports',
      ports: [{ port: 'COM18', baudrate: 115200, settings: {}, lease: null }],
    }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({ ...message(1, 'first\r\n'), port: 'COM18' }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({ type: 'open_ports', ports: [] }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({
      type: 'open_ports',
      ports: [{ port: 'COM18', baudrate: 115200, settings: {}, lease: null }],
    }) } as MessageEvent)
    socket.onmessage?.({ data: JSON.stringify({ ...message(1, 'second\r\n'), port: 'COM18' }) } as MessageEvent)

    expect(serial.getHistory('COM18', 0).map(item => item.content)).toEqual(['second\r\n'])
  })
})
