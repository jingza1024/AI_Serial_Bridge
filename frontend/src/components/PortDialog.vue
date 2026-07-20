<script setup lang="ts">
import { nextTick, useTemplateRef, watch } from 'vue'
import type { SerialPort, SerialSettings } from '../composables/useSerial'
import { useLocale } from '../composables/useLocale'

const props = defineProps<{
  visible: boolean
  ports: readonly SerialPort[]
  detectedCount: number
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const port = defineModel<string>('port', { required: true })
const settings = defineModel<SerialSettings>('settings', { required: true })
const profileName = defineModel<string>('profileName', { required: true })
const autoReconnect = defineModel<boolean>('autoReconnect', { required: true })
const portSelect = useTemplateRef<HTMLSelectElement>('portSelect')
const { t } = useLocale()

watch(() => props.visible, async (visible) => {
  if (!visible) return
  await nextTick()
  portSelect.value?.focus()
}, { immediate: true })
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <form
      class="modal"
      role="dialog"
      aria-modal="true"
      :aria-label="t('app.newTabTitle')"
      @submit.prevent="emit('confirm')"
    >
      <div class="modal-header">
        <h3>{{ t('app.newTabTitle') }}</h3>
        <button type="button" class="modal-close" :aria-label="t('app.cancel')" @click="emit('cancel')">
          &times;
        </button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="port-select">{{ t('app.port') }}</label>
          <select id="port-select" ref="portSelect" v-model="port" class="select">
            <option value="" disabled>{{ t('app.selectPort') }}</option>
            <option v-for="item in ports" :key="item.device" :value="item.device">
              {{ item.device }} {{ item.description ? `- ${item.description}` : '' }}
            </option>
          </select>
          <p v-if="ports.length === 0 && detectedCount > 0" class="form-hint warn">
            {{ t('app.allPortsOpen') }}
          </p>
          <p v-else-if="detectedCount === 0" class="form-hint">
            {{ t('app.noPortDetected') }}
          </p>
        </div>

        <div class="profile-row">
          <div class="form-group profile-name">
            <label for="profile-name">{{ t('app.profileName') }}</label>
            <input id="profile-name" v-model="profileName" class="select" maxlength="64" />
          </div>
          <label class="auto-reconnect">
            <input v-model="autoReconnect" type="checkbox" />
            {{ t('app.autoReconnect') }}
          </label>
        </div>

        <div class="form-group">
          <label for="baudrate-select">{{ t('app.baudrate') }}</label>
          <select id="baudrate-select" v-model="settings.baudrate" class="select">
            <option v-for="value in [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]" :key="value" :value="value">
              {{ value }}
            </option>
          </select>
        </div>

        <div class="settings-grid">
          <div class="form-group">
            <label for="bytesize-select">{{ t('app.bytesize') }}</label>
            <select id="bytesize-select" v-model="settings.bytesize" class="select">
              <option v-for="value in [5, 6, 7, 8]" :key="value" :value="value">{{ value }}</option>
            </select>
          </div>
          <div class="form-group">
            <label for="parity-select">{{ t('app.parity') }}</label>
            <select id="parity-select" v-model="settings.parity" class="select">
              <option v-for="value in ['N', 'E', 'O', 'M', 'S']" :key="value" :value="value">{{ value }}</option>
            </select>
          </div>
          <div class="form-group">
            <label for="stopbits-select">{{ t('app.stopbits') }}</label>
            <select id="stopbits-select" v-model="settings.stopbits" class="select">
              <option v-for="value in [1, 1.5, 2]" :key="value" :value="value">{{ value }}</option>
            </select>
          </div>
          <div class="form-group">
            <label for="dtr-select">DTR</label>
            <select id="dtr-select" v-model="settings.dtr" class="select">
              <option :value="null">{{ t('app.auto') }}</option>
              <option :value="true">On</option>
              <option :value="false">Off</option>
            </select>
          </div>
          <div class="form-group">
            <label for="rts-select">RTS</label>
            <select id="rts-select" v-model="settings.rts" class="select">
              <option :value="null">{{ t('app.auto') }}</option>
              <option :value="true">On</option>
              <option :value="false">Off</option>
            </select>
          </div>
        </div>

        <fieldset class="flow-control">
          <legend>{{ t('app.flowControl') }}</legend>
          <label><input v-model="settings.xonxoff" type="checkbox" /> XON/XOFF</label>
          <label><input v-model="settings.rtscts" type="checkbox" /> RTS/CTS</label>
          <label><input v-model="settings.dsrdtr" type="checkbox" /> DSR/DTR</label>
        </fieldset>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" @click="emit('cancel')">{{ t('app.cancel') }}</button>
        <button type="submit" class="btn btn-primary" :disabled="!port">{{ t('app.openPort') }}</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: rgba(0, 0, 0, 0.6);
}

.modal {
  width: 520px;
  max-width: 90vw;
  border: 1px solid #30363d;
  border-radius: 10px;
  background-color: #161b22;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.modal-header,
.modal-footer {
  display: flex;
  align-items: center;
  padding: 16px 20px;
}

.modal-header {
  justify-content: space-between;
  border-bottom: 1px solid #30363d;
}

.modal-header h3 {
  margin: 0;
  color: #e6edf3;
  font-size: 16px;
}

.modal-close {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: #8b949e;
  font-size: 22px;
  cursor: pointer;
}

.modal-close:hover {
  background-color: #30363d;
  color: #e6edf3;
}

.modal-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.profile-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.profile-name {
  flex: 1;
}

.auto-reconnect {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  color: #8b949e;
  font-size: 12px;
}

.auto-reconnect input {
  accent-color: #58a6ff;
}

.flow-control {
  display: flex;
  gap: 16px;
  margin: 0;
  padding: 12px;
  border: 1px solid #30363d;
  border-radius: 6px;
  color: #8b949e;
  font-size: 12px;
}

.flow-control label {
  display: flex;
  align-items: center;
  gap: 5px;
}

.flow-control input {
  accent-color: #58a6ff;
}

@media (max-width: 560px) {
  .settings-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .flow-control {
    flex-wrap: wrap;
  }
}

.form-group label,
.form-hint {
  margin: 0;
  color: #8b949e;
  font-size: 12px;
}

.form-hint.warn {
  color: #f85149;
}

.select {
  padding: 8px 12px;
  border: 1px solid #30363d;
  border-radius: 6px;
  outline: none;
  background-color: #0d1117;
  color: #c9d1d9;
  font-size: 14px;
}

.select:focus {
  border-color: #58a6ff;
}

.modal-footer {
  justify-content: flex-end;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid #30363d;
}

.btn {
  padding: 8px 20px;
  border: 0;
  border-radius: 6px;
  font-size: 14px;
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

.btn-secondary {
  border: 1px solid #30363d;
  background-color: #21262d;
  color: #c9d1d9;
}
</style>
