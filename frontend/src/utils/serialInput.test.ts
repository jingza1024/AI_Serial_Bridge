import { describe, expect, it } from 'vitest'
import { normalizeInteractiveInput } from './serialInput'

describe('normalizeInteractiveInput', () => {
  it('maps xterm Enter to LF for Unix serial consoles', () => {
    expect(normalizeInteractiveInput('ls\r', '\n')).toBe('ls\n')
  })

  it('replaces CRLF without duplicating the configured newline', () => {
    expect(normalizeInteractiveInput('one\r\ntwo\r', '\r\n')).toBe('one\r\ntwo\r\n')
  })

  it('leaves regular input unchanged', () => {
    expect(normalizeInteractiveInput('status', '\n')).toBe('status')
  })
})
