export type SerialNewline = '\r' | '\n' | '\r\n'

export function normalizeInteractiveInput(data: string, newline: SerialNewline): string {
  return data.replace(/\r\n|\r/g, newline)
}
