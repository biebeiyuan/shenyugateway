import type { ToolEvent } from '../toolLanguage'
import { toolName, toolWarmCopy } from '../toolLanguage'
import type { AssistantPart, ProcessGroup, ProcessTimelineItem, UiMessage } from '../types'
import { textLength, textSlice } from '../utils'
import { toolEventKey } from './sse'

// Groups streamed thinking segments and tool events by the content offset where
// they arrived, so the chat view can interleave process strips between text.

// Markdown emphasis, links, and fenced code can span multiple source lines.
// Rendering each content slice independently is only safe between paragraphs;
// otherwise a delimiter can land in one slice while its closing delimiter lands
// in the next one and the raw `*` characters become visible.
function markdownSafeOffset(source: string, offset: number): number {
  const chars = Array.from(source)
  const length = chars.length
  const clamped = Math.max(0, Math.min(length, offset))
  if (clamped === 0 || clamped === length) return clamped
  // Plain text has no cross-slice Markdown state to protect, so keep the
  // original timing for ordinary prose and emoji-only replies.
  if (!/[*_`~\[\]]/.test(source)) return clamped

  const isParagraphBoundary = (index: number) => (
    index > 1
    && index < length
    && chars[index - 2] === '\n'
    && chars[index - 1] === '\n'
  )
  if (isParagraphBoundary(clamped)) return clamped

  let previous = -1
  for (let index = clamped - 1; index > 0; index -= 1) {
    if (isParagraphBoundary(index)) {
      previous = index
      break
    }
  }

  let next = length
  for (let index = clamped + 1; index < length; index += 1) {
    if (isParagraphBoundary(index)) {
      next = index
      break
    }
  }

  // A single paragraph has no safe interior split. Keep its Markdown whole and
  // place the process strip after it rather than exposing unmatched delimiters.
  if (previous < 0 && next === length) return length
  if (previous < 0) return next
  if (next === length) return previous
  return clamped - previous <= next - clamped ? previous : next
}

export function traceRows(message: UiMessage): ToolEvent[] {
  const rows: ToolEvent[] = []
  const byId = new Map<string, ToolEvent>()
  for (const event of message.events) {
    if (event.phase === 'tool_start') {
      const row = { ...event }
      rows.push(row)
      byId.set(event.tool_call_id || event.name, row)
    } else if (event.phase === 'tool_end') {
      const row = byId.get(event.tool_call_id || event.name)
      if (row) Object.assign(row, event)
      else rows.push({ ...event })
    }
  }
  return rows
}

export function processGroups(message: UiMessage): ProcessGroup[] {
  const groups = new Map<number, ProcessGroup>()
  const ensure = (textOffset: number) => {
    const normalized = markdownSafeOffset(message.content, textOffset)
    const existing = groups.get(normalized)
    if (existing) return existing
    const created: ProcessGroup = { textOffset: normalized, thinking: [], tools: [] }
    groups.set(normalized, created)
    return created
  }

  const thinking = message.thinkingSegments.length
    ? message.thinkingSegments
    : message.thinking
      ? [{ id: `${message.id}-thinking`, content: message.thinking, textOffset: 0, streamOrder: 0 }]
      : []
  for (const item of thinking) ensure(item.textOffset).thinking.push(item)
  for (const event of traceRows(message)) ensure(event.text_offset || 0).tools.push(event)

  return [...groups.values()]
    .sort((left, right) => left.textOffset - right.textOffset)
    .map((group) => ({
      ...group,
      thinking: [...group.thinking].sort((left, right) => left.streamOrder - right.streamOrder),
      tools: [...group.tools].sort((left, right) => (left.stream_order || 0) - (right.stream_order || 0)),
    }))
}

export function assistantParts(message: UiMessage): AssistantPart[] {
  const parts: AssistantPart[] = []
  let cursor = 0
  for (const group of processGroups(message)) {
    if (group.textOffset > cursor) {
      parts.push({ kind: 'content', key: `content-${cursor}`, content: textSlice(message.content, cursor, group.textOffset) })
    }
    parts.push({ kind: 'process', key: `process-${group.textOffset}`, group })
    cursor = group.textOffset
  }
  if (cursor < textLength(message.content) || !parts.length) {
    parts.push({ kind: 'content', key: `content-${cursor}`, content: textSlice(message.content, cursor) })
  }
  return parts
}

export function processTimeline(group?: ProcessGroup): ProcessTimelineItem[] {
  if (!group) return []
  return [
    ...group.thinking.map((thinking) => ({
      kind: 'thinking' as const,
      key: `thinking-${thinking.id}`,
      thinking,
      streamOrder: thinking.streamOrder,
    })),
    ...group.tools.map((tool) => ({
      kind: 'tool' as const,
      key: `tool-${toolEventKey(tool)}`,
      tool,
      streamOrder: tool.stream_order || 0,
    })),
  ].sort((left, right) => left.streamOrder - right.streamOrder)
}

export function groupHasThinking(group: ProcessGroup): boolean {
  return group.thinking.length > 0
}

export function thinkingPreview(thinking: string): string {
  const compact = thinking.replace(/\s+/g, ' ').trim()
  const first = compact.match(/^[^。！？.!?]+[。！？.!?]?/)?.[0] || compact
  return first.length > 30 ? `${first.slice(0, 30)}…` : first
}

export function toolLabel(event: ToolEvent): string {
  return toolName(event).replace(/[_-]+/g, ' ')
}

export function toolResultPreview(event: ToolEvent): string {
  if (event.phase === 'tool_start' || event.ok === undefined) return '正在执行…'
  const output = String(event.output || '').replace(/\s+/g, ' ').trim()
  if (output) return output.length > 72 ? `${output.slice(0, 72)}…` : output
  return event.ok === false ? '执行失败' : '执行成功'
}

export function processSummary(group: ProcessGroup): string {
  const active = group.tools.find((event) => event.phase === 'tool_start' || event.ok === undefined)
  if (active) return `正在${toolWarmCopy(active)} · ${toolLabel(active)}…`
  const thought = group.thinking[group.thinking.length - 1]
  if (thought) return thinkingPreview(thought.content) || '想了一会儿'
  const tool = group.tools[group.tools.length - 1]
  return tool ? `${toolWarmCopy(tool)} · ${toolLabel(tool)}` : '想了一会儿'
}

export function formatToolInput(event?: ToolEvent): string {
  if (!event || event.input === undefined) return '（这条旧的工具记录没有保留参数）'
  if (typeof event.input === 'string') {
    try {
      return JSON.stringify(JSON.parse(event.input), null, 2)
    } catch {
      return event.input
    }
  }
  try {
    return JSON.stringify(event.input, null, 2)
  } catch {
    return String(event.input)
  }
}

export function formatToolOutput(event?: ToolEvent): string {
  if (!event) return '（找不到这一步工具记录）'
  if (event.phase === 'tool_start' || event.ok === undefined) return '正在执行…'
  if (event.output !== undefined) return event.output || '（工具没有返回正文）'
  return '（这条旧的工具记录没有保留结果）'
}
