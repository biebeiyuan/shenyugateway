import type { ToolEvent } from '../toolLanguage'
import type { UiMessage } from '../types'
import { sessionMessageContent } from './history'

// 从 session detail 的 recent_messages（gateway_messages 原始行）里给快照还原的
// assistant 消息补回工具事件：快照只有 user/assistant 正文，tool 行全在原始流里。
// 原始流中连续的 tool 行归属紧随其后的那条 assistant 行；user 行打断这种连续性。
// 匹配从尾部开始、每行只消费一次——重答(retry)会产生重复 assistant 行，尾部优先
// 让最新一轮先占住自己的工具组。匹配不上就跳过，绝不报错。

type RecentRow = Record<string, unknown>

type AssistantRowGroup = {
  contentKey: string
  tools: RecentRow[]
  consumed: boolean
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function groupRecentRows(rows: RecentRow[]): AssistantRowGroup[] {
  const groups: AssistantRowGroup[] = []
  let pendingTools: RecentRow[] = []
  for (const row of rows) {
    const role = String(row.role || '')
    if (role === 'tool') {
      pendingTools.push(row)
    } else if (role === 'assistant') {
      groups.push({ contentKey: normalizeText(sessionMessageContent(row.content)), tools: pendingTools, consumed: false })
      pendingTools = []
    } else {
      pendingTools = []
    }
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

function toolEventsFromRows(tools: RecentRow[], keyBase: string): ToolEvent[] {
  const events: ToolEvent[] = []
  tools.forEach((row, index) => {
    const callId = `hydrated-${String(row.id ?? `${keyBase}-${index}`)}`
    const name = String(row.tool_name || 'gateway_tool')
    let input: unknown
    if (typeof row.tool_args_json === 'string' && row.tool_args_json.trim()) {
      try {
        input = JSON.parse(row.tool_args_json)
      } catch {
        input = row.tool_args_json
      }
    }
    const rawContent = typeof row.content === 'string' ? row.content : ''
    let output = rawContent
    // 历史 tool 行代表一次已完成的执行；ok 从结果 JSON 尽力推断，兜底为 true，
    // 否则 undefined 会让 UI 把它当成"正在执行"，结果永远展示不出来。
    let ok = true
    if (rawContent) {
      try {
        ok = inferOk(JSON.parse(rawContent))
      } catch {
        ok = true
      }
    } else if (row.tool_result_summary != null && String(row.tool_result_summary)) {
      output = String(row.tool_result_summary)
    }
    events.push({ phase: 'tool_start', tool_call_id: callId, name, input, text_offset: 0, stream_order: index * 2 })
    events.push({ phase: 'tool_end', tool_call_id: callId, name, ok, output: output || undefined, text_offset: 0, stream_order: index * 2 + 1 })
  })
  return events
}

export function hydrateToolEvents(messages: UiMessage[], recentRows: unknown): number {
  if (!Array.isArray(recentRows)) return 0
  const groups = groupRecentRows(recentRows.filter((row): row is RecentRow => Boolean(row && typeof row === 'object')))
  if (!groups.length) return 0
  let hydrated = 0
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message.role !== 'assistant' || message.events.length) continue
    const key = normalizeText(message.content)
    if (!key) continue
    let matched: AssistantRowGroup | undefined
    for (let g = groups.length - 1; g >= 0; g--) {
      if (!groups[g].consumed && groups[g].contentKey === key) {
        matched = groups[g]
        break
      }
    }
    if (!matched) continue
    matched.consumed = true
    if (!matched.tools.length) continue
    message.events = toolEventsFromRows(matched.tools, message.id)
    hydrated++
  }
  return hydrated
}
