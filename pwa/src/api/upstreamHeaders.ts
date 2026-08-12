export type UpstreamHeaderEntry = {
  id: string
  name: string
  value: string
}

export const UPSTREAM_HEADERS_STORAGE_KEY = 'shenyu_pwa_upstream_headers'
export const CLAUDE_CODE_SESSION_ID_STORAGE_KEY = 'shenyu_pwa_claude_code_session_id'
export const CLAUDE_CODE_DEVICE_ID_STORAGE_KEY = 'shenyu_pwa_claude_code_device_id'
export const CLAUDE_CODE_USER_AGENT = 'claude-cli/2.1.201 (external, sdk-cli)'
export const CLAUDE_CODE_APP = 'cli'
const LEGACY_CLAUDE_CODE_USER_AGENT = 'claude-cli/2.1.212 (external, cli)'
const COMPACT_CLAUDE_CODE_USER_AGENT = 'claude-cli/2.1.226 (external, cli)'
const CLAUDE_CODE_BETA = 'claude-code-20250219,interleaved-thinking-2025-05-14,effort-2025-11-24,prompt-caching-scope-2026-01-05'

const CLAUDE_CODE_STATIC_HEADERS = [
  ['claude-code-user-agent', 'User-Agent', CLAUDE_CODE_USER_AGENT],
  ['claude-code-accept', 'Accept', 'application/json'],
  ['claude-code-beta', 'Anthropic-Beta', CLAUDE_CODE_BETA],
  ['claude-code-browser-access', 'Anthropic-Dangerous-Direct-Browser-Access', 'true'],
  ['claude-code-app', 'X-App', CLAUDE_CODE_APP],
  ['claude-code-stainless-arch', 'X-Stainless-Arch', 'x64'],
  ['claude-code-stainless-lang', 'X-Stainless-Lang', 'js'],
  ['claude-code-stainless-os', 'X-Stainless-Os', 'Linux'],
  ['claude-code-stainless-package', 'X-Stainless-Package-Version', '0.94.0'],
  ['claude-code-stainless-retry', 'X-Stainless-Retry-Count', '0'],
  ['claude-code-stainless-runtime', 'X-Stainless-Runtime', 'node'],
  ['claude-code-stainless-runtime-version', 'X-Stainless-Runtime-Version', 'v26.3.0'],
  ['claude-code-stainless-timeout', 'X-Stainless-Timeout', '600'],
] as const

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const DEVICE_ID_RE = /^[0-9a-f]{64}$/i
let volatileClaudeCodeSessionId = ''
let volatileClaudeCodeDeviceId = ''

function randomBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length)
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.getRandomValues === 'function') cryptoApi.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  return bytes
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function createClaudeCodeSessionId(): string {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') return cryptoApi.randomUUID()

  const bytes = randomBytes(16)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = bytesToHex(bytes)
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

export function readClaudeCodeDeviceId(): string {
  if (DEVICE_ID_RE.test(volatileClaudeCodeDeviceId)) return volatileClaudeCodeDeviceId
  try {
    const stored = localStorage.getItem(CLAUDE_CODE_DEVICE_ID_STORAGE_KEY) || ''
    if (DEVICE_ID_RE.test(stored)) {
      volatileClaudeCodeDeviceId = stored
      return stored
    }
  } catch {
    // Keep a page-local stable id when browser storage is unavailable.
  }
  volatileClaudeCodeDeviceId = bytesToHex(randomBytes(32))
  try {
    localStorage.setItem(CLAUDE_CODE_DEVICE_ID_STORAGE_KEY, volatileClaudeCodeDeviceId)
  } catch {
    // The in-memory value still preserves the current page's request identity.
  }
  return volatileClaudeCodeDeviceId
}

export function claudeCodeHeaders(sessionId = readClaudeCodeSessionId()): UpstreamHeaderEntry[] {
  return [
    ...CLAUDE_CODE_STATIC_HEADERS.map(([id, name, value]) => ({ id, name, value })),
    { id: 'claude-code-session-id', name: 'X-Claude-Code-Session-Id', value: sessionId },
  ]
}

export function claudeCodeSessionIdFromHeaders(entries: UpstreamHeaderEntry[]): string {
  const sessionId = Object.entries(upstreamHeadersPayload(entries))
    .find(([name]) => name.toLowerCase() === 'x-claude-code-session-id')?.[1] || ''
  return isClaudeCodeSessionId(sessionId) ? sessionId : ''
}

export function claudeCodeMetadata(
  sessionId = readClaudeCodeSessionId(),
  deviceId = readClaudeCodeDeviceId(),
): Record<string, string> {
  return {
    user_id: JSON.stringify({ device_id: deviceId, account_uuid: '', session_id: sessionId }),
  }
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
    const compactSessionId = claudeCodeSessionIdFromHeaders(entries)
    const compactApp = Object.entries(payload).find(([name]) => name.toLowerCase() === 'x-app')?.[1]
    if (Object.keys(payload).length === 3
      && userAgent === COMPACT_CLAUDE_CODE_USER_AGENT
      && compactApp === CLAUDE_CODE_APP
      && compactSessionId) {
      try {
        localStorage.setItem(CLAUDE_CODE_SESSION_ID_STORAGE_KEY, compactSessionId)
      } catch {
        // The migrated headers still carry the stable session id.
      }
      volatileClaudeCodeSessionId = compactSessionId
      return claudeCodeHeaders(compactSessionId)
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
  if (isClaudeCodeHeaderPreset(entries)) return 'Claude Code · 完整模拟'
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
  return headers.length === CLAUDE_CODE_STATIC_HEADERS.length + 1
    && CLAUDE_CODE_STATIC_HEADERS.every(([, expectedName, expectedValue]) => (
      headers.some(([name, value]) => name.toLowerCase() === expectedName.toLowerCase() && value === expectedValue)
    ))
    && headers.some(([name, value]) => name.toLowerCase() === 'x-claude-code-session-id' && isClaudeCodeSessionId(value))
}
