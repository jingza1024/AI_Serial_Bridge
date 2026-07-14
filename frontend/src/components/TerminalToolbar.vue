<script setup lang="ts">
import { useLocale } from '../composables/useLocale'
import type { TransferProtocol } from '../composables/useSerial'

const props = defineProps<{
  port: string
  baudrate: number
  isOpen: boolean
  canWrite: boolean
  hasLease: boolean
  ownsLease: boolean
  leaseOwner: string
  interactiveMode: boolean
  localEcho: boolean
  hexMode: boolean
  sendingFile: boolean
  sendProgress: number
  hasMessages: boolean
  fileProtocol: TransferProtocol
}>()

const emit = defineEmits<{
  close: []
  acquireLease: []
  releaseLease: []
  clear: []
  file: []
  receive: []
  receiveBatch: []
  export: []
  'update:interactiveMode': [value: boolean]
  'update:localEcho': [value: boolean]
  'update:hexMode': [value: boolean]
  'update:fileProtocol': [value: TransferProtocol]
}>()

const { t } = useLocale()
</script>

<template>
  <div class="toolbar">
    <div class="toolbar-group">
      <span class="port-label">{{ props.port }}</span>
      <span class="status-badge" :class="{ active: props.isOpen }">
        {{ props.isOpen ? `${t('terminal.connected')} @ ${props.baudrate}` : t('terminal.notOpen') }}
      </span>
      <button
        v-if="props.isOpen && props.canWrite"
        class="btn btn-danger"
        @click="emit('close')"
      >
        {{ t('terminal.closePort') }}
      </button>
    </div>

    <div class="toolbar-group">
      <span class="lease-badge" :class="{ writer: props.canWrite }">
        {{ props.ownsLease
          ? t('terminal.writer')
          : props.hasLease
            ? t('terminal.leaseOwner', { owner: props.leaseOwner })
            : t('terminal.writeAvailable') }}
      </span>
      <button
        v-if="props.ownsLease"
        class="btn btn-secondary"
        @click="emit('releaseLease')"
      >
        {{ t('terminal.releaseLease') }}
      </button>
      <button
        v-else
        class="btn btn-primary"
        @click="emit('acquireLease')"
      >
        {{ t('terminal.acquireLease') }}
      </button>
    </div>

    <div class="toolbar-group">
      <button
        class="btn"
        :class="props.interactiveMode ? 'btn-primary' : 'btn-secondary'"
        @click="emit('update:interactiveMode', true)"
      >
        {{ t('terminal.interactiveMode') }}
      </button>
      <button
        class="btn"
        :class="!props.interactiveMode ? 'btn-primary' : 'btn-secondary'"
        @click="emit('update:interactiveMode', false)"
      >
        {{ t('terminal.commandMode') }}
      </button>
      <label v-if="props.interactiveMode" class="checkbox" :title="t('terminal.localEchoTooltip')">
        <input
          :checked="props.localEcho"
          type="checkbox"
          @change="emit('update:localEcho', ($event.target as HTMLInputElement).checked)"
        />
        {{ t('terminal.localEcho') }}
      </label>
      <button class="btn btn-secondary" @click="emit('clear')">{{ t('terminal.clear') }}</button>
    </div>

    <div class="toolbar-group">
      <button
        class="btn"
        :class="props.hexMode ? 'btn-primary' : 'btn-secondary'"
        :title="t('terminal.hexViewTooltip')"
        @click="emit('update:hexMode', !props.hexMode)"
      >
        {{ t('terminal.hexView') }}
      </button>
      <select
        class="protocol-select"
        :value="props.fileProtocol"
        :title="t('terminal.transferProtocol')"
        @change="emit('update:fileProtocol', ($event.target as HTMLSelectElement).value as TransferProtocol)"
      >
        <option value="raw">RAW</option>
        <option value="xmodem">XMODEM</option>
        <option value="xmodem1k">XMODEM-1K</option>
        <option value="ymodem">YMODEM</option>
      </select>
      <button
        class="btn btn-secondary"
        :disabled="!props.isOpen || !props.canWrite"
        @click="emit('file')"
      >
        {{ props.sendingFile ? t('terminal.cancelSending', { p: props.sendProgress }) : t('terminal.sendFile') }}
      </button>
      <button
        class="btn btn-secondary"
        :disabled="!props.isOpen || !props.canWrite || props.fileProtocol === 'raw' || props.fileProtocol === 'xmodem1k'"
        @click="emit('receive')"
      >
        {{ t('terminal.receiveFile') }}
      </button>
      <button
        v-if="props.fileProtocol === 'ymodem'"
        class="btn btn-secondary"
        :disabled="!props.isOpen || !props.canWrite"
        @click="emit('receiveBatch')"
      >
        {{ t('terminal.receiveBatch') }}
      </button>
      <button class="btn btn-secondary" :disabled="!props.hasMessages" @click="emit('export')">
        {{ t('terminal.exportLog') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid #30363d;
  background-color: #161b22;
  flex-wrap: wrap;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.port-label,
.status-badge,
.lease-badge {
  padding: 4px 10px;
  border: 1px solid #30363d;
  border-radius: 12px;
  background-color: #21262d;
  color: #8b949e;
  font-size: 12px;
}

.port-label {
  border-radius: 6px;
  color: #58a6ff;
  font-size: 14px;
  font-weight: 600;
}

.status-badge.active,
.lease-badge.writer {
  border-color: #238636;
  background-color: #23863633;
  color: #3fb950;
}

.btn {
  padding: 6px 14px;
  border: 0;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.btn-primary {
  background-color: #238636;
  color: #fff;
}

.btn-danger {
  background-color: #da3633;
  color: #fff;
}

.btn-secondary {
  border: 1px solid #30363d;
  background-color: #21262d;
  color: #c9d1d9;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #8b949e;
  font-size: 12px;
  cursor: pointer;
}

.checkbox input {
  accent-color: #58a6ff;
}

.protocol-select {
  padding: 6px 8px;
  border: 1px solid #30363d;
  border-radius: 6px;
  outline: none;
  background-color: #21262d;
  color: #c9d1d9;
  font-size: 12px;
}
</style>
