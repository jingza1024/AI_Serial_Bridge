<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import LogSessionList, { type LogSessionSummary } from './LogSessionList.vue'
import { useLocale } from '../composables/useLocale'

interface LogPort {
  port: string
  size: number
  updated_at: number
}

interface LogRecord {
  kind: 'message' | 'raw'
  source?: string
  content?: string
  raw_hex?: string
  timestamp: number
}

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useLocale()

const ports = ref<LogPort[]>([])
const sessions = ref<LogSessionSummary[]>([])
const records = ref<LogRecord[]>([])
const selectedPort = shallowRef('')
const selectedSessionId = shallowRef('')
const encrypted = shallowRef(false)
const loading = shallowRef(false)
const error = shallowRef('')
const offset = shallowRef(0)
const limit = 10
const total = shallowRef(0)

watch(() => props.visible, visible => {
  if (visible) void loadPorts()
})

async function loadPorts() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/logs')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const payload = await response.json() as { ports: LogPort[]; encrypted: boolean; error?: string }
    ports.value = payload.ports || []
    encrypted.value = payload.encrypted === true
    if (payload.error) error.value = payload.error
    if (!ports.value.some(item => item.port === selectedPort.value)) {
      selectedPort.value = ports.value[0]?.port || ''
    }
    offset.value = 0
    await loadSessions()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function loadSessions() {
  sessions.value = []
  records.value = []
  selectedSessionId.value = ''
  if (!selectedPort.value) {
    total.value = 0
    return
  }
  const response = await fetch(
    `/api/logs/${encodeURIComponent(selectedPort.value)}/sessions-page?offset=${offset.value}&limit=${limit}`,
  )
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const payload = await response.json() as {
    items: LogSessionSummary[]
    total: number
  }
  sessions.value = payload.items || []
  total.value = payload.total || 0
  if (sessions.value[0]) await selectSession(sessions.value[0])
}

async function changePort() {
  offset.value = 0
  loading.value = true
  error.value = ''
  try {
    await loadSessions()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function selectSession(session: LogSessionSummary) {
  selectedSessionId.value = session.session_id
  const params = new URLSearchParams({ limit: '10000', session_id: session.session_id })
  const response = await fetch(`/api/logs/${encodeURIComponent(selectedPort.value)}?${params}`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  records.value = await response.json() as LogRecord[]
}

async function changePage(nextOffset: number) {
  offset.value = Math.max(0, nextOffset)
  loading.value = true
  error.value = ''
  try {
    await loadSessions()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

function recordText(record: LogRecord) {
  const time = new Date(record.timestamp * 1000).toLocaleString()
  const body = record.kind === 'raw' ? record.raw_hex : record.content
  return `${time} [${record.source || record.kind}] ${body || ''}`
}
</script>

<template>
  <div v-if="props.visible" class="overlay" role="presentation" @click.self="emit('close')">
    <section class="dialog" role="dialog" aria-modal="true" :aria-label="t('logs.title')">
      <header class="dialog-header">
        <div>
          <h2>{{ t('logs.title') }}</h2>
          <span class="encryption" :class="{ active: encrypted }">
            {{ encrypted ? t('logs.encrypted') : t('logs.plaintext') }}
          </span>
        </div>
        <button type="button" class="close" :aria-label="t('app.cancel')" @click="emit('close')">×</button>
      </header>
      <div class="controls">
        <label>
          {{ t('logs.port') }}
          <select v-model="selectedPort" @change="changePort">
            <option v-for="item in ports" :key="item.port" :value="item.port">{{ item.port }}</option>
          </select>
        </label>
        <button type="button" @click="loadPorts">{{ t('logs.refresh') }}</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <div v-if="ports.length" class="browser-body" :class="{ loading }">
        <LogSessionList
          :sessions="sessions"
          :selected-id="selectedSessionId"
          :offset="offset"
          :limit="limit"
          :total="total"
          @select="selectSession"
          @previous="changePage(offset - limit)"
          @next="changePage(offset + limit)"
        />
        <pre class="records">{{ records.map(recordText).join('\n') || t('logs.noRecords') }}</pre>
      </div>
      <p v-else-if="!loading" class="empty">{{ t('logs.noSessions') }}</p>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  z-index: 1200;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: #010409cc;
}

.dialog {
  display: flex;
  flex-direction: column;
  width: min(1000px, 95vw);
  height: min(720px, 90vh);
  border: 1px solid #30363d;
  border-radius: 10px;
  background: #0d1117;
  color: #c9d1d9;
  box-shadow: 0 16px 48px #0009;
}

.dialog-header,
.controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #30363d;
}

.dialog-header h2 {
  display: inline;
  margin: 0 10px 0 0;
  font-size: 18px;
}

.encryption {
  color: #d29922;
  font-size: 12px;
}

.encryption.active {
  color: #3fb950;
}

.close,
.controls button,
.controls select {
  padding: 6px 10px;
  border: 1px solid #30363d;
  border-radius: 6px;
  background: #21262d;
  color: #c9d1d9;
}

.close {
  border: 0;
  background: transparent;
  font-size: 24px;
  cursor: pointer;
}

.controls label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.browser-body {
  display: grid;
  grid-template-columns: 260px 1fr;
  min-height: 0;
  flex: 1;
}

.browser-body.loading {
  opacity: 0.6;
}

.records {
  min-width: 0;
  margin: 0;
  padding: 14px;
  overflow: auto;
  color: #b1bac4;
  white-space: pre-wrap;
  word-break: break-word;
}

.error,
.empty {
  padding: 16px;
}

.error {
  color: #f85149;
}

@media (max-width: 700px) {
  .browser-body {
    grid-template-columns: 1fr;
  }
}
</style>
