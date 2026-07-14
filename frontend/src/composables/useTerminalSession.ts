import { onUnmounted, shallowRef } from 'vue'
import { Terminal, type ITerminalOptions } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'

export function useTerminalSession() {
  const terminal = shallowRef<Terminal | null>(null)
  let fitAddon: FitAddon | null = null

  function fit() {
    fitAddon?.fit()
  }

  function mount(container: HTMLElement, options: ITerminalOptions): Terminal {
    terminal.value?.dispose()
    const instance = new Terminal(options)
    fitAddon = new FitAddon()
    instance.loadAddon(fitAddon)
    instance.loadAddon(new WebLinksAddon())
    instance.open(container)
    terminal.value = instance
    fit()
    window.addEventListener('resize', fit)
    return instance
  }

  onUnmounted(() => {
    window.removeEventListener('resize', fit)
    terminal.value?.dispose()
    terminal.value = null
    fitAddon = null
  })

  return { terminal, mount, fit }
}
