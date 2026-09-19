import type { Attachment, UiMessage } from '../types'
import type { ToolEvent } from '../toolLanguage'

// Only stable references cross the wire or survive reload. A display URL is
// deliberately a different field from the user-upload dataUrl.
const PHOTO_ID = /^phot_[a-zA-Z0-9_-]{1,100}$/
const FINGERPRINT = /^[a-f0-9]{64}$/

export function storedAttachments(value: unknown): Attachment[] {
  if (!Array.isArray(value)) return []
  const result: Attachment[] = []
  const seen = new Set<string>()
  for (const raw of value.slice(0, 9)) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    if (typeof item.id !== 'string' || !item.id || item.id.length > 160 || seen.has(item.id)) continue
    seen.add(item.id)
    const attachment: Attachment = {
      id: item.id,
      name: typeof item.name === 'string' ? item.name.slice(0, 256) : '照片',
      mime: typeof item.mime === 'string' ? item.mime.slice(0, 80) : 'image/jpeg',
    }
    if (typeof item.fingerprint === 'string' && FINGERPRINT.test(item.fingerprint)) attachment.fingerprint = item.fingerprint
    if (typeof item.photoId === 'string' && PHOTO_ID.test(item.photoId)) {
      attachment.photoId = item.photoId
      attachment.title = typeof item.title === 'string' ? item.title : ''
      attachment.description = typeof item.description === 'string' ? item.description : ''
    }
    result.push(attachment)
  }
  return result
}

export function readMedia(value: unknown): Attachment[] {
  if (!Array.isArray(value)) return []
  return storedAttachments(value.map((item) => item && typeof item === 'object' ? {
    id: item.id, name: item.name, mime: item.mime, fingerprint: item.fingerprint,
    photoId: item.photo_id, title: item.title, description: item.content,
  } : null))
}

export function wireMedia(attachments: Attachment[], imageIndexes = false): Record<string, unknown>[] {
  let blockIndex = 0
  const positions = new Map(attachments.map((item) => [item.id,
    item.dataUrl?.startsWith('data:') || item.fingerprint ? blockIndex++ : null]))
  return storedAttachments(attachments).map(({ photoId, title, description, ...item }) => ({
    ...item,
    ...(imageIndexes ? { image_index: positions.get(item.id) ?? null } : {}),
    ...(photoId ? { photo_id: photoId, title, content: description } : {}),
  }))
}

export function photoSource(attachment: Attachment): string {
  return attachment.dataUrl || attachment.displayUrl || ''
}

export function mergeAttachments(local: Attachment[], incoming: Attachment[]): Attachment[] {
  const merged = local.map((item) => ({ ...item }))
  for (const item of incoming) {
    const index = merged.findIndex((candidate) => candidate.id === item.id)
    if (index < 0) merged.push({ ...item })
    else {
      const previous = merged[index]
      merged[index] = { ...previous, ...item }
      if (previous.photoId !== item.photoId && item.photoId) {
        merged[index].displayUrl = undefined
        merged[index].photoState = undefined
      }
    }
  }
  return merged.slice(0, 9)
}

export function receiveSharedPhoto(message: UiMessage, event: ToolEvent): void {
  const identity = message.replyVersionId || message.archiveEvent?.id
  if (!identity || (message.replyVersionId && message.archiveEvent && message.replyVersionId !== message.archiveEvent.id)) return
  if (event.phase !== 'tool_end' || event.ok !== true || event.reply_version_id !== identity) return
  if ((event.target_tool || event.name) !== 'shenyu_album_send') return
  const photos = readMedia([event.photo]).filter((photo) => photo.photoId && photo.id === event.tool_call_id)
  if (photos.length) message.attachments = mergeAttachments(message.attachments, photos)
}
