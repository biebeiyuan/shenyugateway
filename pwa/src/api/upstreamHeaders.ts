export type UpstreamHeaderEntry = {
  id: string
  name: string
  value: string
}

export const UPSTREAM_HEADERS_STORAGE_KEY = 'shenyu_pwa_upstream_headers'
export const CLAUDE_CODE_USER_AGENT = 'claude-cli/2.1.212 (external, cli)'

export function readUpstreamHeaders(): UpstreamHeaderEntry[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(UPSTREAM_HEADERS_STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
      .map((item) => ({
        id: typeof item.id === 'string' ? item.id : '',
        name: typeof item.name === 'string' ? item.name : '',
        value: typeof item.value === 'string' ? item.value : '',
      }))
      .filter((item) => item.id)
      .slice(0, 20)
  } catch {
    return []
  }
}

export function persistUpstreamHeaders(entries: UpstreamHeaderEntry[]): void {
  try {
    localStorage.setItem(UPSTREAM_HEADERS_STORAGE_KEY, JSON.stringify(entries.slice(0, 20)))
  } catch {
    // Header preferences are optional; a storage quota failure must not block chat.
  }
}

export function upstreamHeadersPayload(entries: UpstreamHeaderEntry[]): Record<string, string> {
  const headers: Record<string, string> = {}
  const namesByLowercase = new Map<string, string>()
  for (const entry of entries.slice(0, 20)) {
    const name = entry.name.trim()
    const value = entry.value.trim()
    if (!name || !value) continue
    const normalized = name.toLowerCase()
    const previousName = namesByLowercase.get(normalized)
    if (previousName) delete headers[previousName]
    namesByLowercase.set(normalized, name)
    headers[name] = value
  }
  return headers
}

export function upstreamHeaderSummary(entries: UpstreamHeaderEntry[]): string {
  const headers = Object.entries(upstreamHeadersPayload(entries))
  if (!headers.length) return '未设置'
  const claudeCodeHeader = headers.find(([name, value]) => (
    name.toLowerCase() === 'user-agent' && value === CLAUDE_CODE_USER_AGENT
  ))
  if (claudeCodeHeader) return headers.length === 1 ? 'Claude Code' : `Claude Code + ${headers.length - 1}`
  return `自定义 · ${headers.length}`
}

export function isClaudeCodeHeaderPreset(entries: UpstreamHeaderEntry[]): boolean {
  const headers = Object.entries(upstreamHeadersPayload(entries))
  return headers.length === 1
    && headers[0][0].toLowerCase() === 'user-agent'
    && headers[0][1] === CLAUDE_CODE_USER_AGENT
}
