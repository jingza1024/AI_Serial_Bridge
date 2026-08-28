export interface TerminalClipboardTarget {
  getSelection: () => string
  paste: (text: string) => void
}

export interface ClipboardTarget {
  readText: () => Promise<string>
  writeText: (text: string) => Promise<void>
}

interface PointEvent {
  clientX: number
  clientY: number
}

interface Rectangle {
  left: number
  top: number
  width: number
  height: number
}

interface Size {
  width: number
  height: number
}

export async function copyTerminalSelection(
  terminal: Pick<TerminalClipboardTarget, 'getSelection'>,
  clipboard: Pick<ClipboardTarget, 'writeText'> | null,
): Promise<boolean> {
  const selection = terminal.getSelection()
  if (!selection) return false

  try {
    if (clipboard) {
      await clipboard.writeText(selection)
    } else if (!legacyCopy(selection)) {
      return false
    }
    return true
  } catch {
    return false
  }
}

export async function pasteClipboardIntoTerminal(
  terminal: Pick<TerminalClipboardTarget, 'paste'>,
  clipboard: Pick<ClipboardTarget, 'readText'> | null,
  paste = (text: string) => terminal.paste(text),
): Promise<boolean> {
  try {
    const text = clipboard ? await clipboard.readText() : legacyPaste()
    if (!text) return false
    paste(text)
    return true
  } catch {
    return false
  }
}

function legacyCopy(text: string): boolean {
  if (typeof document === 'undefined') return false
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  return copied
}

function legacyPaste(): string {
  if (typeof document === 'undefined') return ''
  const textarea = document.createElement('textarea')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  const pasted = document.execCommand('paste')
  const text = pasted ? textarea.value : ''
  textarea.remove()
  return text
}

export function positionContextMenu(
  event: PointEvent,
  panel: Rectangle,
  menu: Size,
): { left: number, top: number } {
  const x = event.clientX - panel.left
  const y = event.clientY - panel.top
  return {
    left: Math.min(Math.max(0, x), Math.max(0, panel.width - menu.width)),
    top: Math.min(Math.max(0, y), Math.max(0, panel.height - menu.height)),
  }
}
