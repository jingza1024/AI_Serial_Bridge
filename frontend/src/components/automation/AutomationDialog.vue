<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useLocale } from '../../composables/useLocale'
import {
  createAutomationsClient,
  type DiagnosticSchedule,
  type HealthRule,
  type MacroDefinition,
} from '../../composables/useAutomations'
import MacroPanel from './MacroPanel.vue'
import HealthStatusPanel from './HealthStatusPanel.vue'
import SchedulePanel from './SchedulePanel.vue'

const props = defineProps<{ visible: boolean; clientId: string }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useLocale()
const activePanel = shallowRef<'macros' | 'health' | 'schedules'>('macros')
const client = createAutomationsClient(fetch, undefined, () => props.clientId)

async function refresh() {
  try {
    await client.load()
  } catch {
    // The client exposes the translated server error for the dialog.
  }
}

function runAction(action: () => Promise<unknown>) {
  void action().catch(() => undefined)
}

function saveMacro(macro: MacroDefinition) { runAction(() => client.saveMacro(macro)) }
function deleteMacro(id: string) { runAction(() => client.deleteMacro(id)) }
function runMacro(id: string, port: string) { runAction(() => client.runMacro(id, port)) }
function cancelMacro(id: string) { runAction(() => client.cancelMacro(id)) }
function saveRule(rule: HealthRule) { runAction(() => client.saveRule(rule)) }
function deleteRule(id: string) { runAction(() => client.deleteRule(id)) }
function saveSchedule(schedule: DiagnosticSchedule) { runAction(() => client.saveSchedule(schedule)) }
function deleteSchedule(id: string) { runAction(() => client.deleteSchedule(id)) }

watch(() => props.visible, visible => {
  if (visible) void refresh()
}, { immediate: true })
</script>

<template>
  <div v-if="props.visible" class="overlay" role="presentation" @click.self="emit('close')">
    <section class="dialog" role="dialog" aria-modal="true" :aria-label="t('automations.title')">
      <header class="dialog-header">
        <h2>{{ t('automations.title') }}</h2>
        <button
          type="button"
          class="close"
          data-testid="automation-close"
          :aria-label="t('automations.close')"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <nav class="tabs" :aria-label="t('automations.title')">
        <button type="button" :class="{ active: activePanel === 'macros' }" @click="activePanel = 'macros'">{{ t('automations.macros') }}</button>
        <button type="button" :class="{ active: activePanel === 'health' }" @click="activePanel = 'health'">{{ t('automations.health') }}</button>
        <button type="button" :class="{ active: activePanel === 'schedules' }" @click="activePanel = 'schedules'">{{ t('automations.schedules') }}</button>
        <button type="button" class="refresh" :disabled="client.busy.value" @click="refresh">{{ t('automations.refresh') }}</button>
      </nav>

      <p v-if="client.error.value" class="error" role="alert">{{ client.error.value }}</p>
      <p v-if="client.busy.value" class="loading" aria-live="polite">{{ t('automations.loading') }}</p>

      <main class="panel-body">
        <MacroPanel
          v-if="activePanel === 'macros'"
          :macros="client.macros.value"
          :runs="client.runs.value"
          :active-runs="client.activeRuns.value"
          :busy="client.busy.value"
          @save="saveMacro"
          @delete="deleteMacro"
          @run="runMacro"
          @cancel="cancelMacro"
        />
        <HealthStatusPanel
          v-else-if="activePanel === 'health'"
          :rules="client.rules.value"
          :events="client.healthEvents.value"
          :busy="client.busy.value"
          @save="saveRule"
          @delete="deleteRule"
          @refresh="refresh"
        />
        <SchedulePanel
          v-else
          :schedules="client.schedules.value"
          :macros="client.macros.value"
          :status="client.scheduleStatus.value"
          :busy="client.busy.value"
          @save="saveSchedule"
          @delete="deleteSchedule"
          @refresh="refresh"
        />
      </main>
    </section>
  </div>
</template>

<style scoped>
.overlay { position: fixed; z-index: 1200; inset: 0; display: grid; place-items: center; padding: 24px; background: #010409cc; }
.dialog { display: flex; flex-direction: column; width: min(1180px, 96vw); height: min(760px, 92vh); border: 1px solid #30363d; border-radius: 10px; background: #0d1117; color: #c9d1d9; box-shadow: 0 16px 48px #0009; }
.dialog-header, .tabs { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid #30363d; }
.dialog-header { justify-content: space-between; }.dialog-header h2 { margin: 0; font-size: 18px; }
.close, .tabs button { padding: 6px 10px; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; cursor: pointer; }
.close { border: 0; background: transparent; font-size: 24px; }.tabs button.active { border-color: #58a6ff; color: #58a6ff; }.tabs .refresh { margin-left: auto; }
.tabs button:disabled { cursor: not-allowed; opacity: .5; }.error, .loading { margin: 0; padding: 8px 16px; }.error { color: #ff7b72; }.loading { color: #d29922; }
.panel-body { min-height: 0; flex: 1; }
@media (max-width: 700px) { .overlay { padding: 8px; }.dialog { width: 100%; height: 96vh; }.tabs { overflow-x: auto; } }
</style>
