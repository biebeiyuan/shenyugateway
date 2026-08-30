import type { ToolEvent } from '../toolLanguage'
import { toolName, toolWarmCopy } from '../toolLanguage'
import type { AssistantPart, ProcessGroup, ProcessTimelineItem, UiMessage } from '../types'
import { textLength } from '../utils'
import { markdownBlocks, snapToBlockBoundary } from './blocks'
import { toolEventKey } from './sse'

// Groups streamed thinking segments and tool events by the content offset where
// they arrived. Offsets preserve process chronology for the detail sheet; they
// must never split the assistant Markdown document in the chat view.

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
    const normalized = Math.max(0, Math.min(textLength(message.content), textOffset))
    const existing = groups.get(normalized)
    if (existing) return existing
    const created: ProcessGroup = { textOffset: normalized, echo: [], thinking: [], tools: [] }
    groups.set(normalized, created)
    return created
  }

  const echoSegments = message.echoSegments || []
  const echo = echoSegments.length
    ? echoSegments
    : message.echo
      ? [{ id: `${message.id}-echo`, content: message.echo, textOffset: 0, streamOrder: 0 }]
      : []
  for (const item of echo) ensure(item.textOffset).echo.push(item)

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
      echo: [...group.echo].sort((left, right) => left.streamOrder - right.streamOrder),
      thinking: [...group.thinking].sort((left, right) => left.streamOrder - right.streamOrder),
      tools: [...group.tools].sort((left, right) => (left.stream_order ?? 0) - (right.stream_order ?? 0)),
    }))
}

/**
 * 一条 assistant 消息渲染成什么：过程条与正文块交错，按到达顺序。
 *
 * 过程条插在 **Markdown 块边界**上，绝不切进块内部——按字符偏移直接切会把代码块
 * 和松散列表切成两半（2026-07-29 就是因此把交错渲染删掉的，见 `blocks.ts`）。
 * 落在块中间的过程偏移吸附到该块之后，读起来是自然顺序：写一段 → 做了点事 →
 * 再写一段。
 *
 * 正文按块产出，每块一个 part：`MarkdownBody` 因此能对已经写完的块命中缓存，
 * 流式时只有尾块真的重新解析（借 weir 的"段落封闭后不再重写"，MIT，见
 * `docs/frontend/STYLE_AND_CRAFT.md` § 风格血统声明）。
 */
export function assistantParts(message: UiMessage): AssistantPart[] {
  const groups = processGroups(message)
  const blocks = markdownBlocks(message.content)

  if (!blocks.length) {
    // 还没有正文（只有 Thinking 或工具在跑）：过程条在前，末尾仍保留一个空正文
    // part。调用方靠它渲染流式占位，少了它开头那一下会闪。
    return [
      ...groups.map((group) => ({
        kind: 'process' as const,
        key: `process-${group.textOffset}`,
        group,
      })),
      { kind: 'content' as const, key: 'content', content: message.content },
    ]
  }

  // 每组过程条吸附到一个块边界；同一边界上的多组保持原有先后。
  const pending = new Map<number, ProcessGroup[]>()
  for (const group of groups) {
    const at = snapToBlockBoundary(blocks, group.textOffset)
    const list = pending.get(at)
    if (list) list.push(group)
    else pending.set(at, [group])
  }

  const parts: AssistantPart[] = []
  const emitProcessAt = (boundary: number) => {
    for (const group of pending.get(boundary) || []) {
      parts.push({ kind: 'process', key: `process-${group.textOffset}`, group })
    }
    pending.delete(boundary)
  }

  emitProcessAt(blocks[0].start)
  for (const block of blocks) {
    parts.push({ kind: 'content', key: `content-${block.start}`, content: block.text })
    emitProcessAt(block.end)
  }
  // 吸附到正文之外的（例如偏移越界）兜在最后，绝不丢过程条。
  for (const [, groups_] of pending) {
    for (const group of groups_) {
      parts.push({ kind: 'process', key: `process-${group.textOffset}`, group })
    }
  }
  return parts
}

export function processTimeline(group?: ProcessGroup): ProcessTimelineItem[] {
  if (!group) return []
  return [
    ...group.echo.map((echo) => ({
      kind: 'echo' as const,
      key: `echo-${echo.id}`,
      echo,
      streamOrder: echo.streamOrder,
    })),
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
      streamOrder: tool.stream_order ?? 0,
    })),
  ].sort((left, right) => left.streamOrder - right.streamOrder)
}

export function groupHasThinking(group: ProcessGroup): boolean {
  return group.thinking.length > 0
}

export function groupHasEcho(group: ProcessGroup): boolean {
  return group.echo.length > 0
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
  const timeline = processTimeline(group)
  const latest = timeline[timeline.length - 1]
  if (latest?.kind === 'echo') return thinkingPreview(latest.echo.content) || '留下了一点回响'
  if (latest?.kind === 'thinking') return thinkingPreview(latest.thinking.content) || '想了一会儿'
  if (latest?.kind === 'tool') return `${toolWarmCopy(latest.tool)} · ${toolLabel(latest.tool)}`
  return '想了一会儿'
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
