import { ref } from 'vue'

export interface SerialMessage {
  type: string
  source: 'user' | 'ai' | 'device' | 'system'
  content: string
  timestamp: number
  time_str: string
}

export interface SerialPort {
  device: string
  description: string
  hwid: string
}

/**
 * 关键设计：所有响应式状态与 WebSocket 连接位于 *模块级*，被全部组件共享。
 * 早期版本在 useSerial() 函数体内创建状态，导致每个终端面板各开一条 WS 连接、
 * 历史与打开状态彼此不同步。现在整个应用只有一条 WS、一份状态。
 */

const ws = ref<WebSocket | null>(null)
const isConnected = ref(false)
const isSerialOpen = ref<Record<string, boolean>>({})
const openPorts = ref<string[]>([])
const ports = ref<SerialPort[]>([])
const messages = ref<Record<string, SerialMessage[]>>({})
const portBaudrates = ref<Record<string, number>>({})

// 按 port 分组的回调（显示用）
const callbacks: Record<string, ((msg: SerialMessage) => void)[]> = {}

let _token = ''
let _configLoaded = false
let _connecting = false
let _reconnectAttempts = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

const MAX_RECONNECT_DELAY = 10000

function ensureCallbacks(port: string) {
  if (!callbacks[port]) callbacks[port] = []
}

function _wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const base = `${proto}://${window.location.host}/ws`
  return _token ? `${base}?token=${encodeURIComponent(_token)}` : base
}

async function _loadToken() {
  try {
    const resp = await fetch('/api/config')
    const cfg = await resp.json()
    _token = cfg?.token || ''
  } catch {
    _token = ''
  }
}

function connect() {
  // 异步加载 token 后再建立连接（返回 Promise 便于调用方按需 await）
  return (async () => {
    if (ws.value?.readyState === WebSocket.OPEN) return
    if (_connecting) return
    if (!_configLoaded) {
      await _loadToken()
      _configLoaded = true
    }

    _connecting = true
    const socket = new WebSocket(_wsUrl())

    socket.onopen = () => {
      _connecting = false
      _reconnectAttempts = 0
      isConnected.value = true
      socket.send(JSON.stringify({ action: 'list_ports' }))
    }

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'port_list' && data.ports) {
          ports.value = data.ports
          return
        }

        if (data.type === 'open_ports') {
          // 兼容两种形态：["COM3"] 或 [{port:"COM3", baudrate:115200}]
          const raw: any[] = data.ports || []
          const list = raw.map((p: any) =>
            typeof p === 'string' ? { port: p, baudrate: 115200 } : { port: p.port, baudrate: p.baudrate ?? 115200 }
          )
          openPorts.value = list.map(p => p.port)
          const baudMap: Record<string, number> = {}
          const stateMap: Record<string, boolean> = {}
          for (const p of list) {
            baudMap[p.port] = p.baudrate
            stateMap[p.port] = true
          }
          portBaudrates.value = baudMap
          isSerialOpen.value = stateMap
          return
        }

        if (data.type === 'status') {
          const port = data.port
          if (port) {
            isSerialOpen.value[port] = data.is_open || false
          }
          return
        }

        if (data.type === 'serial_message') {
          const port = data.port || 'default'
          const msg: SerialMessage = {
            type: data.type,
            source: data.source,
            content: data.content,
            timestamp: data.timestamp,
            time_str: data.time_str,
          }
          if (!messages.value[port]) messages.value[port] = []
          messages.value[port].push(msg)
          // 限制历史记录数量
          if (messages.value[port].length > 5000) {
            messages.value[port] = messages.value[port].slice(-3000)
          }
          ensureCallbacks(port)
          callbacks[port].forEach(cb => cb(msg))
        }
      } catch (e) {
        console.error('WS parse error:', e)
      }
    }

    socket.onclose = () => {
      _connecting = false
      isConnected.value = false
      ws.value = null
      // 指数退避重连，封顶 10s
      _reconnectAttempts += 1
      const delay = Math.min(1000 * 2 ** Math.min(_reconnectAttempts - 1, 4), MAX_RECONNECT_DELAY)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      reconnectTimer = setTimeout(() => { connect() }, delay)
    }

    socket.onerror = (err) => {
      console.error('WebSocket error:', err)
    }

    ws.value = socket
  })()
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  _reconnectAttempts = 0
  ws.value?.close()
  ws.value = null
  isConnected.value = false
}

function send(port: string, data: string, source: 'user' | 'ai' = 'user', newline: string = '\r\n') {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ action: 'write', port, data, source, newline }))
  }
}

function sendRaw(port: string, data: string) {
  // 原始按键透传（交互模式），data 包含控制字符如 \r, \t, \x1b 等
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ action: 'raw_write', port, data }))
  }
}

function openPort(port: string, baudrate: number) {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ action: 'open', port, baudrate }))
  }
}

function closePort(port: string) {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ action: 'close', port }))
  }
  // 本地清理
  delete messages.value[port]
  delete isSerialOpen.value[port]
  delete portBaudrates.value[port]
  const idx = openPorts.value.indexOf(port)
  if (idx >= 0) openPorts.value.splice(idx, 1)
  delete callbacks[port]
}

function refreshPorts() {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ action: 'list_ports' }))
  }
}

function onMessage(port: string, callback: (msg: SerialMessage) => void) {
  ensureCallbacks(port)
  callbacks[port].push(callback)
}

function offMessage(port: string, callback: (msg: SerialMessage) => void) {
  ensureCallbacks(port)
  const idx = callbacks[port].indexOf(callback)
  if (idx >= 0) callbacks[port].splice(idx, 1)
}

function getHistory(port: string, limit: number = 1000): SerialMessage[] {
  const arr = messages.value[port] || []
  return limit && limit > 0 ? arr.slice(-limit) : arr.slice()
}

export function useSerial() {
  return {
    ws,
    isConnected,
    isSerialOpen,
    openPorts,
    ports,
    messages,
    portBaudrates,
    connect,
    disconnect,
    send,
    sendRaw,
    openPort,
    closePort,
    refreshPorts,
    onMessage,
    offMessage,
    getHistory,
  }
}
