<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, useTemplateRef, watch } from 'vue'
import type { Terminal } from '@xterm/xterm'
import TerminalToolbar from './TerminalToolbar.vue'
import { useSerial, type SerialMessage, type SerialRawChunk, type TransferProtocol } from '../composables/useSerial'
import { useLocale } from '../composables/useLocale'
import { useTerminalSession } from '../composables/useTerminalSession'
import '@xterm/xterm/css/xterm.css'

const props = defineProps<{ port: string }>()
const emit = defineEmits<{ close: [port: string] }>()
const serial = useSerial()
const { t } = useLocale()

const terminalRef = useTemplateRef<HTMLDivElement>('terminalRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')
const interactiveMode = shallowRef(true)
const localEcho = shallowRef(false)
const autoScroll = shallowRef(true)
const showAiLog = shallowRef(true)
const hexMode = shallowRef(false)
const sendingFile = shallowRef(false)
const sendProgress = shallowRef(0)
const fileProtocol = shallowRef<TransferProtocol>('raw')
const inputText = ref('')
const newlineMode = ref('\r\n')

const settings = computed(() => serial.portSettings.value[props.port])
const baudrate = computed(() => settings.value?.baudrate ?? 115200)
const lease = computed(() => serial.leases.value[props.port] ?? null)
const ownsLease = computed(() => Boolean(lease.value && lease.value.owner_id === serial.clientId.value))
const canWrite = computed(() => serial.canWrite(props.port))
const leaseOwner = computed(() => lease.value?.owner_label || lease.value?.owner_id || '')

let term: Terminal | null = null
const terminalSession = useTerminalSession()
let cancelFileTransfer: (() => void) | null = null
let progressResetTimer: ReturnType<typeof setTimeout> | null = null
let keyBufferTimer: ReturnType<typeof setTimeout> | null = null

function formatHex(hex: string): string {
  return (hex.match(/.{1,2}/g) || []).map(value => value.toUpperCase()).join(' ')
}

function eventText(msg: SerialMessage): string {
  if (!msg.event_code) return msg.content
  const translated = t(`events.${msg.event_code}`, msg.event_params)
  return translated === `events.${msg.event_code}` ? msg.event_code : translated
}

function scrollToBottom() {
  if (autoScroll.value) term?.scrollToBottom()
}

function appendRaw(chunk: SerialRawChunk) {
  if (!term || !hexMode.value) return
  const body = formatHex(chunk.raw_hex)
  if (body) term.write(`\x1b[38;2;139;233;253m${body} \x1b[0m`)
  scrollToBottom()
}

function appendInteractiveMessage(msg: SerialMessage) {
  if (!term) return
  if (msg.source === 'device') {
    if (!hexMode.value) term.write(msg.content)
  } else if (msg.source === 'system') {
    term.write(`\r\n\x1b[90m[${t('terminal.system')}] ${eventText(msg)}\x1b[0m\r\n`)
  } else if (msg.source === 'ai' && showAiLog.value) {
    term.write(`\r\n\x1b[94m[${t('terminal.ai')}] ${msg.content}\x1b[0m\r\n`)
  }
  scrollToBottom()
}

function appendMessage(msg: SerialMessage) {
  if (interactiveMode.value) {
    appendInteractiveMessage(msg)
    return
  }
  if (!term || (msg.source === 'device' && hexMode.value)) return
  const time = `[${msg.time_str}] `
  const reset = '\x1b[0m'
  let line = ''
  if (msg.source === 'device') {
    line = `\x1b[38;2;134;239;172m${time}${msg.content}${reset}`
  } else if (msg.source === 'user') {
    line = `\r\n\x1b[38;2;250;204;21m${time}[${t('terminal.user')}] ${msg.content}${reset}\r\n`
  } else if (msg.source === 'ai') {
    line = `\r\n\x1b[38;2;96;165;250m${time}[${t('terminal.ai')}] ${msg.content}${reset}\r\n`
  } else {
    line = `\r\n\x1b[38;2;156;163;175m${time}[${t('terminal.system')}] ${eventText(msg)}${reset}\r\n`
  }
  term.write(line)
  scrollToBottom()
}

function clearTerminal() {
  term?.clear()
  term?.write(`\x1b[90m--- ${t('terminal.cleared')} ---\x1b[0m\r\n`)
}

function sendInput() {
  const text = inputText.value.trim()
  if (!text || !canWrite.value) return
  serial.send(props.port, text, newlineMode.value)
  inputText.value = ''
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendInput()
  }
}

async function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  sendingFile.value = true
  sendProgress.value = 0
  const data = await file.arrayBuffer()
  const transfer = fileProtocol.value === 'raw'
    ? serial.sendFile(props.port, data, (sent, total) => {
      sendProgress.value = total > 0 ? Math.round((sent / total) * 100) : 100
    })
    : serial.sendProtocolFile(props.port, data, file.name, fileProtocol.value, (sent, total) => {
      sendProgress.value = total > 0 ? Math.round((sent / total) * 100) : 100
    })
  cancelFileTransfer = transfer.cancel
  try {
    await transfer.promise
    sendProgress.value = 100
    progressResetTimer = setTimeout(() => { sendProgress.value = 0 }, 1500)
  } catch (error) {
    term?.write(`\r\n\x1b[31m[${t('terminal.system')}] ${error instanceof Error ? error.message : String(error)}\x1b[0m\r\n`)
  } finally {
    sendingFile.value = false
    cancelFileTransfer = null
    input.value = ''
  }
}

function handleFileButton() {
  if (sendingFile.value) cancelFileTransfer?.()
  else fileInputRef.value?.click()
}

async function handleReceiveButton() {
  if (fileProtocol.value !== 'xmodem' && fileProtocol.value !== 'ymodem') return
  sendingFile.value = true
  sendProgress.value = 0
  const transfer = serial.receiveProtocolFile(props.port, fileProtocol.value, undefined, (received, total) => {
    sendProgress.value = total > 0 ? Math.round((received / total) * 100) : 0
  })
  cancelFileTransfer = transfer.cancel
  try {
    await transfer.promise
    sendProgress.value = 100
  } catch (error) {
    term?.write(`\r\n\x1b[31m[${t('terminal.system')}] ${error instanceof Error ? error.message : String(error)}\x1b[0m\r\n`)
  } finally {
    sendingFile.value = false
    cancelFileTransfer = null
  }
}

async function handleBatchReceiveButton() {
  sendingFile.value = true
  sendProgress.value = 0
  const transfer = serial.receiveYmodemBatch(props.port, (received, total) => {
    sendProgress.value = total > 0 ? Math.round((received / total) * 100) : 0
  })
  cancelFileTransfer = transfer.cancel
  try {
    await transfer.promise
    sendProgress.value = 100
  } catch (error) {
    term?.write(`\r\n\x1b[31m[${t('terminal.system')}] ${error instanceof Error ? error.message : String(error)}\x1b[0m\r\n`)
  } finally {
    sendingFile.value = false
    cancelFileTransfer = null
  }
}

async function exportLog() {
  if (hexMode.value) {
    await serial.loadRawHistory(props.port, 10000)
    const text = serial.getRawHistory(props.port, 0)
      .map(chunk => `${chunk.timestamp.toFixed(3)} ${formatHex(chunk.raw_hex)}`)
      .join('\n')
    if (text) downloadLog(text, 'hex.log')
    return
  }
  await serial.loadHistory(props.port, 10000)
  const history = serial.getHistory(props.port, 0)
  if (!history.length) return
  const text = history.map(message => {
    const tag = message.source === 'device' ? '[DEV]' : message.source === 'user' ? '[USR]' : message.source === 'ai' ? '[AI ]' : '[SYS]'
    let content = (message.source === 'system' ? eventText(message) : message.content)
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
    if (!content.endsWith('\n')) content += '\n'
    return `${message.time_str} ${tag} ${content}`
  }).join('')
  downloadLog(text, 'log')
}

function downloadLog(text: string, extension: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.port}-${Date.now()}.${extension}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  if (!terminalRef.value) return
  term = terminalSession.mount(terminalRef.value, {
    fontSize: 14,
    fontFamily: 'Consolas, "Courier New", monospace',
    theme: { background: '#161b22', foreground: '#c9d1d9', cursor: '#58a6ff' },
    cursorBlink: true,
    scrollback: 10000,
    convertEol: false,
    cursorStyle: 'block',
    tabStopWidth: 4,
  })
  term.write(`\x1b[90m--- ${props.port} ${t('terminal.ready')} ---\x1b[0m\r\n`)
  term.write(`\x1b[90m${t('terminal.waiting')}\x1b[0m\r\n`)

  watch(interactiveMode, value => {
    if (term) term.options = { ...term.options, disableStdin: !value }
  }, { immediate: true })

  let keyBuffer = ''
  const flushKeyBuffer = () => {
    if (keyBuffer && canWrite.value) serial.sendRaw(props.port, keyBuffer)
    keyBuffer = ''
    keyBufferTimer = null
  }
  term.onData((data) => {
    if (!interactiveMode.value || !serial.isSerialOpen.value[props.port] || !canWrite.value) return
    if (localEcho.value) term?.write(data)
    keyBuffer += data
    if (keyBufferTimer) clearTimeout(keyBufferTimer)
    keyBufferTimer = setTimeout(flushKeyBuffer, 5)
  })

  serial.onMessage(props.port, appendMessage)
  serial.onRaw(props.port, appendRaw)
  if (!serial.isConnected.value) void serial.connect()
  onUnmounted(() => {
    serial.offMessage(props.port, appendMessage)
    serial.offRaw(props.port, appendRaw)
    if (keyBufferTimer) clearTimeout(keyBufferTimer)
    if (progressResetTimer) clearTimeout(progressResetTimer)
    cancelFileTransfer?.()
    term = null
  })
})

watch(() => serial.messages.value[props.port]?.length, (newLength, oldLength) => {
  if (oldLength === 0 && newLength && newLength > 0) term?.clear()
})
</script>

<template>
  <div class="terminal-panel">
    <TerminalToolbar
      :port="props.port"
      :baudrate="baudrate"
      :is-open="Boolean(serial.isSerialOpen.value[props.port])"
      :can-write="canWrite"
      :has-lease="Boolean(lease)"
      :owns-lease="ownsLease"
      :lease-owner="leaseOwner"
      :interactive-mode="interactiveMode"
      :local-echo="localEcho"
      :hex-mode="hexMode"
      :sending-file="sendingFile"
      :send-progress="sendProgress"
      :has-messages="Boolean(serial.messages.value[props.port]?.length || serial.rawChunks.value[props.port]?.length)"
      :file-protocol="fileProtocol"
      @close="emit('close', props.port)"
      @acquire-lease="serial.acquireLease(props.port)"
      @release-lease="serial.releaseLease(props.port)"
      @clear="clearTerminal"
      @file="handleFileButton"
      @receive="handleReceiveButton"
      @receive-batch="handleBatchReceiveButton"
      @export="exportLog"
      @update:interactive-mode="interactiveMode = $event"
      @update:local-echo="localEcho = $event"
      @update:hex-mode="hexMode = $event"
      @update:file-protocol="fileProtocol = $event"
    />

    <div ref="terminalRef" class="terminal-container"></div>

    <div v-if="!canWrite" class="read-only-banner">
      {{ t('terminal.writeLeaseRequired') }}
    </div>

    <div v-if="!interactiveMode" class="input-bar">
      <select v-model="newlineMode" class="select" :title="t('terminal.newline')">
        <option :value="'\r\n'">CRLF (\r\n)</option>
        <option :value="'\n'">LF (\n)</option>
        <option :value="'\r'">CR (\r)</option>
        <option :value="''">None</option>
      </select>
      <input
        v-model="inputText"
        type="text"
        class="input"
        :placeholder="t('terminal.inputPlaceholder')"
        :disabled="!serial.isSerialOpen.value[props.port] || !canWrite"
        @keydown="handleKeydown"
      />
      <button
        class="btn btn-primary"
        :disabled="!serial.isSerialOpen.value[props.port] || !canWrite || !inputText.trim()"
        @click="sendInput"
      >
        {{ t('terminal.send') }}
      </button>
    </div>

    <div v-else class="hint-bar">
      <span class="hint">
        {{ t('terminal.interactiveHint') }}
        <template v-if="localEcho"> | {{ t('terminal.localEchoOn') }}</template>
      </span>
      <label class="checkbox">
        <input v-model="showAiLog" type="checkbox" />
        {{ t('terminal.showAiLog') }}
      </label>
    </div>
    <input ref="fileInputRef" type="file" class="hidden-file-input" @change="onFilePicked" />
  </div>
</template>

<style scoped>
.terminal-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
}

.terminal-container {
  flex: 1;
  overflow: hidden;
  background-color: #161b22;
}

.read-only-banner {
  padding: 6px 16px;
  border-top: 1px solid #9e6a03;
  background-color: #9e6a0333;
  color: #d29922;
  font-size: 12px;
}

.input-bar,
.hint-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid #30363d;
  background-color: #161b22;
}

.hint-bar {
  justify-content: space-between;
  padding-block: 8px;
}

.select,
.input {
  padding: 8px 12px;
  border: 1px solid #30363d;
  border-radius: 6px;
  outline: none;
  background-color: #0d1117;
  color: #c9d1d9;
}

.select {
  width: 110px;
}

.input {
  flex: 1;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 14px;
}

.input:focus,
.select:focus {
  border-color: #58a6ff;
}

.btn {
  padding: 8px 20px;
  border: 0;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.btn:disabled,
.input:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.btn-primary {
  background-color: #238636;
  color: #fff;
}

.hint,
.checkbox {
  color: #8b949e;
  font-size: 12px;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.checkbox input {
  accent-color: #58a6ff;
}

.hidden-file-input {
  display: none;
}
</style>
