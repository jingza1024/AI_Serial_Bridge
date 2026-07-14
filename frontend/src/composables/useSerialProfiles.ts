import { ref, readonly, type Ref } from 'vue'
import { defaultSerialSettings, type SerialPort, type SerialSettings } from './useSerial'

export interface SerialProfile {
  id: string
  name: string
  hwid: string
  lastPort: string
  settings: SerialSettings
  autoReconnect: boolean
  updatedAt: number
}

const STORAGE_KEY = 'ai-serial-bridge.profiles.v2'
const LEGACY_KEY = 'ai-serial-bridge.profiles.v1'

function cloneSettings(settings?: Partial<SerialSettings>): SerialSettings {
  return { ...defaultSerialSettings(), ...(settings || {}) }
}

function profileId(): string {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function loadProfiles(storage: Storage): SerialProfile[] {
  try {
    const current = JSON.parse(storage.getItem(STORAGE_KEY) || '[]') as SerialProfile[]
    if (Array.isArray(current) && current.length) {
      return current.map(profile => ({ ...profile, settings: cloneSettings(profile.settings) }))
    }
    const legacy = JSON.parse(storage.getItem(LEGACY_KEY) || '{}') as Record<string, SerialSettings>
    return Object.entries(legacy).map(([key, settings]) => ({
      id: profileId(),
      name: key,
      hwid: key,
      lastPort: /^(COM\d+|\/dev\/)/i.test(key) ? key : '',
      settings: cloneSettings(settings),
      autoReconnect: false,
      updatedAt: Date.now(),
    }))
  } catch {
    return []
  }
}

export function createSerialProfiles(storage: Storage) {
  const profiles = ref<SerialProfile[]>(loadProfiles(storage))

  function persist() {
    storage.setItem(STORAGE_KEY, JSON.stringify(profiles.value))
  }

  function deviceFor(port: string, ports: readonly SerialPort[]): SerialPort | undefined {
    return ports.find(candidate => candidate.device === port)
  }

  function findForPort(port: string, ports: readonly SerialPort[]): SerialProfile | undefined {
    const device = deviceFor(port, ports)
    return profiles.value.find(profile =>
      (Boolean(device?.hwid) && profile.hwid === device?.hwid) || profile.lastPort === port,
    )
  }

  function saveForPort(
    port: string,
    ports: readonly SerialPort[],
    name: string,
    settings: SerialSettings,
    autoReconnect: boolean,
  ): SerialProfile {
    const device = deviceFor(port, ports)
    const existing = findForPort(port, ports)
    const profile: SerialProfile = {
      id: existing?.id || profileId(),
      name: name.trim() || device?.description || port,
      hwid: device?.hwid || existing?.hwid || port,
      lastPort: port,
      settings: cloneSettings(settings),
      autoReconnect,
      updatedAt: Date.now(),
    }
    profiles.value = existing
      ? profiles.value.map(item => item.id === existing.id ? profile : item)
      : [...profiles.value, profile]
    persist()
    return profile
  }

  function remove(id: string) {
    profiles.value = profiles.value.filter(profile => profile.id !== id)
    persist()
  }

  function autoReconnectTargets(ports: readonly SerialPort[], openPorts: readonly string[]) {
    const open = new Set(openPorts)
    return profiles.value.flatMap(profile => {
      if (!profile.autoReconnect) return []
      const match = ports.find(port =>
        (Boolean(profile.hwid) && port.hwid === profile.hwid) || port.device === profile.lastPort,
      )
      if (!match || open.has(match.device)) return []
      return [{ profile, port: match.device }]
    })
  }

  return {
    profiles: readonly(profiles) as Readonly<Ref<SerialProfile[]>>,
    findForPort,
    saveForPort,
    remove,
    autoReconnectTargets,
  }
}
