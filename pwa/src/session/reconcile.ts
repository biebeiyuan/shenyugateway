import type { UiMessage } from '../types'
import { createId } from '../utils'
import { sessionMessageContent, sessionMessageParts } from './history'
import { hydrateToolEvents } from './toolHydration'

// 尾部对账：后台断流后，从 session detail 的 recent_messages（gateway_messages
// 原始行）里把服务端 drain 落库的完整回复找回来。只修尾巴，绝不整体替换——
// openSession 的整体替换对本地 attachments/thinking 有损，仅用于切会话。
//
// 锚点约定：先在服务端行里从尾部找到与本地末轮 user 消息内容一致的行，再取其后
// 的 assistant 行。锚不上（服务端最新 user 行不是我们这条）就返回 false，让调用
// 方按退避重试——这正是"服务端还没 drain 完"的样子。

type RecentRow = Record<string, unknown>

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
  const anchorUser = target ? messages[messages.length - 2] : last
  if (!anchorUser || anchorUser.role !== 'user') return false

  const anchorIndex = anchorRowIndex(rows, anchorUser.content)
  if (anchorIndex < 0) return false
  const replyRow = replyRowAfter(rows, anchorIndex)
  if (!replyRow) return false
  const parts = sessionMessageParts(replyRow.content)
  if (!parts.content && !parts.echo) return false

  if (target) {
    // 只有服务端文本更长才替换——drain 比本地流断点走得更远才有找回的意义。
    const serverLength = parts.content.length + parts.echo.length
    const localLength = (target.content || '').length + (target.echo || '').length
    if (serverLength <= localLength) return false
    target.content = parts.content
    target.echo = parts.echo
    target.echoSegments = parts.echo
      ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }]
      : []
    target.error = undefined
    target.truncated = undefined
    target.streaming = false
  } else {
    messages.push({
      id: String(replyRow.id || createId('message')),
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
