<script setup lang="ts">
import { useLocale } from '../composables/useLocale'

export interface LogSessionSummary {
  session_id: string
  started_at: number
  ended_at: number
  records: number
}

const props = defineProps<{
  sessions: LogSessionSummary[]
  selectedId: string
  offset: number
  limit: number
  total: number
}>()

const emit = defineEmits<{
  select: [session: LogSessionSummary]
  previous: []
  next: []
}>()
const { t } = useLocale()

function formatTime(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString()
}
</script>

<template>
  <div class="session-list">
    <button
      v-for="session in props.sessions"
      :key="session.session_id"
      class="session-item"
      :class="{ selected: session.session_id === props.selectedId }"
      type="button"
      @click="emit('select', session)"
    >
      <span>{{ formatTime(session.started_at) }}</span>
      <small>{{ t('logs.recordCount', { count: session.records }) }}</small>
    </button>
    <div class="pagination">
      <button type="button" :disabled="props.offset === 0" @click="emit('previous')">‹</button>
      <span>{{ props.total ? props.offset + 1 : 0 }}-{{ Math.min(props.offset + props.limit, props.total) }} / {{ props.total }}</span>
      <button
        type="button"
        :disabled="props.offset + props.limit >= props.total"
        @click="emit('next')"
      >
        ›
      </button>
    </div>
  </div>
</template>

<style scoped>
.session-list {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid #30363d;
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid #30363d;
  background: transparent;
  color: #c9d1d9;
  text-align: left;
  cursor: pointer;
}

.session-item:hover,
.session-item.selected {
  background: #1f6feb33;
}

.session-item small {
  color: #8b949e;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding: 10px;
  color: #8b949e;
  font-size: 12px;
}

.pagination button {
  width: 30px;
  height: 30px;
  border: 1px solid #30363d;
  border-radius: 6px;
  background: #21262d;
  color: #c9d1d9;
  cursor: pointer;
}

.pagination button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}
</style>
