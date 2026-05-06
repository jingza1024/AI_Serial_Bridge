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
  const isSerialOpen = ref(false)
  const currentPort = ref<string | null>(null)
  const currentBaudrate = ref<number | null>(null)
  const ports = ref<SerialPort[]>([])
  const messages = ref<SerialMessage[]>([])
  const reconnectTimer = ref<ReturnType<typeof setTimeout> | null>(null)

  const callbacks: ((msg: SerialMessage) => void)[] = []

  function connect() {
    if (ws.value?.readyState === WebSocket.OPEN) return

    const socket = new WebSocket(WS_URL)

    socket.onopen = () => {
      isConnected.value = true
      console.log('WebSocket connected')
      // 请求端口列表
      socket.send(JSON.stringify({ action: 'list_ports' }))
    }

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SerialMessage | { type: string; ports?: SerialPort[]; is_open?: boolean; port?: string; baudrate?: number }

        if (data.type === 'port_list' && 'ports' in data) {
          ports.value = data.ports || []
          return
        }

        if (data.type === 'status') {
          isSerialOpen.value = (data as any).is_open || false
          currentPort.value = (data as any).port || null
          currentBaudrate.value = (data as any).baudrate || null
          return
        }

        if (data.type === 'serial_message') {
          const msg = data as SerialMessage
          messages.value.push(msg)
          // 限制历史记录数量
          if (messages.value.length > 5000) {
            messages.value = messages.value.slice(-3000)
          }
          callbacks.forEach(cb => cb(msg))
        }
      } catch (e) {
        console.error('WS parse error:', e)
      }
    }

    socket.onclose = () => {
      isConnected.value = false
      ws.value = null
      // 自动重连
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

  function send(data: string, source: 'user' | 'ai' = 'user', newline: string = '\r\n') {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ action: 'write', data, source, newline }))
    }
  }

  function sendRaw(data: string) {
    // 原始按键透传（交互模式），data 包含控制字符如 \r, \t, \x1b 等
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ action: 'raw_write', data }))
    }
  }

  function openPort(port: string, baudrate: number) {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ action: 'open', port, baudrate }))
    }
  }

  function closePort() {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ action: 'close' }))
    }
  }

  function refreshPorts() {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ action: 'list_ports' }))
    }
  }

  function onMessage(callback: (msg: SerialMessage) => void) {
    callbacks.push(callback)
  }

  function offMessage(callback: (msg: SerialMessage) => void) {
    const idx = callbacks.indexOf(callback)
    if (idx >= 0) callbacks.splice(idx, 1)
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    ws,
    isConnected,
    isSerialOpen,
    currentPort,
    currentBaudrate,
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
  }
}
