<script setup lang="ts">
import { ref, shallowRef } from 'vue'
import { useLocale } from '../../composables/useLocale'
import type { MacroDefinition, MacroRunResult, MacroStep } from '../../composables/useAutomations'

const props = defineProps<{
  macros: MacroDefinition[]
  runs: MacroRunResult[]
  busy: boolean
  activeRuns?: { runId: string; macroId: string; port: string }[]
}>()

const emit = defineEmits<{
  save: [macro: MacroDefinition]
  delete: [macroId: string]
  run: [macroId: string, port: string]
  cancel: [runId: string]
}>()

const { t } = useLocale()
const runPort = shallowRef('')
const draft = ref<MacroDefinition>(emptyMacro())

function emptyStep(): MacroStep {
  return { command: '', newline: '\r', wait_seconds: 1 }
}

function emptyMacro(): MacroDefinition {
  return { id: '', name: '', steps: [emptyStep()], enabled: true }
}

function edit(macro: MacroDefinition) {
  draft.value = { ...macro, steps: macro.steps.map(step => ({ ...step })) }
}

function addStep() {
  if (draft.value.steps.length < 32) draft.value.steps.push(emptyStep())
}

function removeStep(index: number) {
  if (draft.value.steps.length > 1) draft.value.steps.splice(index, 1)
}

function save() {
  if (!draft.value.id.trim() || !draft.value.name.trim()) return
  if (draft.value.steps.some(step => !step.command.trim())) return
  emit('save', {
    ...draft.value,
    id: draft.value.id.trim(),
    name: draft.value.name.trim(),
    steps: draft.value.steps.map(step => ({ ...step })),
  })
  draft.value = emptyMacro()
}
</script>

<template>
  <div class="panel-layout">
    <section class="list-section">
      <div class="run-controls">
        <label>
          {{ t('automations.port') }}
          <input v-model="runPort" :aria-label="t('automations.runPort')" placeholder="COM17" />
        </label>
      </div>
      <div v-if="props.macros.length" class="definition-list">
        <article v-for="macro in props.macros" :key="macro.id" class="definition-row">
          <div>
            <strong>{{ macro.name }}</strong>
            <span>{{ macro.id }} · {{ t('automations.stepCount', { count: macro.steps.length }) }}</span>
          </div>
          <div class="row-actions">
            <button type="button" @click="edit(macro)">{{ t('automations.edit') }}</button>
            <button
              type="button"
              :data-testid="`run-${macro.id}`"
              :disabled="props.busy || !runPort.trim() || !macro.enabled"
              @click="emit('run', macro.id, runPort.trim())"
            >
              {{ t('automations.run') }}
            </button>
            <button type="button" class="danger" @click="emit('delete', macro.id)">
              {{ t('automations.delete') }}
            </button>
          </div>
        </article>
      </div>
      <p v-else class="empty">{{ t('automations.noMacros') }}</p>

      <div v-if="props.activeRuns?.length" class="active-runs">
        <div v-for="run in props.activeRuns" :key="run.runId" class="definition-row">
          <span>{{ run.macroId }} @ {{ run.port }}</span>
          <button type="button" class="danger" @click="emit('cancel', run.runId)">
            {{ t('automations.cancel') }}
          </button>
        </div>
      </div>

      <pre v-if="props.runs[0]?.output" class="run-output">{{ props.runs[0].output }}</pre>
    </section>

    <form class="editor" @submit.prevent="save">
      <h3>{{ t('automations.macroEditor') }}</h3>
      <label>{{ t('automations.id') }}<input v-model="draft.id" required pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" /></label>
      <label>{{ t('automations.name') }}<input v-model="draft.name" required maxlength="128" /></label>
      <label class="checkbox"><input v-model="draft.enabled" type="checkbox" />{{ t('automations.enabled') }}</label>
      <div v-for="(step, index) in draft.steps" :key="index" class="step-editor">
        <textarea v-model="step.command" required maxlength="4096" :placeholder="t('automations.command')"></textarea>
        <select v-model="step.newline" :aria-label="t('terminal.newline')">
          <option :value="'\r'">CR</option><option :value="'\n'">LF</option><option :value="'\r\n'">CRLF</option><option value="">None</option>
        </select>
        <input v-model.number="step.wait_seconds" type="number" min="0" max="30" step="0.1" :aria-label="t('automations.waitSeconds')" />
        <button type="button" :disabled="draft.steps.length === 1" @click="removeStep(index)">−</button>
      </div>
      <div class="editor-actions">
        <button type="button" :disabled="draft.steps.length >= 32" @click="addStep">{{ t('automations.addStep') }}</button>
        <button type="submit" class="primary">{{ t('automations.save') }}</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.panel-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; min-height: 0; height: 100%; }
.list-section { min-width: 0; overflow: auto; padding: 14px; }
.editor { display: flex; flex-direction: column; gap: 10px; overflow: auto; padding: 14px; border-left: 1px solid #30363d; }
.editor h3 { margin: 0; font-size: 15px; }
.editor label { display: flex; flex-direction: column; gap: 4px; color: #8b949e; font-size: 12px; }
.editor input, .editor textarea, .editor select, .run-controls input { padding: 7px 8px; border: 1px solid #30363d; border-radius: 6px; background: #0d1117; color: #c9d1d9; }
.editor textarea { min-height: 64px; resize: vertical; }
.checkbox { flex-direction: row !important; align-items: center; }
.run-controls { margin-bottom: 12px; }
.run-controls label { display: flex; align-items: center; gap: 8px; color: #8b949e; font-size: 12px; }
.definition-list, .active-runs { border-top: 1px solid #30363d; }
.definition-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 4px; border-bottom: 1px solid #30363d; }
.definition-row div:first-child { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.definition-row span { color: #8b949e; font-size: 12px; }
.row-actions, .editor-actions { display: flex; gap: 6px; }
button { padding: 6px 9px; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .45; }
.primary { background: #238636; border-color: #238636; color: #fff; }
.danger { color: #ff7b72; }
.step-editor { display: grid; grid-template-columns: 1fr 70px 72px 32px; gap: 6px; }
.run-output { padding: 10px; overflow: auto; background: #010409; color: #b1bac4; white-space: pre-wrap; }
.empty { color: #8b949e; }
@media (max-width: 820px) { .panel-layout { grid-template-columns: 1fr; } .editor { border-top: 1px solid #30363d; border-left: 0; } }
</style>
