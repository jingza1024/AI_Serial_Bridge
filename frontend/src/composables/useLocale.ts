import { shallowRef, computed } from 'vue'
import zh from '../locales/zh'
import en from '../locales/en'

export type Locale = 'zh' | 'en'
type MessageTree = { [key: string]: string | MessageTree }

const messages: Record<Locale, MessageTree> = { zh, en }

const currentLocale = shallowRef<Locale>('zh')

function _get(obj: MessageTree, path: string): string {
  const keys = path.split('.')
  let result: string | MessageTree | undefined = obj
  for (const key of keys) {
    if (typeof result === 'string' || result === undefined) return path
    result = result[key]
  }
  return typeof result === 'string' ? result : path
}

export function useLocale() {
  const locale = computed({
    get: () => currentLocale.value,
    set: (val: Locale) => {
      currentLocale.value = val
    }
  })

  function t(path: string, params?: Record<string, string | number | boolean>): string {
    let s = _get(messages[currentLocale.value], path)
    if (params) {
      for (const k of Object.keys(params)) {
        s = s.split(`{${k}}`).join(String(params[k]))
      }
    }
    return s
  }

  return { locale, t }
}

export { currentLocale }
