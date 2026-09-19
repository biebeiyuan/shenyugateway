import type { ToolEvent } from '../toolLanguage'
import type { UiMessage } from '../types'
import { readArchiveEvent, sessionMessageParts } from './history'

// A reply identity owns its tool receipts. Text is a legacy-only, unambiguous
// fallback, never an alternative when a known identity fails to match.
type RecentRow = Record<string, unknown>
type Group = { identity?: string; content: string; tools: RecentRow[]; consumed: boolean }
const textKey = (value: string) => value.replace(/\s+/g, ' ').trim()

function rowIdentity(row: RecentRow): string | undefined {
  return String(row.source_id || row.reply_version_id || readArchiveEvent(row.archive_event)?.id || '') || undefined
}

function groupsFromRows(rows: RecentRow[]): Group[] {
  const groups: Group[] = []
  let tools: RecentRow[] = []
  for (const row of rows) {
    if (row.role === 'tool') tools.push(row)
    else if (row.role === 'assistant') {
      const identity = rowIdentity(row)
      groups.push({ identity, content: textKey(sessionMessageParts(row.content).content),
        tools: tools.filter(tool => !tool.reply_version_id || String(tool.reply_version_id) === identity), consumed: false })
      tools = []
    } else tools = []
  }
  return groups
}

function inferOk(parsed: unknown): boolean {
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const record = parsed as Record<string, unknown>
    if (typeof record.ok === 'boolean') return record.ok
    if (typeof record.success === 'boolean') return record.success
    if (record.error || record.is_error) return false
  }
  return true
}

export function toolEventsFromRows(tools: RecentRow[], keyBase: string): ToolEvent[] {
  return tools.flatMap((row, index) => {
    const callId = String(row.tool_call_id || '') || `hydrated-${String(row.id ?? `${keyBase}-${index}`)}`
    const name = String(row.tool_name || 'gateway_tool')
    let input: unknown
    if (typeof row.tool_args_json === 'string' && row.tool_args_json.trim()) {
      try { input = JSON.parse(row.tool_args_json) } catch { input = row.tool_args_json }
    }
    const output = (typeof row.content === 'string' && row.content) || String(row.tool_result_summary || '')
    let parsed: unknown
    try { parsed = JSON.parse(output) } catch { parsed = undefined }
    const details = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown> : {}
    const common = { tool_call_id: callId, name, text_offset: 0, stream_order: index * 2 }
    return [
      { ...common, phase: 'tool_start', input },
      { ...common, phase: 'tool_end', stream_order: index * 2 + 1,
        ok: typeof row.tool_ok === 'boolean' ? row.tool_ok : inferOk(parsed),
        output: output || undefined,
        ...(details.error_kind ? { error_kind: String(details.error_kind) } : {}) },
    ] as ToolEvent[]
  })
}

// Preserve observed local order/offsets and completed results; fill only missing
// fields/phases. Synthetic legacy IDs cannot complete a real in-flight call.
export function mergeToolEvents(local: ToolEvent[], incoming: ToolEvent[]): ToolEvent[] {
  const result = local.map(event => ({ ...event }))
  for (const event of incoming) {
    const id = event.tool_call_id
    if (!id) continue
    const sameCall = result.filter(item => item.tool_call_id === id)
    if (id.startsWith('hydrated-') && local.length && !sameCall.length) continue
    const existing = sameCall.find(item => item.phase === event.phase)
    if (existing) {
      for (const [key, value] of Object.entries(event)) {
        if (value !== undefined && (existing as unknown as Record<string, unknown>)[key] === undefined) {
          (existing as unknown as Record<string, unknown>)[key] = value
        }
      }
      continue
    }
    // A terminal receipt does not need an invented missing start in the UI.
    if (event.phase === 'tool_start' && sameCall.some(item => item.phase === 'tool_end')) continue
    const start = sameCall.find(item => item.phase === 'tool_start')
    result.push({ ...event,
      name: start?.name || event.name,
      target_tool: start?.target_tool || event.target_tool,
      text_offset: start?.text_offset ?? event.text_offset,
      stream_order: start?.stream_order ?? event.stream_order })
  }
  return result
}

export function hasUnfinishedTools(events: ToolEvent[]): boolean {
  return events.some(event => event.phase === 'tool_start' && event.tool_call_id
    && !events.some(end => end.phase === 'tool_end' && end.tool_call_id === event.tool_call_id))
}

export function hydrateToolEvents(messages: UiMessage[], recentRows: unknown): number {
  if (!Array.isArray(recentRows)) return 0
  const rows = recentRows.filter((row): row is RecentRow => Boolean(row && typeof row === 'object'))
  const groups = groupsFromRows(rows)
  let hydrated = 0
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message.role !== 'assistant') continue
    if (message.replyVersionId && message.archiveEvent && message.replyVersionId !== message.archiveEvent.id) continue
    const identity = message.replyVersionId || message.archiveEvent?.id
    const key = textKey(message.content)
    let matched: Group | undefined
    if (identity) matched = groups.find(group => !group.consumed && group.identity === identity)
    else {
      const candidates = groups.filter(group => !group.consumed && group.content === key)
      const localCount = messages.filter(item => item.role === 'assistant' && textKey(item.content) === key).length
      if (key && candidates.length === 1 && localCount === 1) matched = candidates[0]
    }
    // Reserve a matched group even when local events are complete, so another
    // same-text bubble can never borrow it.
    if (matched) matched.consumed = true
    const tools = matched?.tools || (identity
      ? rows.filter(row => row.role === 'tool' && String(row.reply_version_id || '') === identity) : [])
    if (!tools.length) continue
    const merged = mergeToolEvents(message.events, toolEventsFromRows(tools, message.id))
    if (JSON.stringify(merged) !== JSON.stringify(message.events)) {
      message.events = merged
      hydrated++
    }
  }
  return hydrated
}
