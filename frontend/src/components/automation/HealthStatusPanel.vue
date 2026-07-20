<script setup lang="ts">
import { ref } from 'vue'
import { useLocale } from '../../composables/useLocale'
import type { HealthEvent, HealthRule } from '../../composables/useAutomations'

const props = defineProps<{ rules: HealthRule[]; events: HealthEvent[]; busy: boolean }>()
const emit = defineEmits<{ save: [rule: HealthRule]; delete: [ruleId: string]; refresh: [] }>()
const { t } = useLocale()
const draft = ref<HealthRule>(emptyRule())

function emptyRule(): HealthRule {
  return { id: '', name: '', pattern: '', severity: 'warning', message: '', cooldown_seconds: 60, enabled: true }
}

function edit(rule: HealthRule) { draft.value = { ...rule } }
function save() {
  if (!draft.value.id.trim() || !draft.value.pattern.trim() || !draft.value.message.trim()) return
  emit('save', { ...draft.value, id: draft.value.id.trim(), name: draft.value.name.trim() })
  draft.value = emptyRule()
}
function formatTime(timestamp: number) { return new Date(timestamp * 1000).toLocaleString() }
</script>

<template>
  <div class="panel-layout">
    <section class="list-section">
      <div class="section-header">
        <h3>{{ t('automations.healthEvents') }}</h3>
        <button data-testid="refresh-health" type="button" :disabled="props.busy" @click="emit('refresh')">{{ t('automations.refresh') }}</button>
      </div>
      <div v-if="props.events.length" class="event-list">
        <article v-for="event in props.events" :key="event.event_id" class="event-row" :class="event.severity">
          <div><strong>{{ event.message }}</strong><span>{{ event.severity }} · {{ event.port }} · {{ formatTime(event.timestamp) }}</span></div>
          <p>{{ event.content }}</p>
        </article>
      </div>
      <p v-else class="empty">{{ t('automations.noHealthEvents') }}</p>

      <h3>{{ t('automations.healthRules') }}</h3>
      <div class="rule-list">
        <div v-for="rule in props.rules" :key="rule.id" class="rule-row">
          <div><strong>{{ rule.name }}</strong><span>{{ rule.pattern }} · {{ rule.severity }}</span></div>
          <div><button type="button" @click="edit(rule)">{{ t('automations.edit') }}</button><button type="button" class="danger" @click="emit('delete', rule.id)">{{ t('automations.delete') }}</button></div>
        </div>
      </div>
    </section>

    <form class="editor" @submit.prevent="save">
      <h3>{{ t('automations.ruleEditor') }}</h3>
      <label>{{ t('automations.id') }}<input v-model="draft.id" required /></label>
      <label>{{ t('automations.name') }}<input v-model="draft.name" required /></label>
      <label>{{ t('automations.pattern') }}<input v-model="draft.pattern" required /></label>
      <label>{{ t('automations.message') }}<input v-model="draft.message" required /></label>
      <label>{{ t('automations.severity') }}<select v-model="draft.severity"><option value="info">info</option><option value="warning">warning</option><option value="critical">critical</option></select></label>
      <label>{{ t('automations.cooldown') }}<input v-model.number="draft.cooldown_seconds" type="number" min="0" max="86400" /></label>
      <label class="checkbox"><input v-model="draft.enabled" type="checkbox" />{{ t('automations.enabled') }}</label>
      <button type="submit" class="primary">{{ t('automations.save') }}</button>
    </form>
  </div>
</template>

<style scoped>
.panel-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; height: 100%; min-height: 0; }
.list-section, .editor { padding: 14px; overflow: auto; }
.editor { display: flex; flex-direction: column; gap: 10px; border-left: 1px solid #30363d; }
.section-header, .rule-row, .event-row > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
h3 { margin: 6px 0 10px; font-size: 15px; }
.event-row, .rule-row { padding: 10px 4px; border-bottom: 1px solid #30363d; }
.event-row { border-left: 3px solid #58a6ff; padding-left: 10px; }
.event-row.warning { border-left-color: #d29922; }.event-row.critical { border-left-color: #f85149; }
.event-row div, .rule-row div:first-child { display: flex; flex-direction: column; gap: 3px; }.event-row span, .rule-row span { color: #8b949e; font-size: 12px; }
.event-row p { margin: 8px 0 0; white-space: pre-wrap; }
.editor label { display: flex; flex-direction: column; gap: 4px; color: #8b949e; font-size: 12px; }.checkbox { flex-direction: row !important; align-items: center; }
input, select, button { padding: 7px 8px; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; }button { cursor: pointer; }.primary { background: #238636; border-color: #238636; color: white; }.danger { color: #ff7b72; }.empty { color: #8b949e; }
@media (max-width: 820px) { .panel-layout { grid-template-columns: 1fr; }.editor { border-left: 0; border-top: 1px solid #30363d; } }
</style>
