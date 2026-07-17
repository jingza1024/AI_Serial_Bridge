<script setup lang="ts">
import { ref } from 'vue'
import { useLocale } from '../../composables/useLocale'
import type { DiagnosticSchedule, MacroDefinition, ScheduleState } from '../../composables/useAutomations'

const props = defineProps<{
  schedules: DiagnosticSchedule[]
  macros: MacroDefinition[]
  status: Record<string, ScheduleState>
  busy: boolean
}>()
const emit = defineEmits<{ save: [schedule: DiagnosticSchedule]; delete: [scheduleId: string]; refresh: [] }>()
const { t } = useLocale()
const draft = ref<DiagnosticSchedule>(emptySchedule())

function emptySchedule(): DiagnosticSchedule {
  return { id: '', name: '', macro_id: '', port: '', interval_seconds: 3600, enabled: false }
}
function edit(schedule: DiagnosticSchedule) { draft.value = { ...schedule } }
function save() {
  if (!draft.value.id.trim() || !draft.value.macro_id || !draft.value.port.trim()) return
  emit('save', { ...draft.value, id: draft.value.id.trim(), name: draft.value.name.trim(), port: draft.value.port.trim() })
  draft.value = emptySchedule()
}
function toggle(schedule: DiagnosticSchedule, event: Event) {
  emit('save', { ...schedule, enabled: (event.target as HTMLInputElement).checked })
}
</script>

<template>
  <div class="panel-layout">
    <section class="list-section">
      <div class="section-header"><h3>{{ t('automations.schedules') }}</h3><button type="button" :disabled="props.busy" @click="emit('refresh')">{{ t('automations.refresh') }}</button></div>
      <div v-if="props.schedules.length">
        <article v-for="schedule in props.schedules" :key="schedule.id" class="schedule-row">
          <label class="toggle"><input :data-testid="`toggle-${schedule.id}`" type="checkbox" :checked="schedule.enabled" @change="toggle(schedule, $event)" /></label>
          <div class="schedule-body">
            <strong>{{ schedule.name }}</strong>
            <span>{{ schedule.macro_id }} @ {{ schedule.port }} · {{ schedule.interval_seconds }}s</span>
            <span>{{ props.status[schedule.id]?.last_status || 'idle' }}</span>
            <span v-if="props.status[schedule.id]?.last_error" class="error">{{ props.status[schedule.id].last_error }}</span>
          </div>
          <div class="actions"><button type="button" @click="edit(schedule)">{{ t('automations.edit') }}</button><button type="button" class="danger" @click="emit('delete', schedule.id)">{{ t('automations.delete') }}</button></div>
        </article>
      </div>
      <p v-else class="empty">{{ t('automations.noSchedules') }}</p>
    </section>

    <form class="editor" @submit.prevent="save">
      <h3>{{ t('automations.scheduleEditor') }}</h3>
      <label>{{ t('automations.id') }}<input v-model="draft.id" required /></label>
      <label>{{ t('automations.name') }}<input v-model="draft.name" required /></label>
      <label>{{ t('automations.macro') }}<select v-model="draft.macro_id" required><option value="" disabled>{{ t('automations.selectMacro') }}</option><option v-for="macro in props.macros" :key="macro.id" :value="macro.id">{{ macro.name }}</option></select></label>
      <label>{{ t('automations.port') }}<input v-model="draft.port" required placeholder="COM17" /></label>
      <label>{{ t('automations.interval') }}<input v-model.number="draft.interval_seconds" type="number" min="5" max="604800" required /></label>
      <label class="checkbox"><input v-model="draft.enabled" type="checkbox" />{{ t('automations.enabled') }}</label>
      <button type="submit" class="primary">{{ t('automations.save') }}</button>
    </form>
  </div>
</template>

<style scoped>
.panel-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; height: 100%; min-height: 0; }.list-section, .editor { padding: 14px; overflow: auto; }.editor { display: flex; flex-direction: column; gap: 10px; border-left: 1px solid #30363d; }.section-header, .schedule-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.section-header h3, .editor h3 { margin: 0; font-size: 15px; }.schedule-row { padding: 10px 4px; border-bottom: 1px solid #30363d; }.schedule-body { display: flex; flex: 1; flex-direction: column; gap: 3px; min-width: 0; }.schedule-body span { color: #8b949e; font-size: 12px; }.schedule-body .error { color: #ff7b72; }.actions { display: flex; gap: 6px; }.editor label { display: flex; flex-direction: column; gap: 4px; color: #8b949e; font-size: 12px; }.checkbox { flex-direction: row !important; align-items: center; }input, select, button { padding: 7px 8px; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; }button { cursor: pointer; }.primary { background: #238636; border-color: #238636; color: white; }.danger, .error { color: #ff7b72; }.empty { color: #8b949e; }
@media (max-width: 820px) { .panel-layout { grid-template-columns: 1fr; }.editor { border-left: 0; border-top: 1px solid #30363d; } }
</style>
