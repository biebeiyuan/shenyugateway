import { mergeAttachments, readMedia, wireMedia } from './media'
import type { MessageVariant, UiMessage } from '../types'
import { createId } from '../utils'
import { readArchiveEvent, restoredArchiveState, sessionMessageContent, sessionMessageParts } from './history'
import { hydrateToolEvents, mergeToolEvents, toolEventsFromRows, hasUnfinishedTools } from './toolHydration'
import { stripStatusSuffix } from '../meta/statusSuffix'
import { applyVariant, selectedVariantIndex, snapshotMessage, syncCurrentVariant } from './variants'

// Tail recovery has two inputs: /reply-recovery and the legacy recent_messages
// fallback. Both keep local data and require a known reply identity to match.
// Producer/storage/consumer contract: REQUEST_CONTEXT.md § Transcript identity and recovery.

type RecentRow = Record<string, unknown>

type RecoveryReply = {
  media?: unknown
  id?: unknown
  reply_version_id?: unknown
  archive_event?: unknown
  content?: unknown
  tool_rows?: unknown
}

type ReplyIdentity = Pick<MessageVariant, 'replyVersionId' | 'archiveEvent'>

function replyIdentity(value?: ReplyIdentity): string | undefined {
  return value?.replyVersionId || value?.archiveEvent?.id
}

function identityMatches(local: ReplyIdentity | undefined, incoming: ReplyIdentity): boolean {
  for (const value of [local, incoming]) {
    if (value?.replyVersionId && value.archiveEvent && value.replyVersionId !== value.archiveEvent.id) return false
  }
  const expected = replyIdentity(local)
  return !expected || expected === replyIdentity(incoming)
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
  local: { content: string; echo: string },
  incoming: { content: string; echo: string }
): boolean {
  // content 和 echo 用包含关系判断，容忍换行差异
  if (!covers(incoming.content, local.content)) return false
  if (!covers(incoming.echo, local.echo)) return false
  return true
}

// 只有已经开始过、后来变得不完整的 assistant 才有后台可找。
// 单独的 user 或普通 fetch error 不能证明请求到过网关。
export function tailNeedsReconcile(messages: UiMessage[]): boolean {
  const last = messages[messages.length - 1]
  if (!last || last.role !== 'assistant') return false
  return Boolean(last.truncated || hasUnfinishedTools(last.events))
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

  // 多个 assistant 行：直接首尾相连，不加分隔符。这包括多轮工具调用的所有回复
  // （第1轮、第3轮等）。轮边界是网关内部的事——流式客户端收到的就是各轮 content
  // 事件相连，后端落库也是 "".join，这里加 \n\n 会让护栏的 includes() 对不上，
  // 把本该放行的完整版当成不相干候选拒掉。
  // 继承最后一行的元数据（source_id 等），因为最后一段是收口行。
  const fullContent = assistantRows.map(r => String(r.content || '')).join('')
  return { ...assistantRows[assistantRows.length - 1], content: fullContent }
}

export function applyReconciledTail(messages: UiMessage[], payload: Record<string, unknown>): boolean {
  const last = messages[messages.length - 1]
  if (!last) return false
  // Explicit callers may still repair a known trailing user from server data.
  // The stricter tailNeedsReconcile() only controls automatic background polling.
  if (last.role === 'assistant' && !tailNeedsReconcile(messages)) return false
  const rows = recentRows(payload)
  if (!rows.length) return false

  const target = last.role === 'assistant' ? last : undefined
  const expectedVersion = replyIdentity(target)
  const versionedReply = expectedVersion
    ? rows.find((row) => row.role === 'assistant' && String(row.source_id || '') === expectedVersion)
    : undefined
  // A known version must never fall back to matching user text. Rolls share
  // that text, and an empty/common-prefix tail cannot distinguish their replies.
  if (expectedVersion && !versionedReply) return false
  let selectedReply = versionedReply
  if (!selectedReply) {
    const anchorUser = target ? messages[messages.length - 2] : last
    if (!anchorUser || anchorUser.role !== 'user') return false
    const anchorIndex = anchorRowIndex(rows, anchorUser.content)
    if (anchorIndex < 0) return false
    selectedReply = replyRowAfter(rows, anchorIndex)
  }
  if (!selectedReply) return false
  if (!identityMatches(target, {
    replyVersionId: String(selectedReply.source_id || '') || undefined,
    archiveEvent: readArchiveEvent(selectedReply.archive_event),
  })) return false
  const parts = sessionMessageParts(selectedReply.content)
  const attachments = readMedia(selectedReply.media)
  if (!parts.content && !parts.echo && !attachments.length) return false

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

    target.archiveEvent = target.archiveEvent || readArchiveEvent(selectedReply.archive_event)
    target.archiveReplay = true
    target.attachments = mergeAttachments(target.attachments, attachments)
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
      ...restoredArchiveState(selectedReply),
      role: 'assistant',
      content: parts.content,
      echo: parts.echo,
      echoSegments: parts.echo
        ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
        : [],
      attachments,
      thinking: '',
      thinkingSegments: [],
      events: [],
      streaming: false,
    })
  }
  // 快照只有正文；工具事件从原始 tool 行补回（只补 events 为空的行，安全）。
  hydrateToolEvents(messages, rows)
  messages.forEach(syncCurrentVariant)
  return true
}

function recoveryVariant(reply: RecoveryReply): MessageVariant | undefined {
  const parts = sessionMessageParts(reply.content)
  const attachments = readMedia(reply.media)
  if (!parts.content && !parts.echo && !attachments.length) return undefined
  const variant: MessageVariant = {
    attachments,
    ...restoredArchiveState(reply),
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
  variant.events = toolEventsFromRows(toolRows.filter(row => !row.reply_version_id
    || String(row.reply_version_id) === replyIdentity(variant)), String(reply.id || replyIdentity(variant) || 'recovery'))
  return variant
}

// 服务端永远没有 thinking，events 也只有塌到 offset 0 的补水版本。
// 本地有的一律以本地为准，服务端只补本地空着的字段。
function mergeRecoveredVariant(local: MessageVariant, incoming: MessageVariant): MessageVariant {
  return {
    ...incoming,
    attachments: mergeAttachments(local.attachments || [], incoming.attachments || []),
    thinking: local.thinking || incoming.thinking,
    thinkingSegments: local.thinkingSegments.length ? local.thinkingSegments : incoming.thinkingSegments,
    echoSegments: local.echoSegments.length ? local.echoSegments : incoming.echoSegments,
    events: mergeToolEvents(local.events, incoming.events),
    error: local.error ?? incoming.error,
    responseMeta: local.responseMeta ?? incoming.responseMeta,
  }
}

function variantKey(variant: MessageVariant): string {
  const identity = replyIdentity(variant)
  if (identity) return `id:${identity}`
  return `text:${variant.content}\u0000${variant.echo}`
}

// 找回只修当前这一条回复，服务端也只返回这一条。历史 roll 版本是纯本地状态
// （variants.ts 负责）：没有 per-request user id 时，重复的用户正文无法判定某条
// 旧回复属于哪一次请求，合进来就会把旧 roll 的正文挂到当前气泡上。
//
// 语义只有三种，没有例外分支：服务端涵盖本地且更长 → 写入并清标记；涵盖且完全
// 相同 → 确认无恙、清标记让退避链停下；不涵盖 → 什么都不做，标记留着继续退避。
export function applyReplyRecovery(messages: UiMessage[], payload: Record<string, unknown>): boolean {
  const candidates = (Array.isArray(payload.replies) ? payload.replies : [])
    .filter((item): item is RecoveryReply => Boolean(item && typeof item === 'object'))
    .map(recoveryVariant)
    .filter((item): item is MessageVariant => Boolean(item))
  if (!candidates.length) return false

  const lastUserIndex = messages.map((message) => message.role).lastIndexOf('user')
  if (lastUserIndex < 0) return false
  let target = messages[lastUserIndex + 1]
  // Validate the legacy user anchor BEFORE allocating a reply placeholder.
  // A known reply identity is stronger than any normalized visible text.
  if (!replyIdentity(target)) {
    const incomingUser = normalizeText(stripStatusSuffix(sessionMessageContent(payload.user_content)))
    const localUser = normalizeText(stripStatusSuffix(messages[lastUserIndex].content))
    if (!incomingUser || incomingUser !== localUser) return false
  }
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

  // 确保 variants 存在，但不要用 message 覆盖已有的 variant（保护 responseMeta 等字段）。
  // 这一步在任何提前返回之前完成：留下 variants: undefined 会让后续读它的代码炸。
  if (!target.variants?.length) {
    target.variants = [snapshotMessage(target)]
    target.selectedVariantIndex = 0
  } else {
    target.selectedVariantIndex = selectedVariantIndex(target)
    // 不调用 syncCurrentVariant，避免用 message 覆盖已有 variant 的 responseMeta
  }
  const variants = target.variants
  let changed = false
  const selectedKey = variantKey(variants[selectedVariantIndex(target)])
  // 去重老快照留下的重复项，但去重本身不算"变化"——它只是整理，不是找回。
  const uniqueVariants: MessageVariant[] = []
  const seenKeys = new Set<string>()
  for (const variant of variants) {
    const key = variantKey(variant)
    if (seenKeys.has(key)) continue
    seenKeys.add(key)
    uniqueVariants.push(variant)
  }
  if (uniqueVariants.length !== variants.length) {
    variants.splice(0, variants.length, ...uniqueVariants)
    // Removing an earlier duplicate shifts indexes, not the selected identity.
    target.selectedVariantIndex = variants.findIndex(variant => variantKey(variant) === selectedKey)
  }

  // 候选只认一条：本地有回复/归档身份就必须精确匹配，否则取最新那条。
  // 匹配不上 = 服务端手里不是这条回复，不碰，让退避链继续。
  const expectedVersion = replyIdentity(target)
  const candidate = expectedVersion
    ? candidates.find((item) => replyIdentity(item) === expectedVersion)
    : candidates[candidates.length - 1]
  if (!candidate || !identityMatches(target, candidate)) return changed
  // 只增不减：唯一的写入闸门，没有例外分支。服务端不涵盖本地就原样返回，
  // truncated/error 留着，让调用方按退避继续问——这正是"drain 还没写完"的样子。
  if (!acceptRecovery(
    { content: target.content || '', echo: target.echo || '' },
    { content: candidate.content, echo: candidate.echo }
  )) return changed

  // 到这里服务端这版确认涵盖本地（含完全相同）——本次找回成功。
  // 先清标记再写入：清在后面的话，快照已经带着旧 error 落进 variants 了。
  if (target.error || target.truncated) {
    target.error = undefined
    target.truncated = undefined
    changed = true
  }
  target.streaming = false
  if (!target.archiveReplay) {
    target.archiveReplay = true
    changed = true
  }
  if (!target.archiveEvent && candidate.archiveEvent) {
    target.archiveEvent = candidate.archiveEvent
    changed = true
  }

  const index = selectedVariantIndex(target)
  const contentChanged = normalizeText(candidate.content) !== normalizeText(target.content || '')
    || normalizeText(candidate.echo) !== normalizeText(target.echo || '')
  const attachments = mergeAttachments(target.attachments, candidate.attachments || [])
  const mediaChanged = JSON.stringify(wireMedia(attachments)) !== JSON.stringify(wireMedia(target.attachments))
  const mergedEvents = mergeToolEvents(target.events, candidate.events)
  const eventsChanged = JSON.stringify(mergedEvents) !== JSON.stringify(target.events)
  if (eventsChanged) {
    target.events = mergedEvents
    variants[index].events = mergedEvents.map(event => ({ ...event }))
    changed = true
  }
  if (contentChanged || mediaChanged) {
    // 服务端永远没有 thinking，events 只有塌到 offset 0 的补水版，echoSegments 只有单段，
    // responseMeta 压根不在恢复载荷里。本地有的一律以本地为准，服务端只补本地空着的。
    // error 例外：上面刚判定找回成功清掉了它，快照里那份不能再传染回来。
    const merged = { ...mergeRecoveredVariant(variants[index], candidate),
      archiveEvent: target.archiveEvent || candidate.archiveEvent, attachments, truncated: false, error: undefined }
    applyVariant(target, merged, index)
    syncCurrentVariant(target)
    changed = true
  } else {
    // Equal text still confirms completion. Keep that receipt on the selected
    // variant too, or switching away/back revives its pending/error state and
    // loses a newly recovered archive identity. Do not overwrite local metadata.
    if (!target.replyVersionId && candidate.replyVersionId) {
      target.replyVersionId = candidate.replyVersionId
      changed = true
    }
    Object.assign(variants[index], {
      replyVersionId: target.replyVersionId,
      archiveEvent: target.archiveEvent,
      archiveReplay: true,
      truncated: false,
      error: undefined,
    })
  }
  return changed
}
