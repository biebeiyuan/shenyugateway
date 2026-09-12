import type { MessageVariant, UiMessage } from '../types'
import { createId } from '../utils'
import { sessionMessageContent, sessionMessageParts } from './history'
import { hydrateToolEvents } from './toolHydration'
import { applyVariant, ensureVariants, selectedVariantIndex, snapshotMessage, syncCurrentVariant } from './variants'

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

// 服务端这份是否涵盖本地这份：包含关系判断。
// 断流时本地是完整回复的前缀，此判据天然成立且不受换行差异影响。
function covers(incoming: string, local: string): boolean {
  const a = normalizeText(incoming)
  const b = normalizeText(local)
  return !b || a.includes(b)
}

// 只增不减护栏：自动找回这条路在物理上没有能力削短任何东西。
// 任何会让本地内容变少的操作一律拒绝，宁可留着 truncated 让退避链继续。
function acceptRecovery(
  local: { content: string; echo: string; events?: unknown[]; thinking?: string },
  incoming: { content: string; echo: string; events?: unknown[]; thinking?: string }
): boolean {
  // content 和 echo 用包含关系判断，容忍换行差异
  if (!covers(incoming.content, local.content)) return false
  if (!covers(incoming.echo, local.echo)) return false

  // events 和 thinking 只在传入时才比较（某些路径不涉及这些字段）
  if (local.events !== undefined && incoming.events !== undefined) {
    if (incoming.events.length < local.events.length) return false
  }
  if (local.thinking && incoming.thinking !== undefined) {
    if (!incoming.thinking) return false
  }

  return true
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
  const assistantRows: RecentRow[] = []
  for (let index = anchorIndex + 1; index < rows.length; index++) {
    if (rows[index].role === 'user') break
    if (rows[index].role === 'assistant') assistantRows.push(rows[index])
  }
  if (!assistantRows.length) return undefined
  if (assistantRows.length === 1) return assistantRows[0]
  // 多个 assistant 行：拼接完整的工具回合内容，段落间用 \n\n 对齐本地流式约定
  // 继承最后一行的元数据（source_id 等），因为最后一段是收口行
  const fullContent = assistantRows.map(r => String(r.content || '')).join('\n\n')
  return { ...assistantRows[assistantRows.length - 1], content: fullContent }
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
    const nextContent = parts.content
    const nextEcho = parts.echo

    // 只增不减护栏：检查服务端内容是否涵盖本地
    if (!acceptRecovery(
      { content: target.content || '', echo: target.echo || '' },
      { content: nextContent, echo: nextEcho }
    )) {
      return false
    }

    target.content = nextContent
    target.echo = nextEcho
    // 只在本地没有 echoSegments 时才用服务端的（服务端只能给 offset 0 的单段）
    if (!target.echoSegments.length) {
      target.echoSegments = nextEcho
        ? [{ id: createId('echo'), content: nextEcho, textOffset: 0, streamOrder: 0 }]
        : []
    }
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
    responseMeta: undefined,
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
    echoSegments: local.echoSegments.length ? local.echoSegments : incoming.echoSegments,
    events: local.events.length ? local.events : incoming.events,
    error: local.error ?? incoming.error,
    responseMeta: local.responseMeta ?? incoming.responseMeta,
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

  // 确保 variants 存在，但不要用 message 覆盖已有的 variant（保护 responseMeta 等字段）
  if (!target.variants?.length) {
    target.variants = [snapshotMessage(target)]
    target.selectedVariantIndex = 0
  } else {
    target.selectedVariantIndex = selectedVariantIndex(target)
    // 不调用 syncCurrentVariant，避免用 message 覆盖已有 variant 的 responseMeta
  }
  const variants = target.variants
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
  // 修复槽位：当 target 有 error/truncated 且只有一个 variant 时，
  // 第一个 candidate 可以直接替换它，但这个机会只能用一次
  let repairSlotUsed = false
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
    const isRepairSlot = index < 0 && !repairSlotUsed && variants.length === 1 && (target.error || target.truncated)
    if (isRepairSlot) {
      index = 0
      repairSlotUsed = true
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

      // 修复槽位时跳过护栏（本地是截断残片，服务端是完整版本，可能完全不同）
      if (isRepairSlot) {
        variants[index] = merged
        if (previous.content !== merged.content || previous.echo !== merged.echo
            || (!previous.events.length && merged.events.length)
            || (!previous.replyVersionId && merged.replyVersionId && !hadCompleteContent)) {
          changed = true
        }
      } else {
        // 护栏：服务端这版是否涵盖本地？不涵盖就只补空字段，正文不动
        const serverCovers = acceptRecovery(
          { content: previous.content, echo: previous.echo, events: previous.events, thinking: previous.thinking },
          { content: merged.content, echo: merged.echo, events: merged.events, thinking: merged.thinking }
        )

        if (!serverCovers) {
          // 服务端更短：只补 replyVersionId，正文、回响、events、thinking 一律不动
          const updated = { ...previous, replyVersionId: merged.replyVersionId ?? previous.replyVersionId }
          const addedVersionId = !previous.replyVersionId && updated.replyVersionId
          variants[index] = updated
          // 只有首次添加 replyVersionId 且原消息不完整时才算 changed
          if (addedVersionId && !hadCompleteContent) {
            changed = true
          }
        } else {
          // 服务端涵盖本地：检查是否真的有变化
          const contentChanged = previous.content !== merged.content || previous.echo !== merged.echo
          const eventsAdded = !previous.events.length && merged.events.length
          const addedVersionId = !previous.replyVersionId && merged.replyVersionId

          variants[index] = merged

          // 只有真正变化时才标记 changed
          if (contentChanged || eventsAdded || (addedVersionId && !hadCompleteContent)) {
            changed = true
          }
        }
      }
    }
    if (candidateId) recoveredIds.add(candidateId)
  }
  // Keep recovered rolls in server order, then retain any local-only variants
  // (for example an in-flight draft) after them.
  // 在重排前记录当前选中的 variant 对象
  const currentlySelected = variants[target.selectedVariantIndex ?? 0]

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

  // 重排后重新找到之前选中的 variant 的新索引
  const currentIndex = currentlySelected
    ? variants.findIndex(v => v === currentlySelected)
    : 0

  const selected = originalSelectedId
    ? variants.findIndex((variant) => variant.replyVersionId === originalSelectedId)
    : -1
  const lastRecovered = replies[replies.length - 1]
  const lastRecoveredIndex = lastRecovered?.replyVersionId
    ? variants.findIndex((variant) => variant.replyVersionId === lastRecovered.replyVersionId)
    : variants.findIndex((variant) => variant.content === lastRecovered?.content && variant.echo === lastRecovered.echo)
  const priorError = target.error
  const priorTruncated = target.truncated
  // 只有在以下情况才切换到 lastRecovered：
  // 1. 原本就选中了（selected >= 0）
  // 2. 或者本地有 error/truncated（需要修复）
  const selectedIndex = selected >= 0 ? selected : (priorError || priorTruncated ? lastRecoveredIndex : currentIndex)

  const applied = variants[selectedIndex]
  // 判断是否真的拿到了更好的内容：
  // 1. 服务端涵盖本地 且 内容确实不同
  // 2. 或者本地有 error/truncated，任何不同的内容都算改善
  const improved = Boolean(applied) && (
    ((covers(applied.content, target.content || '') || covers(applied.echo, target.echo || ''))
      && (applied.content !== target.content || applied.echo !== target.echo)) ||
    ((priorError || priorTruncated) && (applied.content !== target.content || applied.echo !== target.echo))
  )

  // 应用 variant 的条件：
  // 1. selectedIndex 变了（切换到不同的 variant）
  // 2. 内容真的改善了（improved = true）
  const needsApply = selectedIndex >= 0 && (currentIndex !== selectedIndex || improved)

  if (needsApply) {
    applyVariant(target, applied, selectedIndex)
    target.streaming = false
    // 只有真的改善了才清除 error/truncated，否则恢复原标记
    if (improved) {
      target.error = undefined
      target.truncated = undefined
    } else {
      target.error = priorError
      target.truncated = priorTruncated
    }
    syncCurrentVariant(target)
    changed = true
  }

  return changed
}
