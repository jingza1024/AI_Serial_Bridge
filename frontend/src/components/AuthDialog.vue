<script setup lang="ts">
import { nextTick, shallowRef, useTemplateRef, watch } from 'vue'
import { useLocale } from '../composables/useLocale'

const props = defineProps<{
  visible: boolean
  busy: boolean
  error: string
}>()

const emit = defineEmits<{
  submit: [token: string]
}>()

const { t } = useLocale()
const token = shallowRef('')
const tokenInput = useTemplateRef<HTMLInputElement>('tokenInput')

watch(() => props.visible, async (visible) => {
  if (!visible) return
  await nextTick()
  tokenInput.value?.focus()
}, { immediate: true })

function submit() {
  if (!token.value.trim() || props.busy) return
  emit('submit', token.value)
}
</script>

<template>
  <div v-if="visible" class="auth-overlay">
    <form
      class="auth-dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="t('auth.title')"
      @submit.prevent="submit"
    >
      <h2>{{ t('auth.title') }}</h2>
      <p>{{ t('auth.description') }}</p>
      <label for="auth-token">{{ t('auth.token') }}</label>
      <input
        id="auth-token"
        ref="tokenInput"
        v-model="token"
        type="password"
        autocomplete="current-password"
        :disabled="busy"
      />
      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
      <button type="submit" :disabled="busy || !token.trim()">
        {{ busy ? t('auth.connecting') : t('auth.connect') }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.auth-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(1, 4, 9, 0.82);
}

.auth-dialog {
  display: flex;
  width: min(420px, 100%);
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  border: 1px solid #30363d;
  border-radius: 10px;
  background: #161b22;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

.auth-dialog h2,
.auth-dialog p {
  margin: 0;
}

.auth-dialog p,
.auth-dialog label {
  color: #8b949e;
  font-size: 13px;
}

.auth-dialog input {
  padding: 10px 12px;
  border: 1px solid #30363d;
  border-radius: 6px;
  outline: none;
  background: #0d1117;
  color: #e6edf3;
}

.auth-dialog input:focus {
  border-color: #58a6ff;
}

.auth-dialog button {
  padding: 10px 14px;
  border: 0;
  border-radius: 6px;
  background: #238636;
  color: white;
  cursor: pointer;
}

.auth-dialog button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.auth-error {
  color: #f85149 !important;
}
</style>
