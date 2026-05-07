<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import { WebLinksAddon } from 'xterm-addon-web-links'
import { useSerial, type SerialMessage } from '../composables/useSerial'
import 'xterm/css/xterm.css'

const props = defineProps<{
  port: string
}>()

const emit = defineEmits<{
  (e: 'close', port: string): void
}>()

const terminalRef = ref<HTMLDivElement | null>(null)
const serial = useSerial()

let term: Terminal | null = null
let fitAddon: FitAddon | null = null

const baudrate = ref(115200)
const interactiveMode = ref(true)
const localEcho = ref(false)
const autoScroll = ref(true)
const showAiLog = ref(true)

const inputText = ref('')
const newlineMode = ref('\r\n')

// 交互模式：直接透传显示
function appendInteractiveMessage(msg: SerialMessage) {
  if (!term) return

  if (msg.source === 'device') {
    term.write(msg.content)
    if (autoScroll.value) term.scrollToBottom()
  } else if (msg.source === 'system') {
    term.write(`\r\n\x1b[90m[系统] ${msg.content}\x1b[0m\r\n`)
    if (autoScroll.value) term.scrollToBottom()
  } else if (msg.source === 'ai' && showAiLog.value) {
    term.write(`\r\n\x1b[94m[AI] ${msg.content}\x1b[0m\r\n`)
    if (autoScroll.value) term.scrollToBottom()
  }
}

function appendMessage(msg: SerialMessage) {
  if (interactiveMode.value) {
    appendInteractiveMessage(msg)
  } else {
    // 命令模式日志
    if (!term) return
    const time = `[${msg.time_str}] `
    const reset = '\x1b[0m'
    let line = ''
    if (msg.source === 'device') {
      line = `\x1b[38;2;134;239;172m${time}${msg.content}${reset}`
    } else if (msg.source === 'user') {
      line = `\r\n\x1b[38;2;250;204;21m${time}[用户] ${msg.content}${reset}\r\n`
    } else if (msg.source === 'ai') {
      line = `\r\n\x1b[38;2;96;165;250m${time}[AI] ${msg.content}${reset}\r\n`
    } else {
      line = `\r\n\x1b[38;2;156;163;175m${time}[系统] ${msg.content}${reset}\r\n`
    }
    term.write(line)
    if (autoScroll.value) term.scrollToBottom()
  }
}

function clearTerminal() {
  if (term) {
    term.clear()
    if (interactiveMode.value) {
      term.write('\x1b[90m--- 终端已清空 ---\x1b[0m\r\n')
    } else {
      term.write('\x1b[38;2;156;163;175m--- 终端已清空 ---\x1b[0m\r\n')
    }
  }
}

function sendInput() {
  const text = inputText.value.trim()
  if (!text) return
  serial.send(props.port, text, 'user', newlineMode.value)
  inputText.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendInput()
  }
}

function handleOpen() {
  serial.openPort(props.port, baudrate.value)
}

function handleClose() {
  serial.closePort(props.port)
  emit('close', props.port)
}

// 初始化 xterm
onMounted(() => {
  if (!terminalRef.value) return

  term = new Terminal({
    fontSize: 14,
    fontFamily: 'Consolas, "Courier New", monospace',
    theme: {
      background: '#161b22',
      foreground: '#c9d1d9',
      cursor: '#58a6ff',
    },
    cursorBlink: true,
    scrollback: 10000,
    allowTransparency: false,
    convertEol: false,
    cursorStyle: 'block',
    tabStopWidth: 4,
  })

  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.loadAddon(new WebLinksAddon())

  term.open(terminalRef.value)
  fitAddon.fit()

  term.write(`\x1b[90m--- ${props.port} 终端已就绪 ---\x1b[0m\r\n`)
  term.write('\x1b[90m等待串口连接...\x1b[0m\r\n')

  // 交互模式：监听按键直接透传串口
  let keyBuffer = ''
  let keyBufferTimer: ReturnType<typeof setTimeout> | null = null
  const flushKeyBuffer = () => {
    if (keyBuffer) {
      serial.sendRaw(props.port, keyBuffer)
      keyBuffer = ''
    }
    keyBufferTimer = null
  }

  term.onData((data) => {
    if (!term) return
    if (!interactiveMode.value) return
    if (!serial.isSerialOpen.value[props.port]) return

    if (localEcho.value) {
      term.write(data)
    }

    keyBuffer += data
    if (keyBufferTimer) clearTimeout(keyBufferTimer)
    keyBufferTimer = setTimeout(flushKeyBuffer, 5)
  })

  // 连接 WebSocket（全局只连一次）
  if (!serial.isConnected.value) {
    serial.connect()
  }

  // 注册消息回调（只接收本 port 的消息）
  serial.onMessage(props.port, appendMessage)

  // 窗口大小调整
  const handleResize = () => {
    fitAddon?.fit()
  }
  window.addEventListener('resize', handleResize)

  onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
    serial.offMessage(props.port, appendMessage)
    term?.dispose()
    term = null
  })
})

// 首次收到数据清空提示
watch(() => serial.messages.value[props.port]?.length, (newLen, oldLen) => {
  if (oldLen === 0 && newLen && newLen > 0 && term) {
    term.clear()
  }
})
</script>

<template>
  <div class="terminal-panel">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-group">
        <span class="port-label">{{ props.port }}</span>

        <select v-model="baudrate" class="select" :disabled="serial.isSerialOpen.value[props.port]">
          <option :value="9600">9600</option>
          <option :value="19200">19200</option>
          <option :value="38400">38400</option>
          <option :value="57600">57600</option>
          <option :value="115200">115200</option>
          <option :value="230400">230400</option>
          <option :value="460800">460800</option>
          <option :value="921600">921600</option>
        </select>

        <button
          v-if="!serial.isSerialOpen.value[props.port]"
          class="btn btn-primary"
          @click="handleOpen"
        >
          打开串口
        </button>
        <button
          v-else
          class="btn btn-danger"
          @click="handleClose"
        >
          关闭串口
        </button>
      </div>

      <div class="toolbar-group">
        <span class="status-badge" :class="{ active: serial.isSerialOpen.value[props.port] }">
          {{ serial.isSerialOpen.value[props.port] ? `已连接 @ ${baudrate}` : '未打开' }}
        </span>
      </div>

      <div class="toolbar-group">
        <button
          class="btn"
          :class="interactiveMode ? 'btn-primary' : 'btn-secondary'"
          @click="interactiveMode = true"
        >
          交互模式
        </button>
        <button
          class="btn"
          :class="!interactiveMode ? 'btn-primary' : 'btn-secondary'"
          @click="interactiveMode = false"
        >
          命令模式
        </button>

        <label v-if="interactiveMode" class="checkbox" title="设备不回显时开启">
          <input v-model="localEcho" type="checkbox" />
          本地回显
        </label>

        <button class="btn btn-secondary" @click="clearTerminal">清空</button>
      </div>
    </div>

    <!-- 终端区域 -->
    <div ref="terminalRef" class="terminal-container"></div>

    <!-- 底部命令栏（仅命令模式显示） -->
    <div v-if="!interactiveMode" class="input-bar">
      <select v-model="newlineMode" class="select" title="换行符">
        <option value="\r\n">CRLF (\r\n)</option>
        <option value="\n">LF (\n)</option>
        <option value="\r">CR (\r)</option>
        <option value="">无</option>
      </select>
      <input
        v-model="inputText"
        type="text"
        class="input"
        placeholder="输入命令发送给串口... (Enter发送)"
        :disabled="!serial.isSerialOpen.value[props.port]"
        @keydown="handleKeydown"
      />
      <button
        class="btn btn-primary"
        :disabled="!serial.isSerialOpen.value[props.port] || !inputText.trim()"
        @click="sendInput"
      >
        发送
      </button>
    </div>

    <!-- 底部提示栏（仅交互模式显示） -->
    <div v-else class="hint-bar">
      <span class="hint">
        交互模式：直接在终端输入，Tab 补全、方向键、Ctrl+C 等均支持
        <template v-if="localEcho"> | 本地回显已开启</template>
      </span>
      <label class="checkbox">
        <input v-model="showAiLog" type="checkbox" />
        显示AI操作
      </label>
    </div>
  </div>
</template>

<style scoped>
.terminal-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  background-color: #161b22;
  border-bottom: 1px solid #30363d;
  flex-wrap: wrap;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.port-label {
  font-size: 14px;
  font-weight: 600;
  color: #58a6ff;
  padding: 4px 10px;
  background-color: #21262d;
  border-radius: 6px;
  border: 1px solid #30363d;
}

.select {
  padding: 6px 10px;
  background-color: #21262d;
  color: #c9d1d9;
  border: 1px solid #30363d;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  min-width: 100px;
}

.select:focus {
  border-color: #58a6ff;
}

.btn {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.2s;
  font-weight: 500;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background-color: #238636;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background-color: #2ea043;
}

.btn-danger {
  background-color: #da3633;
  color: #fff;
}

.btn-danger:hover:not(:disabled) {
  background-color: #f85149;
}

.btn-secondary {
  background-color: #21262d;
  color: #c9d1d9;
  border: 1px solid #30363d;
}

.btn-secondary:hover:not(:disabled) {
  background-color: #30363d;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  background-color: #21262d;
  color: #8b949e;
  border: 1px solid #30363d;
}

.status-badge.active {
  background-color: #23863633;
  color: #3fb950;
  border-color: #238636;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #8b949e;
  cursor: pointer;
}

.checkbox input {
  accent-color: #58a6ff;
}

.terminal-container {
  flex: 1;
  overflow: hidden;
  background-color: #161b22;
}

.input-bar {
  display: flex;
  gap: 8px;
  padding: 10px 16px;
  background-color: #161b22;
  border-top: 1px solid #30363d;
  align-items: center;
}

.input-bar .select {
  min-width: auto;
  width: 110px;
}

.input {
  flex: 1;
  padding: 8px 12px;
  background-color: #0d1117;
  color: #c9d1d9;
  border: 1px solid #30363d;
  border-radius: 6px;
  font-size: 14px;
  font-family: 'Consolas', 'Courier New', monospace;
  outline: none;
}

.input:focus {
  border-color: #58a6ff;
}

.input:disabled {
  opacity: 0.5;
}

.hint-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 16px;
  background-color: #161b22;
  border-top: 1px solid #30363d;
}

.hint {
  font-size: 12px;
  color: #8b949e;
}
</style>
