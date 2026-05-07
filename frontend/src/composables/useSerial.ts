import { ref, onUnmounted } from 'vue'

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

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

export function useSerial() {
  const ws = ref<WebSocket | null>(null)
  const isConnected = ref(false)
  const isSerialOpen = ref<Record<string, boolean>>({})
  const openPorts = ref<string[]>([])
  const ports = ref<SerialPort[]>([])
  const messages = ref<Record<string, SerialMessage[]>>({})
  const reconnectTimer = ref<ReturnType<typeof setTimeout> | null>(null)

  // 按 port 分组的回调
  const callbacks: Record<string, ((msg: SerialMessage) => void)[]> = {}

  function ensureCallbacks(port: string) {
    if (!callbacks[port]) callbacks[port] = []
  }

  function connect() {
    if (ws.value?.readyState === WebSocket.OPEN) return

    const socket = new WebSocket(WS_URL)

    socket.onopen = () => {
      isConnected.value = true
      console.log('WebSocket connected')
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
          openPorts.value = data.ports || []
          // 同步 isSerialOpen
          const newState: Record<string, boolean> = {}
          for (const p of openPorts.value) newState[p] = true
          isSerialOpen.value = newState
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
      isConnected.value = false
      ws.value = null
      reconnectTimer.value = setTimeout(() => connect(), 2000)
    }

    socket.onerror = (err) => {
      console.error('WebSocket error:', err)
    }

    ws.value = socket
  }

  function disconnect() {
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }
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
    return messages.value[port] || []
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    ws,
    isConnected,
    isSerialOpen,
    openPorts,
    ports,
    messages,
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
