<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import AuthDialog from './components/AuthDialog.vue'
import PortDialog from './components/PortDialog.vue'
import LogBrowserDialog from './components/LogBrowserDialog.vue'
import AutomationDialog from './components/automation/AutomationDialog.vue'
import TerminalPanel from './components/TerminalPanel.vue'
import { defaultSerialSettings, useSerial, type SerialSettings } from './composables/useSerial'
import { useLocale } from './composables/useLocale'
import { createSerialProfiles } from './composables/useSerialProfiles'

interface Tab {
  id: string
  port: string
  baudrate: number
  settings: SerialSettings
  label: string
}

const serial = useSerial()
const { t, locale } = useLocale()
const tabs = ref<Tab[]>([])
const activeTabId = shallowRef('')
const showNewTabModal = shallowRef(false)
const showLogBrowser = shallowRef(false)
const showAutomations = shallowRef(false)
const selectedPort = shallowRef('')
const selectedSettings = ref<SerialSettings>(defaultSerialSettings())
const selectedProfileName = shallowRef('')
const selectedAutoReconnect = shallowRef(false)
const profileStore = createSerialProfiles(localStorage)
const suppressedReconnect = new Set<string>()
const reconnectSchedule = new Map<string, { attempts: number, nextAt: number }>()

// 获取可用但尚未打开的串口（防呆）
const availablePorts = computed(() => {
  const openSet = new Set(tabs.value.map(t => t.port))
  return serial.ports.value.filter(p => !openSet.has(p.device))
})

// 当前激活的标签
const activeTab = computed(() => {
  return tabs.value.find(t => t.id === activeTabId.value)
})

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

function createTab(port: string, settings: SerialSettings, shouldOpen: boolean = true) {
  // 防呆：检查是否已存在该 port 的标签
  const existing = tabs.value.find(t => t.port === port)
  if (existing) {
    activeTabId.value = existing.id
    return
  }

  const tab: Tab = {
    id: generateId(),
    port,
    baudrate: settings.baudrate,
    settings: { ...settings },
    label: port,
  }
  tabs.value.push(tab)
  activeTabId.value = tab.id

  // 用户主动创建时才发 open 命令；WebSocket 同步时不重复 open
  if (shouldOpen) {
    setTimeout(() => {
      serial.openPort(port, settings)
    }, 100)
  }
}

function closeTab(tabId: string) {
  const idx = tabs.value.findIndex(t => t.id === tabId)
  if (idx < 0) return

  const tab = tabs.value[idx]
  const profile = profileStore.findForPort(tab.port, serial.ports.value)
  if (profile?.autoReconnect) suppressedReconnect.add(profile.id)

  // 关闭串口
  serial.closePort(tab.port)

  // 移除标签
  tabs.value.splice(idx, 1)

  // 切换激活标签
  if (activeTabId.value === tabId) {
    if (tabs.value.length > 0) {
      activeTabId.value = tabs.value[Math.min(idx, tabs.value.length - 1)].id
    } else {
      activeTabId.value = ''
    }
  }
}

function openNewTabModal() {
  selectedPort.value = availablePorts.value.length > 0 ? availablePorts.value[0].device : ''
  loadSelectedProfile(selectedPort.value)
  showNewTabModal.value = true
}

function confirmNewTab() {
  if (!selectedPort.value) return
  const profile = profileStore.saveForPort(
    selectedPort.value,
    serial.ports.value,
    selectedProfileName.value,
    selectedSettings.value,
    selectedAutoReconnect.value,
  )
  suppressedReconnect.delete(profile.id)
  createTab(selectedPort.value, selectedSettings.value)
  showNewTabModal.value = false
}

function cancelNewTab() {
  showNewTabModal.value = false
}

// 关键：监听后端已打开的串口列表，自动同步标签页
// AI 通过 MCP 打开/关闭串口后，WebSocket 会推送 open_ports 消息
watch(() => [...serial.openPorts.value], (newPorts) => {
  const tabPorts = new Set(tabs.value.map(t => t.port))

  // 1) 后端有但 UI 没有 -> 自动创建标签（不重复发送 open 命令）
  //    使用后端实际打开时使用的波特率，而非写死 115200
  for (const port of newPorts) {
    if (!tabPorts.has(port)) {
      createTab(
        port,
        serial.portSettings.value[port] ?? {
          ...defaultSerialSettings(),
          baudrate: serial.portBaudrates.value[port] ?? 115200,
        },
        false,
      )
    }
  }

  // 2) UI 有但后端已关闭 -> 自动移除标签
  const openSet = new Set(newPorts)
  for (let i = tabs.value.length - 1; i >= 0; i--) {
    if (!openSet.has(tabs.value[i].port)) {
      tabs.value.splice(i, 1)
    }
  }

  // 3) 当前激活标签被移除时，切到最后一个
  if (activeTabId.value && !tabs.value.find(t => t.id === activeTabId.value)) {
    activeTabId.value = tabs.value.length > 0 ? tabs.value[tabs.value.length - 1].id : ''
  }
}, { immediate: true })

// 组件挂载时连接 WebSocket
serial.connect()

watch(selectedPort, port => {
  if (showNewTabModal.value) loadSelectedProfile(port)
})

function loadSelectedProfile(port: string) {
  const profile = port ? profileStore.findForPort(port, serial.ports.value) : undefined
  selectedSettings.value = { ...(profile?.settings || defaultSerialSettings()) }
  selectedProfileName.value = profile?.name || port
  selectedAutoReconnect.value = profile?.autoReconnect || false
}

watch(
  [() => serial.isConnected.value, () => [...serial.ports.value], () => [...serial.openPorts.value]],
  ([connected]) => {
    if (!connected) return
    const now = Date.now()
    for (const target of profileStore.autoReconnectTargets(serial.ports.value, serial.openPorts.value)) {
      if (suppressedReconnect.has(target.profile.id)) continue
      const state = reconnectSchedule.get(target.profile.id) || { attempts: 0, nextAt: 0 }
      if (state.nextAt > now) continue
      serial.openPort(target.port, target.profile.settings)
      const attempts = state.attempts + 1
      reconnectSchedule.set(target.profile.id, {
        attempts,
        nextAt: now + Math.min(1000 * 2 ** Math.min(attempts - 1, 4), 10000),
      })
    }
    for (const port of serial.openPorts.value) {
      const profile = profileStore.findForPort(port, serial.ports.value)
      if (profile) reconnectSchedule.delete(profile.id)
    }
  },
  { immediate: true },
)

const portRefreshTimer = setInterval(() => {
  if (serial.isConnected.value) serial.refreshPorts()
}, 3000)

onUnmounted(() => clearInterval(portRefreshTimer))

function authenticate(token: string) {
  void serial.authenticate(token)
}
</script>

<template>
  <div class="app">
    <AuthDialog
      :visible="serial.authRequired.value && !serial.authenticated.value"
      :busy="serial.authBusy.value"
      :error="serial.authError.value"
      @submit="authenticate"
    />
    <!-- 顶部栏 -->
    <header class="app-header">
      <div class="logo">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14"/>
          <path d="M12 5l7 7-7 7"/>
        </svg>
        <h1>AI Serial Bridge</h1>
      </div>
      <div class="header-right">
        <span class="ws-status" :class="{ active: serial.isConnected.value }">
          WS: {{ serial.isConnected.value ? t('app.wsConnected') : t('app.wsDisconnected') }}
        </span>
        <button class="lang-btn" @click="showLogBrowser = true">{{ t('logs.open') }}</button>
        <button class="lang-btn" @click="showAutomations = true">{{ t('automations.open') }}</button>
        <button class="lang-btn" @click="locale = locale === 'zh' ? 'en' : 'zh'">
          {{ locale === 'zh' ? t('app.en') : t('app.zh') }}
        </button>
      </div>
    </header>

    <!-- 标签栏 -->
    <div class="tab-bar" role="tablist" :aria-label="t('app.serialTabs')">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="tab"
        :class="{ active: activeTabId === tab.id }"
        role="tab"
        :aria-selected="activeTabId === tab.id"
        :tabindex="activeTabId === tab.id ? 0 : -1"
        @click="activeTabId = tab.id"
        @keydown.enter="activeTabId = tab.id"
        @keydown.space.prevent="activeTabId = tab.id"
      >
        <span class="tab-label">{{ tab.label }}</span>
        <button
          type="button"
          class="tab-close"
          @click.stop="closeTab(tab.id)"
          :title="t('app.closeTabTooltip')"
          :aria-label="`${t('app.closeTabTooltip')}: ${tab.label}`"
        >
          x
        </button>
      </div>

      <button
        class="tab-add"
        @click="openNewTabModal"
        :title="t('app.newTab')"
        :disabled="availablePorts.length === 0 && serial.ports.value.length === 0"
      >
        +
      </button>
    </div>

    <!-- 终端内容区 -->
    <main class="app-main">
      <template v-if="tabs.length > 0">
        <div
          v-for="tab in tabs"
          :key="tab.id"
          class="tab-panel"
          :class="{ hidden: activeTabId !== tab.id }"
          role="tabpanel"
        >
          <TerminalPanel
            :port="tab.port"
            @close="closeTab(tab.id)"
          />
        </div>
      </template>
      <div v-else class="empty-state">
        <div class="empty-content">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14"/>
            <path d="M12 5l7 7-7 7"/>
          </svg>
          <p>{{ t('app.noPortOpen') }}</p>
          <button class="btn btn-primary" @click="openNewTabModal">+ {{ t('app.newTab') }}</button>
        </div>
      </div>
    </main>

    <PortDialog
      v-model:port="selectedPort"
      v-model:settings="selectedSettings"
      v-model:profile-name="selectedProfileName"
      v-model:auto-reconnect="selectedAutoReconnect"
      :visible="showNewTabModal"
      :ports="availablePorts"
      :detected-count="serial.ports.value.length"
      @confirm="confirmNewTab"
      @cancel="cancelNewTab"
    />
    <LogBrowserDialog :visible="showLogBrowser" @close="showLogBrowser = false" />
    <AutomationDialog
      :visible="showAutomations"
      :client-id="serial.clientId.value"
      @close="showAutomations = false"
    />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background-color: #0d1117;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background-color: #161b22;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #58a6ff;
}

.logo h1 {
  font-size: 18px;
  font-weight: 600;
  color: #e6edf3;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ws-status {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  background-color: #21262d;
  color: #8b949e;
  border: 1px solid #30363d;
}

.ws-status.active {
  background-color: #23863633;
  color: #3fb950;
  border-color: #238636;
}

.lang-btn {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  background-color: #21262d;
  color: #c9d1d9;
  border: 1px solid #30363d;
  cursor: pointer;
}

.lang-btn:hover {
  background-color: #30363d;
}

/* 标签栏 */
.tab-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px 0;
  background-color: #161b22;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
  overflow-x: auto;
}

.tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background-color: #21262d;
  color: #8b949e;
  border: 1px solid #30363d;
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  min-width: 80px;
}

.tab:hover {
  background-color: #30363d;
  color: #c9d1d9;
}

.tab.active {
  background-color: #0d1117;
  color: #e6edf3;
  border-color: #30363d;
  border-bottom: 1px solid #0d1117;
  margin-bottom: -1px;
}

.tab-label {
  flex: 1;
}

.tab-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  font-size: 12px;
  color: #8b949e;
  cursor: pointer;
  border: 0;
  background: transparent;
}

.tab-close:hover {
  background-color: #da3633;
  color: #fff;
}

.tab-add {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid #30363d;
  border-radius: 6px;
  background-color: #21262d;
  color: #c9d1d9;
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
}

.tab-add:hover:not(:disabled) {
  background-color: #30363d;
}

.tab-add:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 主内容区 */
.app-main {
  flex: 1;
  overflow: hidden;
  position: relative;
}

.tab-panel {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
}

.tab-panel.hidden {
  display: none;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: #8b949e;
}

.empty-content svg {
  color: #30363d;
}

.btn {
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 500;
}

.btn-primary {
  background-color: #238636;
  color: #fff;
}

.btn-primary:hover {
  background-color: #2ea043;
}

.btn-secondary {
  background-color: #21262d;
  color: #c9d1d9;
  border: 1px solid #30363d;
}

.btn-secondary:hover {
  background-color: #30363d;
}

</style>
