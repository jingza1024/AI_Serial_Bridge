<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import TerminalPanel from './components/TerminalPanel.vue'
import { useSerial } from './composables/useSerial'

interface Tab {
  id: string
  port: string
  baudrate: number
  label: string
}

const serial = useSerial()
const tabs = ref<Tab[]>([])
const activeTabId = ref<string>('')
const showNewTabModal = ref(false)
const selectedPort = ref('')
const selectedBaudrate = ref(115200)

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
  return Date.now().toString(36) + Math.random().toString(36).substr(2, 5)
}

function createTab(port: string, baudrate: number) {
  // 防呆：检查是否已存在该 port 的标签
  const existing = tabs.value.find(t => t.port === port)
  if (existing) {
    activeTabId.value = existing.id
    return
  }

  const tab: Tab = {
    id: generateId(),
    port,
    baudrate,
    label: port,
  }
  tabs.value.push(tab)
  activeTabId.value = tab.id

  // 自动连接串口
  setTimeout(() => {
    serial.openPort(port, baudrate)
  }, 100)
}

function closeTab(tabId: string) {
  const idx = tabs.value.findIndex(t => t.id === tabId)
  if (idx < 0) return

  const tab = tabs.value[idx]

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
  selectedBaudrate.value = 115200
  showNewTabModal.value = true
}

function confirmNewTab() {
  if (!selectedPort.value) return
  createTab(selectedPort.value, selectedBaudrate.value)
  showNewTabModal.value = false
}

function cancelNewTab() {
  showNewTabModal.value = false
}

// 监听串口列表变化，刷新可用端口
watch(() => serial.ports.value.length, () => {
  // 自动刷新可用端口
})

// 组件挂载时连接 WebSocket
serial.connect()
</script>

<template>
  <div class="app">
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
          WS: {{ serial.isConnected.value ? '已连接' : '未连接' }}
        </span>
      </div>
    </header>

    <!-- 标签栏 -->
    <div class="tab-bar">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="tab"
        :class="{ active: activeTabId === tab.id }"
        @click="activeTabId = tab.id"
      >
        <span class="tab-label">{{ tab.label }}</span>
        <span
          class="tab-close"
          @click.stop="closeTab(tab.id)"
          title="关闭标签并断开串口"
        >
          x
        </span>
      </div>

      <button
        class="tab-add"
        @click="openNewTabModal"
        title="新建标签"
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
          <p>暂无打开的串口</p>
          <button class="btn btn-primary" @click="openNewTabModal">+ 新建标签</button>
        </div>
      </div>
    </main>

    <!-- 新建标签弹窗 -->
    <div v-if="showNewTabModal" class="modal-overlay" @click.self="cancelNewTab">
      <div class="modal">
        <div class="modal-header">
          <h3>新建串口标签</h3>
          <button class="modal-close" @click="cancelNewTab">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>串口</label>
            <select v-model="selectedPort" class="select">
              <option value="" disabled>选择串口</option>
              <option
                v-for="p in availablePorts"
                :key="p.device"
                :value="p.device"
              >
                {{ p.device }} {{ p.description ? `- ${p.description}` : '' }}
              </option>
            </select>
            <p v-if="availablePorts.length === 0 && serial.ports.value.length > 0" class="form-hint warn">
              所有可用串口已打开，请先关闭某个标签
            </p>
            <p v-else-if="serial.ports.value.length === 0" class="form-hint">
              未检测到可用串口，请检查设备连接
            </p>
          </div>

          <div class="form-group">
            <label>波特率</label>
            <select v-model="selectedBaudrate" class="select">
              <option :value="9600">9600</option>
              <option :value="19200">19200</option>
              <option :value="38400">38400</option>
              <option :value="57600">57600</option>
              <option :value="115200">115200</option>
              <option :value="230400">230400</option>
              <option :value="460800">460800</option>
              <option :value="921600">921600</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancelNewTab">取消</button>
          <button
            class="btn btn-primary"
            :disabled="!selectedPort"
            @click="confirmNewTab"
          >
            打开串口
          </button>
        </div>
      </div>
    </div>
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

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background-color: #161b22;
  border: 1px solid #30363d;
  border-radius: 10px;
  width: 420px;
  max-width: 90vw;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #30363d;
}

.modal-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #e6edf3;
  margin: 0;
}

.modal-close {
  background: none;
  border: none;
  color: #8b949e;
  font-size: 22px;
  cursor: pointer;
  padding: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}

.modal-close:hover {
  background-color: #30363d;
  color: #e6edf3;
}

.modal-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 13px;
  color: #8b949e;
}

.select {
  padding: 8px 12px;
  background-color: #0d1117;
  color: #c9d1d9;
  border: 1px solid #30363d;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
}

.select:focus {
  border-color: #58a6ff;
}

.form-hint {
  font-size: 12px;
  color: #8b949e;
  margin: 0;
}

.form-hint.warn {
  color: #f85149;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 20px 16px;
  border-top: 1px solid #30363d;
}
</style>
