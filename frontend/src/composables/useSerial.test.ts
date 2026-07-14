import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSerial } from './useSerial'

afterEach(() => {
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
