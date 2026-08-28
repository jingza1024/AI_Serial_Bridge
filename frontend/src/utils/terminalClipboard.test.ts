import { describe, expect, it, vi } from 'vitest'
import {
  copyTerminalSelection,
  pasteClipboardIntoTerminal,
  positionContextMenu,
} from './terminalClipboard'

describe('terminal clipboard helpers', () => {
  it('copies the current terminal selection', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const terminal = { getSelection: () => 'selected output' }

    const copied = await copyTerminalSelection(terminal, { writeText })

    expect(copied).toBe(true)
    expect(writeText).toHaveBeenCalledWith('selected output')
  })

  it('does not copy when the terminal has no selection', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const terminal = { getSelection: () => '' }

    const copied = await copyTerminalSelection(terminal, { writeText })

    expect(copied).toBe(false)
    expect(writeText).not.toHaveBeenCalled()
  })

  it('reports copy failure when clipboard writing is rejected', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    const terminal = { getSelection: () => 'selected output' }

    const copied = await copyTerminalSelection(terminal, { writeText })

    expect(copied).toBe(false)
  })

  it('reads clipboard text and pastes it into the terminal', async () => {
    const readText = vi.fn().mockResolvedValue('echo pasted')
    const paste = vi.fn()
    const terminal = { paste }

    const pasted = await pasteClipboardIntoTerminal(terminal, { readText })

    expect(pasted).toBe(true)
    expect(readText).toHaveBeenCalledOnce()
    expect(paste).toHaveBeenCalledWith('echo pasted')
  })

  it('keeps the context menu inside the terminal panel', () => {
    expect(positionContextMenu(
      { clientX: 390, clientY: 290 },
      { left: 100, top: 100, width: 300, height: 200 },
      { width: 120, height: 80 },
    )).toEqual({ left: 180, top: 120 })
  })
})
