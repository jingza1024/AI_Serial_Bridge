import { ref, computed } from 'vue'
import zh from '../locales/zh'
import en from '../locales/en'

export type Locale = 'zh' | 'en'

const messages: Record<Locale, Record<string, any>> = { zh, en }

const currentLocale = ref<Locale>('zh')

function _get(obj: any, path: string): string {
  const keys = path.split('.')
  let result = obj
  for (const key of keys) {
    if (result === undefined || result === null) return path
    result = result[key]
  }
  return typeof result === 'string' ? result : path
}

export function useLocale() {
  const locale = computed({
    get: () => currentLocale.value,
    set: (val: Locale) => {
      currentLocale.value = val
      // 同步通知后端切换语言
      try {
        fetch('/api/lang', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lang: val })
        }).catch(() => {})
      } catch {
        // ignore
      }
    }
  })

  function t(path: string): string {
    return _get(messages[currentLocale.value], path)
  }

  return { locale, t }
}

export { currentLocale }
