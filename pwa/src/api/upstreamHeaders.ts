export type UpstreamHeaderEntry = {
  id: string
  name: string
  value: string
}

export const UPSTREAM_HEADERS_STORAGE_KEY = 'shenyu_pwa_upstream_headers'
export const CLAUDE_CODE_SESSION_ID_STORAGE_KEY = 'shenyu_pwa_claude_code_session_id'
export const CLAUDE_CODE_USER_AGENT = 'claude-cli/2.1.226 (external, cli)'
export const CLAUDE_CODE_APP = 'cli'
const LEGACY_CLAUDE_CODE_USER_AGENT = 'claude-cli/2.1.212 (external, cli)'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
let volatileClaudeCodeSessionId = ''

function createClaudeCodeSessionId(): string {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') return cryptoApi.randomUUID()

  const bytes = new Uint8Array(16)
  if (typeof cryptoApi?.getRandomValues === 'function') cryptoApi.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function isClaudeCodeSessionId(value: string): boolean {
  return UUID_RE.test(value.trim())
}

export function readClaudeCodeSessionId(): string {
  if (isClaudeCodeSessionId(volatileClaudeCodeSessionId)) return volatileClaudeCodeSessionId
  try {
    const stored = localStorage.getItem(CLAUDE_CODE_SESSION_ID_STORAGE_KEY) || ''
    if (isClaudeCodeSessionId(stored)) {
      volatileClaudeCodeSessionId = stored
      return stored
    }
  } catch {
    // A storage failure must not block the optional header preset.
  }
  return refreshClaudeCodeSessionId()
}

export function refreshClaudeCodeSessionId(): string {
  const next = createClaudeCodeSessionId()
  volatileClaudeCodeSessionId = next
  try {
    localStorage.setItem(CLAUDE_CODE_SESSION_ID_STORAGE_KEY, next)
  } catch {
    // The in-memory value still works for this page when storage is unavailable.
  }
  return next
}

export function claudeCodeHeaders(sessionId = readClaudeCodeSessionId()): UpstreamHeaderEntry[] {
  return [
    { id: 'claude-code-user-agent', name: 'User-Agent', value: CLAUDE_CODE_USER_AGENT },
    { id: 'claude-code-app', name: 'X-App', value: CLAUDE_CODE_APP },
    { id: 'claude-code-session-id', name: 'X-Claude-Code-Session-Id', value: sessionId },
  ]
}

export function readUpstreamHeaders(): UpstreamHeaderEntry[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(UPSTREAM_HEADERS_STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    const entries = parsed
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
      .map((item) => ({
        id: typeof item.id === 'string' ? item.id : '',
        name: typeof item.name === 'string' ? item.name : '',
        value: typeof item.value === 'string' ? item.value : '',
      }))
      .filter((item) => item.id)
      .slice(0, 20)
    const payload = upstreamHeadersPayload(entries)
    const userAgent = Object.entries(payload).find(([name]) => name.toLowerCase() === 'user-agent')?.[1]
    if (Object.keys(payload).length === 1 && userAgent === LEGACY_CLAUDE_CODE_USER_AGENT) {
      return claudeCodeHeaders(readClaudeCodeSessionId())
    }
    return entries
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
  if (isClaudeCodeHeaderPreset(entries)) return 'Claude Code · 固定会话'
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
  return headers.length === 3
    && headers.some(([name, value]) => name.toLowerCase() === 'user-agent' && value === CLAUDE_CODE_USER_AGENT)
    && headers.some(([name, value]) => name.toLowerCase() === 'x-app' && value === CLAUDE_CODE_APP)
    && headers.some(([name, value]) => name.toLowerCase() === 'x-claude-code-session-id' && isClaudeCodeSessionId(value))
}
