import type { UiMessage } from '../types'
import { createId } from '../utils'
import { sessionHistoryRows, readArchiveEvent, restoredArchiveState, sessionMessageParts } from './history'
import { mergeAttachments, readMedia } from './media'
import { hydrateToolEvents, mergeToolEvents } from './toolHydration'
import { syncCurrentVariant } from './variants'
import { snapshotTranscript, type TranscriptState } from './transcriptStore'

function identity(message: UiMessage): string | undefined {
  if (message.replyVersionId && message.archiveEvent && message.replyVersionId !== message.archiveEvent.id) return undefined
  const id = message.archiveEvent?.id || message.replyVersionId
  return id ? `${message.role}:${id}` : undefined
}
const normalized = (text: string) => text.replace(/\s+/g, ' ').trim()
const covers = (incoming: string, local: string) => normalized(incoming).includes(normalized(local))

// Both originals are checkpointed before this merge. The newly loaded active
// branch wins; a different draft/roll/history stays accessible in its copy, not
// silently spliced into the next model request. Only identical known replies
// may contribute locally observed process data to that active branch.
export function mergeConcurrentTranscript(saved: TranscriptState, local: TranscriptState): TranscriptState {
  const result = snapshotTranscript(saved)
  // Keep an ordinary unsent draft when there is no saved input to displace.
  // Edit-mode drafts and attachment-only saved input are not empty composers.
  if (!saved.draft && !saved.pendingAttachments.length && !saved.editId && !local.editId) {
    const own = snapshotTranscript(local)
    result.draft = own.draft
    result.pendingAttachments = own.pendingAttachments
  }
  for (const message of result.messages) {
    const key = identity(message)
    if (!key || message.role !== 'assistant') continue
    const matches = local.messages.filter(item => identity(item) === key)
    const other = matches.length === 1 ? matches[0] : undefined
    if (!other || other.content !== message.content || other.echo !== message.echo) continue
    message.events = mergeToolEvents(message.events, other.events)
    message.attachments = mergeAttachments(message.attachments, other.attachments)
    if (!message.thinking) {
      message.thinking = other.thinking
      message.thinkingSegments = other.thinkingSegments.map(segment => ({ ...segment }))
    } else if (message.thinking === other.thinking && !message.thinkingSegments.length) {
      message.thinkingSegments = other.thinkingSegments.map(segment => ({ ...segment }))
    }
    if (!message.echoSegments.length) message.echoSegments = other.echoSegments.map(segment => ({ ...segment }))
    if (other.responseMeta) message.responseMeta = { ...other.responseMeta, ...message.responseMeta }
    syncCurrentVariant(message)
  }
  return result
}

function serverMessages(payload: Record<string, unknown>): UiMessage[] {
  const rows = sessionHistoryRows(payload)
  const messages: UiMessage[] = rows.filter(row => row.role === 'user' || row.role === 'assistant').map(row => {
    const event = readArchiveEvent(row.archive_event)
    const parts = sessionMessageParts(row.content)
    return {
      id: String(row.id || event?.id || createId('message')), role: row.role as 'user' | 'assistant',
      ...restoredArchiveState(row), content: parts.content, echo: row.role === 'assistant' ? parts.echo : '',
      echoSegments: row.role === 'assistant' && parts.echo
        ? [{ id: createId('echo'), content: parts.echo, textOffset: 0, streamOrder: 0 }] : [],
      thinking: '', thinkingSegments: [], events: [], attachments: readMedia(row.media), streaming: false,
      truncated: row.archive_pending === true || undefined,
      replyVersionId: row.role === 'assistant' ? String(row.source_id || event?.id || '') || undefined : undefined,
    }
  })
  hydrateToolEvents(messages, payload.recent_messages)
  return messages
}

// Local display history is not a disposable projection of the context window.
// Only exact identities may supplement it; an unrelated or shorter server
// window is not a deletion/branch-selection instruction.
export function mergeSessionHistory(local: UiMessage[], payload: Record<string, unknown>): UiMessage[] {
  const incoming = serverMessages(payload)
  if (!local.length) return incoming
  const byId = new Map(incoming.filter(message => identity(message)).map(message => [identity(message), message]))
  const result = local.map(message => {
    const key = identity(message)
    const server = key ? byId.get(key) : undefined
    if (!server) return message
    const merged: UiMessage = { ...message,
      attachments: mergeAttachments(message.attachments, server.attachments),
      events: mergeToolEvents(message.events, server.events),
    }
    if (!message.streaming && covers(server.content, message.content) && covers(server.echo, message.echo)) {
      merged.content = server.content
      merged.echo = server.echo
      if (!merged.echoSegments.length) merged.echoSegments = server.echoSegments
      // Snapshots may be intermediate. Completion is confirmed by reply recovery,
      // never by merely seeing a longer snapshot while opening a conversation.
    }
    if (message.variants) merged.variants = message.variants.map(variant => ({ ...variant }))
    syncCurrentVariant(merged)
    return merged
  })
  // Only a suffix following our exact active tail is eligible for append. If
  // the snapshot diverged earlier, do not splice another branch into this one.
  const tail = identity(local[local.length - 1])
  const anchor = tail ? incoming.findIndex(message => identity(message) === tail) : -1
  if (anchor >= 0) {
    const overlap = Math.min(anchor + 1, local.length)
    const continuous = Array.from({ length: overlap }, (_, index) => index)
      .every(offset => identity(local[local.length - 1 - offset])
        && identity(local[local.length - 1 - offset]) === identity(incoming[anchor - offset]))
    if (continuous) {
      const existing = new Set(local.map(identity).filter(Boolean))
      const suffix = incoming.slice(anchor + 1)
      if (suffix.every(message => identity(message) && !existing.has(identity(message)))) result.push(...suffix)
    }
  }
  hydrateToolEvents(result, payload.recent_messages)
  result.forEach(syncCurrentVariant)
  return result
}
