import { readonly, ref, shallowRef } from 'vue'

export interface SerialSettings {
  baudrate: number
  bytesize: 5 | 6 | 7 | 8
  parity: 'N' | 'E' | 'O' | 'M' | 'S'
  stopbits: 1 | 1.5 | 2
  xonxoff: boolean
  rtscts: boolean
  dsrdtr: boolean
  dtr: boolean | null
  rts: boolean | null
}

export interface PortLease {
  port: string
  owner_id: string
  owner_label: string
  expires_at: number
}

export interface SerialMessage {
  type: 'serial_message'
  source: 'user' | 'ai' | 'device' | 'system'
  content: string
  raw_hex?: string
  sequence: number
  event_code?: string | null
  event_params?: Record<string, string | number | boolean>
  timestamp: number
  time_str: string
}

export interface SerialRawChunk {
  type: 'serial_raw'
  raw_hex: string
  sequence: number
  timestamp: number
}

export interface SerialPort {
  device: string
  description: string
  hwid: string
}

export interface FileTransferHandle {
  promise: Promise<void>
  cancel: () => void
}

export type TransferProtocol = 'raw' | 'xmodem' | 'xmodem1k' | 'ymodem'
export type ProtocolTransferName = Exclude<TransferProtocol, 'raw'>
  | 'receive-xmodem'
  | 'receive-ymodem'
  | 'receive-ymodem-batch'

export interface ProtocolTransferState {
  transferId: string
  port: string
  protocol: ProtocolTransferName
  sent: number
  total: number
  block: number
  retries: number
  complete: boolean
  error: string
}

interface OpenPortDetail {
  port: string
  baudrate: number
  settings: SerialSettings
  lease: PortLease | null
}

interface FileTransfer {
  id: string
  port: string
  bytes: Uint8Array
  offset: number
  pendingEnd: number
  sequence: number
  onProgress?: (sent: number, total: number) => void
  resolve: () => void
  reject: (reason: Error) => void
}

export const defaultSerialSettings = (): SerialSettings => ({
  baudrate: 115200,
  bytesize: 8,
  parity: 'N',
  stopbits: 1,
  xonxoff: false,
  rtscts: false,
  dsrdtr: false,
  dtr: null,
  rts: null,
})

const ws = shallowRef<WebSocket | null>(null)
const isConnected = shallowRef(false)
const authRequired = shallowRef(false)
const authenticated = shallowRef(false)
const authBusy = shallowRef(false)
const authError = shallowRef('')
const protocolError = shallowRef('')
const clientId = shallowRef('')
const isSerialOpen = ref<Record<string, boolean>>({})
const openPorts = ref<string[]>([])
const ports = ref<SerialPort[]>([])
const messages = ref<Record<string, SerialMessage[]>>({})
const rawChunks = ref<Record<string, SerialRawChunk[]>>({})
const portBaudrates = ref<Record<string, number>>({})
const portSettings = ref<Record<string, SerialSettings>>({})
const leases = ref<Record<string, PortLease | null>>({})
const protocolTransfers = ref<Record<string, ProtocolTransferState>>({})

const callbacks: Record<string, ((msg: SerialMessage) => void)[]> = {}
const rawCallbacks: Record<string, ((chunk: SerialRawChunk) => void)[]> = {}
const transfers = new Map<string, FileTransfer>()
const protocolProgressCallbacks = new Map<string, (sent: number, total: number) => void>()

let configLoaded = false
let connecting = false
let manualDisconnect = false
let reconnectAttempts = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

const MAX_RECONNECT_DELAY = 10000
const MAX_FILE_SIZE = 32 * 1024 * 1024
const FILE_CHUNK = 4096

function ensureCallbacks(port: string) {
  if (!callbacks[port]) callbacks[port] = []
  if (!rawCallbacks[port]) rawCallbacks[port] = []
}

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws`
}

function sendCommand(command: Record<string, unknown>): boolean {
  const socket = ws.value
  if (!socket || socket.readyState !== WebSocket.OPEN) return false
  socket.send(JSON.stringify(command))
  return true
}

function tokenFromHash(): string {
  return new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token') || ''
}

function clearTokenHash() {
  if (window.location.hash) {
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  }
}

async function authenticate(token: string): Promise<boolean> {
  const value = token.trim()
  if (!value) {
    authError.value = 'Token is required'
    return false
  }
  authBusy.value = true
  authError.value = ''
  try {
    const resp = await fetch('/api/session', {
      method: 'POST',
      headers: { Authorization: `Bearer ${value}` },
    })
    if (!resp.ok) {
      authError.value = 'Invalid token'
      authenticated.value = false
      return false
    }
    authenticated.value = true
    clearTokenHash()
    await connect()
    return true
  } catch {
    authError.value = 'Backend is unavailable'
    authenticated.value = false
    return false
  } finally {
    authBusy.value = false
  }
}

async function loadConfig(): Promise<boolean> {
  if (configLoaded) return authenticated.value
  try {
    const resp = await fetch('/api/config')
    if (!resp.ok) throw new Error('config request failed')
    const cfg = await resp.json() as { auth_required?: boolean }
    authRequired.value = Boolean(cfg.auth_required)
    configLoaded = true
    if (!authRequired.value) {
      authenticated.value = true
      return true
    }
    if ((await fetch('/api/health')).ok) {
      authenticated.value = true
      return true
    }
    const hashToken = tokenFromHash()
    return hashToken ? authenticate(hashToken) : false
  } catch {
    authError.value = 'Backend is unavailable'
    return false
  }
}

function normalizeSettings(raw: unknown, baudrate = 115200): SerialSettings {
  const defaults = defaultSerialSettings()
  if (!raw || typeof raw !== 'object') return { ...defaults, baudrate }
  return { ...defaults, ...(raw as Partial<SerialSettings>), baudrate }
}

function normalizeLease(raw: unknown): PortLease | null {
  if (!raw || typeof raw !== 'object') return null
  const lease = raw as Partial<PortLease>
  if (typeof lease.port !== 'string' || typeof lease.owner_id !== 'string') return null
  return {
    port: lease.port,
    owner_id: lease.owner_id,
    owner_label: typeof lease.owner_label === 'string' ? lease.owner_label : lease.owner_id,
    expires_at: typeof lease.expires_at === 'number' ? lease.expires_at : 0,
  }
}

function normalizeOpenPorts(raw: unknown): OpenPortDetail[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item): OpenPortDetail[] => {
    if (typeof item === 'string') {
      return [{ port: item, baudrate: 115200, settings: defaultSerialSettings(), lease: null }]
    }
    if (!item || typeof item !== 'object') return []
    const candidate = item as Record<string, unknown>
    if (typeof candidate.port !== 'string') return []
    const baudrate = typeof candidate.baudrate === 'number' ? candidate.baudrate : 115200
    return [{
      port: candidate.port,
      baudrate,
      settings: normalizeSettings(candidate.settings, baudrate),
      lease: normalizeLease(candidate.lease),
    }]
  })
}

function appendSerialMessage(port: string, msg: SerialMessage) {
  if (!messages.value[port]) messages.value[port] = []
  const existing = messages.value[port]
  if (msg.sequence && existing.some(item => item.sequence === msg.sequence)) return
  existing.push(msg)
  if (existing.length > 5000) messages.value[port] = existing.slice(-3000)
  ensureCallbacks(port)
  callbacks[port].forEach(callback => callback(msg))
}

function appendRawChunk(port: string, chunk: SerialRawChunk) {
  if (!rawChunks.value[port]) rawChunks.value[port] = []
  const existing = rawChunks.value[port]
  if (chunk.sequence && existing.some(item => item.sequence === chunk.sequence)) return
  existing.push(chunk)
  if (existing.length > 5000) rawChunks.value[port] = existing.slice(-3000)
  ensureCallbacks(port)
  rawCallbacks[port].forEach(callback => callback(chunk))
}

function uint8ToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

function sendNextFileChunk(transfer: FileTransfer) {
  const socket = ws.value
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    transfer.reject(new Error('WebSocket disconnected'))
    transfers.delete(transfer.id)
    return
  }
  const end = Math.min(transfer.offset + FILE_CHUNK, transfer.bytes.length)
  transfer.pendingEnd = end
  sendCommand({
    action: 'send_file',
    port: transfer.port,
    transfer_id: transfer.id,
    sequence: transfer.sequence,
    data: uint8ToBase64(transfer.bytes.subarray(transfer.offset, end)),
    final: end === transfer.bytes.length,
  })
}

function handleFileAck(data: Record<string, unknown>) {
  const id = typeof data.transfer_id === 'string' ? data.transfer_id : ''
  const transfer = transfers.get(id)
  if (!transfer) return
  if (data.success !== true) {
    transfer.reject(new Error('Serial write failed'))
    transfers.delete(id)
    return
  }
  transfer.offset = transfer.pendingEnd
  transfer.onProgress?.(transfer.offset, transfer.bytes.length)
  if (data.complete === true || transfer.offset >= transfer.bytes.length) {
    transfer.resolve()
    transfers.delete(id)
    return
  }
  transfer.sequence += 1
  sendNextFileChunk(transfer)
}

async function connect(): Promise<void> {
  if (ws.value?.readyState === WebSocket.OPEN || connecting) return
  connecting = true
  if (!await loadConfig()) {
    connecting = false
    return
  }
  manualDisconnect = false
  const socket = new WebSocket(wsUrl())
  socket.onopen = () => {
    connecting = false
    reconnectAttempts = 0
    isConnected.value = true
    authenticated.value = true
    socket.send(JSON.stringify({ action: 'list_ports' }))
  }
  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>
      if (data.type === 'welcome') {
        clientId.value = typeof data.client_id === 'string' ? data.client_id : ''
        return
      }
      if (data.type === 'port_list' && Array.isArray(data.ports)) {
        ports.value = data.ports as SerialPort[]
        return
      }
      if (data.type === 'open_ports') {
        const list = normalizeOpenPorts(data.ports)
        openPorts.value = list.map(item => item.port)
        portBaudrates.value = Object.fromEntries(list.map(item => [item.port, item.baudrate]))
        portSettings.value = Object.fromEntries(list.map(item => [item.port, item.settings]))
        leases.value = Object.fromEntries(list.map(item => [item.port, item.lease]))
        isSerialOpen.value = Object.fromEntries(list.map(item => [item.port, true]))
        return
      }
      if (data.type === 'lease_status' && typeof data.port === 'string') {
        leases.value[data.port] = normalizeLease(data.lease)
        return
      }
      if (data.type === 'status' && typeof data.port === 'string') {
        isSerialOpen.value[data.port] = data.is_open === true
        return
      }
      if (data.type === 'file_ack') {
        handleFileAck(data)
        return
      }
      if (data.type === 'transfer_progress' && typeof data.transfer_id === 'string') {
        const transferId = data.transfer_id
        const state: ProtocolTransferState = {
          transferId,
          port: typeof data.port === 'string' ? data.port : '',
          protocol: (typeof data.protocol === 'string' ? data.protocol : 'xmodem') as ProtocolTransferState['protocol'],
          sent: typeof data.sent === 'number' ? data.sent : 0,
          total: typeof data.total === 'number' ? data.total : 0,
          block: typeof data.block === 'number' ? data.block : 0,
          retries: typeof data.retries === 'number' ? data.retries : 0,
          complete: data.complete === true,
          error: typeof data.error === 'string' ? data.error : '',
        }
        protocolTransfers.value[transferId] = state
        protocolProgressCallbacks.get(transferId)?.(state.sent, state.total)
        return
      }
      if (data.type === 'error') {
        protocolError.value = typeof data.code === 'string' ? data.code : String(data.message || 'error')
        if (data.code === 'lease.conflict' && typeof data.port === 'string') {
          leases.value[data.port] = normalizeLease(data.lease)
        }
        return
      }
      if (data.type === 'serial_raw' && typeof data.port === 'string') {
        appendRawChunk(data.port, {
          type: 'serial_raw',
          raw_hex: typeof data.raw_hex === 'string' ? data.raw_hex : '',
          sequence: typeof data.sequence === 'number' ? data.sequence : 0,
          timestamp: typeof data.timestamp === 'number' ? data.timestamp : Date.now() / 1000,
        })
        return
      }
      if (data.type === 'serial_message' && typeof data.port === 'string') {
        appendSerialMessage(data.port, {
          type: 'serial_message',
          source: data.source as SerialMessage['source'],
          content: typeof data.content === 'string' ? data.content : '',
          raw_hex: typeof data.raw_hex === 'string' ? data.raw_hex : '',
          sequence: typeof data.sequence === 'number' ? data.sequence : 0,
          event_code: typeof data.event_code === 'string' ? data.event_code : null,
          event_params: data.event_params && typeof data.event_params === 'object'
            ? data.event_params as SerialMessage['event_params']
            : {},
          timestamp: typeof data.timestamp === 'number' ? data.timestamp : Date.now() / 1000,
          time_str: typeof data.time_str === 'string' ? data.time_str : '',
        })
      }
    } catch (error) {
      console.error('WS parse error:', error)
    }
  }
  socket.onclose = (event) => {
    connecting = false
    isConnected.value = false
    clientId.value = ''
    ws.value = null
    for (const transfer of transfers.values()) transfer.reject(new Error('WebSocket disconnected'))
    transfers.clear()
    if (event.code === 1008) {
      authenticated.value = false
      authError.value = event.reason || 'Authentication or origin rejected'
      return
    }
    if (manualDisconnect) return
    reconnectAttempts += 1
    const delay = Math.min(1000 * 2 ** Math.min(reconnectAttempts - 1, 4), MAX_RECONNECT_DELAY)
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(() => { void connect() }, delay)
  }
  socket.onerror = (error) => console.error('WebSocket error:', error)
  ws.value = socket
}

function disconnect() {
  manualDisconnect = true
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = null
  reconnectAttempts = 0
  ws.value?.close()
  ws.value = null
  isConnected.value = false
}

function canWrite(port: string): boolean {
  const lease = leases.value[port]
  return !lease || lease.expires_at <= Date.now() / 1000 || lease.owner_id === clientId.value
}

function acquireLease(port: string, ttl = 30) {
  protocolError.value = ''
  sendCommand({ action: 'acquire_lease', port, ttl })
}

function releaseLease(port: string) {
  sendCommand({ action: 'release_lease', port })
}

function send(port: string, data: string, newline = '\r\n') {
  if (canWrite(port)) sendCommand({ action: 'write', port, data, newline })
}

function sendRaw(port: string, data: string) {
  if (!canWrite(port)) return
  const bytes = new TextEncoder().encode(data)
  sendCommand({ action: 'raw_write', port, data_b64: uint8ToBase64(bytes) })
}

function sendFile(port: string, data: ArrayBuffer, onProgress?: (sent: number, total: number) => void): FileTransferHandle {
  const bytes = new Uint8Array(data)
  if (!canWrite(port)) return { promise: Promise.reject(new Error('Write lease required')), cancel: () => {} }
  if (bytes.length === 0) return { promise: Promise.resolve(), cancel: () => {} }
  if (bytes.length > MAX_FILE_SIZE) {
    return { promise: Promise.reject(new Error('File exceeds 32 MiB limit')), cancel: () => {} }
  }
  const id = `${Date.now().toString(36)}-${crypto.randomUUID().replaceAll('-', '')}`
  let transfer: FileTransfer
  const promise = new Promise<void>((resolve, reject) => {
    transfer = { id, port, bytes, offset: 0, pendingEnd: 0, sequence: 0, onProgress, resolve, reject }
    transfers.set(id, transfer)
    sendNextFileChunk(transfer)
  })
  return {
    promise,
    cancel: () => {
      const active = transfers.get(id)
      if (!active) return
      sendCommand({ action: 'cancel_file', transfer_id: id })
      active.reject(new Error('Transfer cancelled'))
      transfers.delete(id)
    },
  }
}

function sendProtocolFile(
  port: string,
  data: ArrayBuffer,
  filename: string,
  protocol: Exclude<TransferProtocol, 'raw'>,
  onProgress?: (sent: number, total: number) => void,
): FileTransferHandle {
  if (!canWrite(port)) {
    return { promise: Promise.reject(new Error('Write lease required')), cancel: () => {} }
  }
  if (data.byteLength === 0) {
    return { promise: Promise.reject(new Error('File is empty')), cancel: () => {} }
  }
  if (data.byteLength > MAX_FILE_SIZE) {
    return { promise: Promise.reject(new Error('File exceeds 32 MiB limit')), cancel: () => {} }
  }

  const transferId = `web-${crypto.randomUUID().replaceAll('-', '')}`
  const controller = new AbortController()
  if (onProgress) protocolProgressCallbacks.set(transferId, onProgress)
  const params = new URLSearchParams({
    port,
    transfer_id: transferId,
    protocol,
    filename,
  })
  const promise = fetch(`/api/transfer/send?${params}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-AI-Serial-Client': clientId.value,
      'X-AI-Serial-Client-Label': 'Web UI',
    },
    body: data,
    signal: controller.signal,
  }).then(async response => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `Transfer failed: HTTP ${response.status}`)
    }
  }).finally(() => {
    protocolProgressCallbacks.delete(transferId)
  })

  return {
    promise,
    cancel: () => {
      const cancelParams = new URLSearchParams({ transfer_id: transferId })
      void fetch(`/api/transfer/cancel?${cancelParams}`, {
        method: 'POST',
        headers: {
          'X-AI-Serial-Client': clientId.value,
          'X-AI-Serial-Client-Label': 'Web UI',
        },
      }).finally(() => controller.abort())
    },
  }
}

function receiveProtocolFile(
  port: string,
  protocol: 'xmodem' | 'ymodem',
  expectedSize?: number,
  onProgress?: (received: number, total: number) => void,
): FileTransferHandle {
  const transferId = `web-rx-${crypto.randomUUID().replaceAll('-', '')}`
  const controller = new AbortController()
  if (onProgress) protocolProgressCallbacks.set(transferId, onProgress)
  const params = new URLSearchParams({ port, transfer_id: transferId, protocol })
  if (expectedSize !== undefined) params.set('expected_size', String(expectedSize))
  const promise = fetch(`/api/transfer/receive?${params}`, {
    method: 'POST',
    headers: {
      'X-AI-Serial-Client': clientId.value,
      'X-AI-Serial-Client-Label': 'Web UI',
    },
    signal: controller.signal,
  }).then(async response => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `Receive failed: HTTP ${response.status}`)
    }
    const data = await response.blob()
    const filename = response.headers.get('X-AI-Serial-Filename') || `${port}-${Date.now()}.${protocol}`
    downloadBlob(data, filename)
  }).finally(() => protocolProgressCallbacks.delete(transferId))
  return {
    promise,
    cancel: () => {
      const cancelParams = new URLSearchParams({ transfer_id: transferId })
      void fetch(`/api/transfer/cancel?${cancelParams}`, {
        method: 'POST',
        headers: { 'X-AI-Serial-Client': clientId.value },
      }).finally(() => controller.abort())
    },
  }
}

function receiveYmodemBatch(
  port: string,
  onProgress?: (received: number, total: number) => void,
): FileTransferHandle {
  const transferId = `web-rxb-${crypto.randomUUID().replaceAll('-', '')}`
  const controller = new AbortController()
  if (onProgress) protocolProgressCallbacks.set(transferId, onProgress)
  const params = new URLSearchParams({ port, transfer_id: transferId })
  const promise = fetch(`/api/transfer/receive-batch?${params}`, {
    method: 'POST',
    headers: {
      'X-AI-Serial-Client': clientId.value,
      'X-AI-Serial-Client-Label': 'Web UI',
    },
    signal: controller.signal,
  }).then(async response => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `Batch receive failed: HTTP ${response.status}`)
    }
    const archive = await response.blob()
    const disposition = response.headers.get('Content-Disposition') || ''
    const headerFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    const filename = headerFilename?.split(/[\\/]/).pop() || `ymodem-${port}-${Date.now()}-batch.zip`
    downloadBlob(archive, filename)
  }).finally(() => protocolProgressCallbacks.delete(transferId))
  return {
    promise,
    cancel: () => {
      const cancelParams = new URLSearchParams({ transfer_id: transferId })
      void fetch(`/api/transfer/cancel?${cancelParams}`, {
        method: 'POST',
        headers: { 'X-AI-Serial-Client': clientId.value },
      }).finally(() => controller.abort())
    },
  }
}

function downloadBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function openPort(port: string, settings: SerialSettings | number = defaultSerialSettings()) {
  const normalized = typeof settings === 'number'
    ? { ...defaultSerialSettings(), baudrate: settings }
    : settings
  sendCommand({ action: 'open', port, ...normalized })
}

function closePort(port: string) {
  if (canWrite(port)) sendCommand({ action: 'close', port })
}

function refreshPorts() {
  sendCommand({ action: 'list_ports' })
}

async function loadHistory(port: string, limit = 1000) {
  const resp = await fetch(`/api/history?port=${encodeURIComponent(port)}&limit=${limit}`)
  if (!resp.ok) return
  const history = await resp.json() as Omit<SerialMessage, 'type'>[]
  const combined = [
    ...history.map(item => ({ ...item, type: 'serial_message' as const })),
    ...(messages.value[port] || []),
  ]
  const unique = new Map<number, SerialMessage>()
  for (const item of combined) unique.set(item.sequence, item)
  messages.value[port] = [...unique.values()].sort((a, b) => a.sequence - b.sequence)
}

async function loadRawHistory(port: string, limit = 1000) {
  const resp = await fetch(`/api/raw-history?port=${encodeURIComponent(port)}&limit=${limit}`)
  if (!resp.ok) return
  const history = await resp.json() as Omit<SerialRawChunk, 'type'>[]
  const combined = [
    ...history.map(item => ({ ...item, type: 'serial_raw' as const })),
    ...(rawChunks.value[port] || []),
  ]
  const unique = new Map<number, SerialRawChunk>()
  for (const item of combined) unique.set(item.sequence, item)
  rawChunks.value[port] = [...unique.values()].sort((a, b) => a.sequence - b.sequence)
}

function onMessage(port: string, callback: (msg: SerialMessage) => void) {
  ensureCallbacks(port)
  callbacks[port].push(callback)
}

function offMessage(port: string, callback: (msg: SerialMessage) => void) {
  ensureCallbacks(port)
  const index = callbacks[port].indexOf(callback)
  if (index >= 0) callbacks[port].splice(index, 1)
}

function onRaw(port: string, callback: (chunk: SerialRawChunk) => void) {
  ensureCallbacks(port)
  rawCallbacks[port].push(callback)
}

function offRaw(port: string, callback: (chunk: SerialRawChunk) => void) {
  ensureCallbacks(port)
  const index = rawCallbacks[port].indexOf(callback)
  if (index >= 0) rawCallbacks[port].splice(index, 1)
}

function getHistory(port: string, limit = 1000): SerialMessage[] {
  const history = messages.value[port] || []
  return limit > 0 ? history.slice(-limit) : history.slice()
}

function getRawHistory(port: string, limit = 1000): SerialRawChunk[] {
  const history = rawChunks.value[port] || []
  return limit > 0 ? history.slice(-limit) : history.slice()
}

export function useSerial() {
  return {
    ws: readonly(ws),
    isConnected: readonly(isConnected),
    authRequired: readonly(authRequired),
    authenticated: readonly(authenticated),
    authBusy: readonly(authBusy),
    authError: readonly(authError),
    protocolError: readonly(protocolError),
    clientId: readonly(clientId),
    isSerialOpen: readonly(isSerialOpen),
    openPorts: readonly(openPorts),
    ports: readonly(ports),
    messages: readonly(messages),
    rawChunks: readonly(rawChunks),
    portBaudrates: readonly(portBaudrates),
    portSettings: readonly(portSettings),
    leases: readonly(leases),
    protocolTransfers: readonly(protocolTransfers),
    authenticate,
    connect,
    disconnect,
    canWrite,
    acquireLease,
    releaseLease,
    send,
    sendRaw,
    sendFile,
    sendProtocolFile,
    receiveProtocolFile,
    receiveYmodemBatch,
    openPort,
    closePort,
    refreshPorts,
    loadHistory,
    loadRawHistory,
    onMessage,
    offMessage,
    onRaw,
    offRaw,
    getHistory,
    getRawHistory,
  }
}
