import type { UiMessage } from '../types'

// Thread handoff / history source selection.
//
// A gateway session detail payload can carry up to four history representations.
// Priority order (see README § PWA chat frontend):
//   1. context_snapshots          — trimmed client transcript, the authoritative handoff source
//   2. request_context_snapshots  — legacy field name for the same snapshot data
//   3. recent_messages            — inspection stream, compatibility fallback for old data only
// cold_start_snapshots is a separate, explicitly-requested clean baseline used by
// duplicate-history recovery, never by ordinary handoff.

export function sessionTagFromLocation(search: string = window.location.search): string {
  try {
    const params = new URLSearchParams(search)
    return (params.get('session_tag') || params.get('session') || params.get('thread') || '').trim()
  } catch {
    return ''
  }
}

export function sessionMessageContent(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((block) => {
      if (typeof block === 'string') return block
      if (!block || typeof block !== 'object') return ''
      const item = block as Record<string, unknown>
      return item.type === 'text' ? String(item.text || '') : ''
    }).join('')
  }
  return value == null ? '' : String(value)
}

export function sessionHistoryRows(payload: Record<string, unknown>): Record<string, unknown>[] {
  const snapshotCollections = [payload.context_snapshots, payload.request_context_snapshots]
  for (const candidate of snapshotCollections) {
    if (!Array.isArray(candidate)) continue
    const latest = candidate[0]
    if (!latest || typeof latest !== 'object') continue
    const rows = (latest as Record<string, unknown>).messages
    if (!Array.isArray(rows)) continue
    return rows.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
  }
  const fallback = payload.recent_messages
  return Array.isArray(fallback)
    ? fallback.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
    : []
}

export function coldStartHistoryRows(payload: Record<string, unknown>, targetTag: string): Record<string, unknown>[] {
  const snapshots = payload.cold_start_snapshots
  if (!Array.isArray(snapshots)) return []
  const latest = snapshots.find((item) => item && typeof item === 'object' && (item as Record<string, unknown>).active !== false) as Record<string, unknown> | undefined
  const sources = latest?.sources
  if (!Array.isArray(sources)) return []
  const source = sources.find((item) => {
    if (!item || typeof item !== 'object') return false
    const row = item as Record<string, unknown>
    return !targetTag || String(row.session_tag || '') === targetTag
  }) || sources[0]
  if (!source || typeof source !== 'object') return []
  const rows = (source as Record<string, unknown>).messages
  if (!Array.isArray(rows)) return []
  return rows
    .filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
    .filter((row) => row.role === 'user' || row.role === 'assistant')
}

// NUL separator keeps role/content concatenation collision-free.
const DEDUPE_KEY_SEPARATOR = String.fromCharCode(0)

export function hasExactDuplicateRows(rows: Record<string, unknown>[]): boolean {
  const seen = new Set<string>()
  for (const row of rows) {
    if (row.role !== 'user' && row.role !== 'assistant') continue
    const key = `${String(row.role)}${DEDUPE_KEY_SEPARATOR}${sessionMessageContent(row.content)}`
    if (seen.has(key)) return true
    seen.add(key)
  }
  return false
}

export function dedupeUiMessagesForRecovery(source: UiMessage[]): UiMessage[] {
  const seen = new Set<string>()
  return source.filter((message) => {
    const key = `${message.role}${DEDUPE_KEY_SEPARATOR}${message.content}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
