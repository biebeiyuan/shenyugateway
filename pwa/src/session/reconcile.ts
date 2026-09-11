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

// 服务端永远没有 thinking，events 也只有塌到 offset 0 的补水版本。
// 本地有的一律以本地为准，服务端只补本地空着的字段。
function mergeRecoveredVariant(local: MessageVariant, incoming: MessageVariant): MessageVariant {
  return {
    ...incoming,
    thinking: local.thinking || incoming.thinking,
    thinkingSegments: local.thinkingSegments.length ? local.thinkingSegments : incoming.thinkingSegments,
    events: local.events.length ? local.events : incoming.events,
  }
}

function variantKey(variant: MessageVariant): string {
  if (variant.replyVersionId) return `id:${variant.replyVersionId}`
  return `text:${variant.content}\u0000${variant.echo}`
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

  // 记录原始状态：如果 message 已经有完整的 thinking/events，
  // 说明是正常流式接收的完整消息，只是静默升级 replyVersionId，不算 changed
  const hadCompleteContent = Boolean(target.thinking || target.events.length)

  const variants = ensureVariants(target)
  const originalSelectedId = target.replyVersionId
  let changed = false
  // 去重，但去重本身不算"变化"——它只是整理，不是找回。
  const uniqueVariants: MessageVariant[] = []
  const seenKeys = new Set<string>()
  let hadDuplicates = false
  for (const variant of variants) {
    const key = variantKey(variant)
    if (seenKeys.has(key)) {
      hadDuplicates = true
      continue
    }
    seenKeys.add(key)
    uniqueVariants.push(variant)
  }
  if (uniqueVariants.length !== variants.length) variants.splice(0, variants.length, ...uniqueVariants)
  const recoveredIds = new Set<string>()
  for (const candidate of replies) {
    const candidateId = candidate.replyVersionId
    let index = candidateId
      ? variants.findIndex((variant) => variant.replyVersionId === candidateId)
      : variants.findIndex((variant) => variant.content === candidate.content && variant.echo === candidate.echo)
    if (index < 0 && candidateId) {
      index = variants.findIndex((variant) => !variant.replyVersionId && variant.content === candidate.content && variant.echo === candidate.echo)
    }
    // 如果还是找不到，但 target 有 error/truncated，且只有一个 variant，
    // 说明服务端的完整版本是对这个不完整 message 的修复，应该 merge 而不是添加
    if (index < 0 && variants.length === 1 && (target.error || target.truncated)) {
      index = 0
    }
    if (index < 0 && !candidateId) {
      index = variants.findIndex((variant) => variant.content === candidate.content && variant.echo === candidate.echo)
    }
    if (index < 0) {
      variants.push(candidate)
      changed = true
    } else {
      const previous = variants[index]
      const merged = mergeRecoveredVariant(previous, candidate)
      // 总是更新为 merged 版本，保留本地的 thinking/events
      variants[index] = merged
      // 标记 changed 的条件：
      // 1. 内容变化
      // 2. 补充了 events
      // 3. 首次添加 replyVersionId，但仅当原 message 不是完整内容时才算 changed
      //    （完整内容 = 有 thinking 或 events，说明是正常流式接收的）
      const addedVersionId = !previous.replyVersionId && merged.replyVersionId
      if (previous.content !== merged.content || previous.echo !== merged.echo
          || (!previous.events.length && merged.events.length)
          || (addedVersionId && !hadCompleteContent)) {
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
  // 按对象身份排除，避免重复插入同一个 variant。
  const orderedSet = new Set(ordered)
  const extras = variants.filter((variant) => !orderedSet.has(variant))
  // 只在真正需要重排时才 splice 和设置 changed：顺序变了，或数量变了
  const needsReorder = ordered.length && (
    ordered.length + extras.length !== variants.length ||
    ordered.some((variant, index) => variant !== variants[index])
  )
  if (needsReorder) {
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
  const currentIndex = target.selectedVariantIndex ?? 0

  // 应用 variant 的条件：
  // 1. selectedIndex 变了（切换到不同的 variant）
  // 2. 有新内容（changed = true）
  // 3. 当前 message 不完整（有 error/truncated），需要用恢复的版本替换
  const needsApply = selectedIndex >= 0 && (
    currentIndex !== selectedIndex ||
    changed ||
    target.error ||
    target.truncated
  )

  if (needsApply) {
    applyVariant(target, variants[selectedIndex], selectedIndex)
    target.streaming = false
    // 只有真拿到内容才敢清 error/truncated，否则会把"还需找回"的标记抹掉。
    if (variants[selectedIndex].content || variants[selectedIndex].echo) {
      target.error = undefined
      target.truncated = undefined
    }
    syncCurrentVariant(target)
    changed = true
  }

  // 去重算作有意义的变化（清理了重复的 variants）
  if (hadDuplicates) changed = true

  return changed
}
