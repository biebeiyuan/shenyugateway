export function createId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

// Unicode-safe text length: assistant content offsets count code points,
// not UTF-16 units, so emoji in streamed text do not shift process groups.
export function textLength(value: string): number {
  return Array.from(value).length
}
