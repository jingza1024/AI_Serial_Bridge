import { describe, expect, it } from 'vitest'
import { createSerialProfiles } from './useSerialProfiles'
import { defaultSerialSettings, type SerialPort } from './useSerial'

class MemoryStorage implements Storage {
  private data = new Map<string, string>()
  get length() { return this.data.size }
  clear() { this.data.clear() }
  getItem(key: string) { return this.data.get(key) ?? null }
  key(index: number) { return [...this.data.keys()][index] ?? null }
  removeItem(key: string) { this.data.delete(key) }
  setItem(key: string, value: string) { this.data.set(key, value) }
}

const ports: SerialPort[] = [
  { device: 'COM14', description: 'Linux console', hwid: 'USB-DEVICE-1' },
]

describe('serial profiles', () => {
  it('matches a renamed COM port by hardware id', () => {
    const storage = new MemoryStorage()
    const store = createSerialProfiles(storage)
    store.saveForPort('COM14', ports, 'Board console', defaultSerialSettings(), true)

    const moved = [{ ...ports[0], device: 'COM18' }]
    expect(store.findForPort('COM18', moved)?.name).toBe('Board console')
    expect(store.autoReconnectTargets(moved, [])[0].port).toBe('COM18')
  })

  it('does not reconnect disabled or already-open profiles', () => {
    const storage = new MemoryStorage()
    const store = createSerialProfiles(storage)
    store.saveForPort('COM14', ports, 'Manual', defaultSerialSettings(), false)
    expect(store.autoReconnectTargets(ports, [])).toEqual([])

    store.saveForPort('COM14', ports, 'Auto', defaultSerialSettings(), true)
    expect(store.autoReconnectTargets(ports, ['COM14'])).toEqual([])
  })
})
