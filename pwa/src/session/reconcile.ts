import type { MessageVariant, UiMessage } from '../types'
import { createId } from '../utils'
import { sessionMessageContent, sessionMessageParts } from './history'
import { hydrateToolEvents } from './toolHydration'
import { applyVariant, ensureVariants, syncCurrentVariant } from './variants'

// 尾部对账：后台断流后，从 session detail 的 recent_messages（gateway_messages
// 原始行）里把服务端 drain 落库的完整回复找回来。只修尾巴，绝不整体替换——
// openSession 的整体替换对本地 attachments/thinking 有损，仅用于切会话。
//
// 锚点约定：先在服务端行里从尾部找到与本地末轮 user 消息内容一致的行，再取其后
// 的 assistant 行。锚不上（服务端最新 user 行不是我们这条）就返回 false，让调用
// 方按退避重试——这正是"服务端还没 drain 完"的样子。

type RecentRow = Record<string, unknown>

type RecoveryReply = {
  id?: unknown
  reply_version_id?: unknown
  content?: unknown
  tool_rows?: unknown
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

// 末轮是否不完整：最后一条是 user（没等到回复），或 assistant 带 error/truncated。
export function tailNeedsReconcile(messages: UiMessage[]): boolean {
  const last = messages[messages.length - 1]
  if (!last) return false
  if (last.role === 'user') return true
  return Boolean(last.error || last.truncated)
}

function recentRows(payload: Record<string, unknown>): RecentRow[] {
  return Array.isArray(payload.recent_messages)
    ? payload.recent_messages.filter((row): row is RecentRow => Boolean(row && typeof row === 'object'))
    : []
}

// 从尾部找服务端最新一条 user 行；只认最新那条——它若不是本地末轮的 user 消息，
// 说明服务端尾巴还落后于本地（drain 未完成或压根没收到请求），不能拿旧轮回复充数。
function anchorRowIndex(rows: RecentRow[], anchorContent: string): number {
  const anchorKey = normalizeText(anchorContent)
  if (!anchorKey) return -1
  for (let index = rows.length - 1; index >= 0; index--) {
    if (rows[index].role !== 'user') continue
    return normalizeText(sessionMessageContent(rows[index].content)) === anchorKey ? index : -1
  }
  return -1
}

function replyRowAfter(rows: RecentRow[], anchorIndex: number): RecentRow | undefined {
  let reply: RecentRow | undefined
  for (let index = anchorIndex + 1; index < rows.length; index++) {
    if (rows[index].role === 'user') break
    if (rows[index].role === 'assistant') reply = rows[index]
  }
  return reply
}

export function applyReconciledTail(messages: UiMessage[], payload: Record<string, unknown>): boolean {
  if (!tailNeedsReconcile(messages)) return false
  const rows = recentRows(payload)
  if (!rows.length) return false

  const last = messages[messages.length - 1]
  const target = last.role === 'assistant' ? last : undefined
  const versionedReply = target?.replyVersionId
    ? rows.find((row) => row.role === 'assistant' && String(row.source_id || '') === target.replyVersionId)
    : undefined
  let selectedReply = versionedReply
  if (!selectedReply) {
    const anchorUser = target ? messages[messages.length - 2] : last
    if (!anchorUser || anchorUser.role !== 'user') return false
    const anchorIndex = anchorRowIndex(rows, anchorUser.content)
    if (anchorIndex < 0) return false
    selectedReply = replyRowAfter(rows, anchorIndex)
  }
  if (!selectedReply) return false
  const parts = sessionMessageParts(selectedReply.content)
  if (!parts.content && !parts.echo) return false

  if (target) {
    const serverLength = parts.content.length + parts.echo.length
    const localLength = (target.content || '').length + (target.echo || '').length
    // 精确版本号已经证明这是同一版 roll；即使服务端文本更短也要采用。
    if (!versionedReply && serverLength <= localLength) return false
    target.content = parts.content
    target.echo = parts.echo
    target.echoSegments = parts.echo
      ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
      : []
    target.error = undefined
    target.truncated = undefined
    target.streaming = false
    syncCurrentVariant(target)
  } else {
    messages.push({
      id: String(selectedReply.id || createId('message')),
      role: 'assistant',
      content: parts.content,
      echo: parts.echo,
      echoSegments: parts.echo
        ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
        : [],
      attachments: [],
      thinking: '',
      thinkingSegments: [],
      events: [],
      streaming: false,
    })
  }
  // 快照只有正文；工具事件从原始 tool 行补回（只补 events 为空的行，安全）。
  hydrateToolEvents(messages, rows)
  return true
}

function recoveryVariant(reply: RecoveryReply): MessageVariant | undefined {
  const parts = sessionMessageParts(reply.content)
  if (!parts.content && !parts.echo) return undefined
  const variant: MessageVariant = {
    replyVersionId: reply.reply_version_id ? String(reply.reply_version_id) : undefined,
    content: parts.content,
    echo: parts.echo,
    echoSegments: parts.echo
      ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
      : [],
    thinking: '',
    thinkingSegments: [],
    events: [],
  }
  const toolRows = Array.isArray(reply.tool_rows)
    ? reply.tool_rows.filter((row): row is RecentRow => Boolean(row && typeof row === 'object'))
    : []
  if (toolRows.length) {
    const holder: UiMessage = {
      id: String(reply.id || createId('recovery')),
      role: 'assistant',
      content: variant.content,
      echo: variant.echo,
      echoSegments: variant.echoSegments,
      attachments: [],
      thinking: '',
      thinkingSegments: [],
      events: [],
    }
    hydrateToolEvents([holder], [...toolRows, { role: 'assistant', content: reply.content }])
    variant.events = holder.events
  }
  return variant
}

// Merge the durable same-user roll group into one assistant bubble. This path
// runs even when the currently selected reply is complete: a complete snapshot
// can still be missing older variants.
export function applyReplyRecovery(messages: UiMessage[], payload: Record<string, unknown>): boolean {
  const rawReplies = Array.isArray(payload.replies) ? payload.replies : []
  const replies = rawReplies
    .filter((item): item is RecoveryReply => Boolean(item && typeof item === 'object'))
    .map(recoveryVariant)
    .filter((item): item is MessageVariant => Boolean(item))
  if (!replies.length) return false

  const lastUserIndex = messages.map((message) => message.role).lastIndexOf('user')
  if (lastUserIndex < 0) return false
  let target = messages[lastUserIndex + 1]
  if (!target || target.role !== 'assistant') {
    target = {
      id: createId('assistant'),
      role: 'assistant',
      content: '',
      echo: '',
      echoSegments: [],
      attachments: [],
      thinking: '',
      thinkingSegments: [],
      events: [],
      streaming: false,
    }
    messages.splice(lastUserIndex + 1, 0, target)
  }
  const variants = ensureVariants(target)
  const originalSelectedId = target.replyVersionId
  let changed = false
  const recoveredIds = new Set<string>()
  for (const candidate of replies) {
    const candidateId = candidate.replyVersionId
    let index = candidateId
      ? variants.findIndex((variant) => variant.replyVersionId === candidateId)
      : variants.findIndex((variant) => variant.content === candidate.content && variant.echo === candidate.echo)
    if (index < 0) {
      index = variants.findIndex((variant) => variant.content === candidate.content && variant.echo === candidate.echo)
    }
    if (index < 0) {
      variants.push(candidate)
      changed = true
    } else {
      const previous = variants[index]
      if (candidateId && previous.replyVersionId !== candidateId) {
        variants[index] = candidate
        changed = true
      } else if (previous.content !== candidate.content || previous.echo !== candidate.echo || previous.events.length !== candidate.events.length) {
        variants[index] = candidate
        changed = true
      }
    }
    if (candidateId) recoveredIds.add(candidateId)
  }
  // Keep recovered rolls in server order, then retain any local-only variants
  // (for example an in-flight draft) after them.
  const ordered = replies.map((candidate) => {
    const index = candidate.replyVersionId
      ? variants.findIndex((variant) => variant.replyVersionId === candidate.replyVersionId)
      : variants.findIndex((variant) => variant.content === candidate.content && variant.echo === candidate.echo)
    return variants[index]
  }).filter((variant): variant is MessageVariant => Boolean(variant))
  const extras = variants.filter((variant) => !variant.replyVersionId || !recoveredIds.has(variant.replyVersionId))
  if (ordered.length && (ordered.length !== variants.length || ordered.some((variant, index) => variant !== variants[index]))) {
    variants.splice(0, variants.length, ...ordered, ...extras)
    changed = true
  }
  const selected = originalSelectedId
    ? variants.findIndex((variant) => variant.replyVersionId === originalSelectedId)
    : -1
  const lastRecovered = replies[replies.length - 1]
  const lastRecoveredIndex = lastRecovered?.replyVersionId
    ? variants.findIndex((variant) => variant.replyVersionId === lastRecovered.replyVersionId)
    : variants.findIndex((variant) => variant.content === lastRecovered?.content && variant.echo === lastRecovered.echo)
  const selectedIndex = selected >= 0 ? selected : lastRecoveredIndex
  if (selectedIndex >= 0 && (target.selectedVariantIndex !== selectedIndex || changed)) {
    applyVariant(target, variants[selectedIndex], selectedIndex)
    target.streaming = false
    target.error = undefined
    target.truncated = undefined
    syncCurrentVariant(target)
    changed = true
  }
  return changed
}
