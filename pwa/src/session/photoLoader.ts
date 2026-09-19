import { fetchAlbumPhoto, resolveAlbumMedia, type RequestContext } from '../api/client'
import type { Attachment, UiMessage } from '../types'
import { readArchiveEvent } from './history'
import { mergeAttachments, photoSource, readMedia, wireMedia } from './media'
import { findCachedPhotos, photoDataUrl } from './photoStore'

function scope(ctx: RequestContext): string {
  return JSON.stringify([ctx.gatewayUrl, ctx.authToken, ctx.sessionTag])
}
function identity(message: UiMessage): string {
  const event = readArchiveEvent(message.archiveEvent)
  return event?.id || (message.role === 'assistant' ? message.replyVersionId || '' : '')
}

/** Owns transient, authenticated display URLs; never stores remote pixels in
 * the ordinary 30-photo cache and never fills a remote image into dataUrl.
 */
export function createPhotoLoader(
  getContext: () => RequestContext,
  getMessages: () => UiMessage[],
  onReferences: () => void = () => {},
) {
  let generation = 0
  let currentScope = ''
  let controller = new AbortController()
  let disposed = false
  const urls = new Map<string, string>()
  const loads = new Map<string, Promise<string>>()

  function reset() {
    controller.abort()
    controller = new AbortController()
    for (const url of urls.values()) URL.revokeObjectURL(url)
    urls.clear()
    loads.clear()
  }

  async function restore(): Promise<void> {
    if (disposed) return
    const run = ++generation
    const ctx = { ...getContext() }
    const key = scope(ctx)
    if (key !== currentScope) {
      reset()
      currentScope = key
      for (const message of getMessages()) for (const item of message.attachments) item.displayUrl = undefined
    }
    const source = getMessages()
    const entries = source.map((message) => ({message, eventId: identity(message)}))
    const valid = () => !disposed && generation === run && scope(getContext()) === key && getMessages() === source
    const matches = (entry: typeof entries[number]) => valid() && identity(entry.message) === entry.eventId
    const allAttachments = () => entries.filter(matches).flatMap(({message}) => message.attachments)
    const localTargets = entries.filter(({message}) => message.role === 'user')
      .flatMap(({message}) => message.attachments.filter((item) => !item.dataUrl))
    for (const item of allAttachments()) if (!photoSource(item)) item.photoState = 'loading'
    // Local images become visible before waiting for any network request.
    let localReadable = !localTargets.length
    try {
      const cached = await findCachedPhotos(localTargets)
      if (!valid()) return
      localReadable = true
      for (const {message, eventId} of entries) {
        if (message.role !== 'user' || identity(message) !== eventId) continue
        for (const item of message.attachments) {
          const photo = cached.get(item.id)
          if (photo && (!item.fingerprint || item.fingerprint === photo.fingerprint)) {
            item.dataUrl = photoDataUrl(photo)
            item.fingerprint = photo.fingerprint
            item.photoState = undefined
          }
        }
      }
    } catch {
      // Device storage can fail independently of the server album.
    }
    if (!valid()) return
    let resolved = false
    try {
      const events = entries.filter((entry) => entry.eventId).map(({message, eventId}) => ({role: message.role, event_id: eventId}))
      const fingerprints = [...new Set(allAttachments().flatMap((item) => item.fingerprint ? [item.fingerprint] : []))]
      const payload = await resolveAlbumMedia(ctx, events, fingerprints, controller.signal)
      if (!valid()) return
      resolved = true
      let referencesChanged = false
      for (const entry of entries) {
        if (!matches(entry)) continue
        const m = entry.message
        const before = JSON.stringify(wireMedia(m.attachments))
        m.attachments = mergeAttachments(m.attachments, readMedia(payload.media[`${m.role}:${entry.eventId}`]))
        for (const item of m.attachments) {
          const raw = item.fingerprint ? payload.photos[item.fingerprint] : undefined
          const reference = readMedia(raw && typeof raw === 'object' ? [{...raw, id:item.id, name:item.name, mime:item.mime}] : [])[0]
          if (reference?.photoId) Object.assign(item, {photoId: reference.photoId, title: reference.title, description: reference.description})
        }
        if (JSON.stringify(wireMedia(m.attachments)) !== before) referencesChanged = true
      }
      if (referencesChanged) onReferences()
    } catch {
      // Offline is not evidence that a photo was deleted or never saved.
    }
    if (!valid()) return
    const jobs = entries.filter(matches).flatMap((entry) => entry.message.attachments.map((item) => ({entry, item})))
    let next = 0
    async function worker() {
      while (next < jobs.length && valid()) {
        const {entry, item} = jobs[next++]
        if (!matches(entry)) continue
        if (photoSource(item)) { item.photoState = undefined; continue }
        if (!item.photoId) { item.photoState = resolved && localReadable ? 'cleared' : 'error'; continue }
        const photoId = item.photoId
        item.photoState = 'loading'
        try {
          let url = urls.get(photoId)
          if (!url) {
            let task = loads.get(photoId)
            if (!task) {
              const signal = controller.signal
              task = fetchAlbumPhoto(ctx, photoId, signal).then((blob) => {
                if (disposed || signal.aborted || currentScope !== key) throw new Error('stale photo load')
                const made = URL.createObjectURL(blob)
                urls.set(photoId, made)
                return made
              })
              loads.set(photoId, task)
              task.finally(() => { if (loads.get(photoId) === task) loads.delete(photoId) }).catch(() => {})
            }
            url = await task
          }
          if (matches(entry) && entry.message.attachments.includes(item) && item.photoId === photoId) {
            item.displayUrl = url
            item.photoState = undefined
          }
        } catch {
          if (matches(entry)) item.photoState = 'error'
        }
      }
    }
    // Bound concurrent image fetches independently of album size.
    await Promise.all(Array.from({length: Math.min(4, jobs.length)}, worker))
    if (!valid()) return
    const referenced = new Set(source.flatMap((m) => [...m.attachments, ...(m.variants || []).flatMap((v) => v.attachments || [])]).map((a) => a.photoId))
    for (const [photoId, url] of urls) if (!referenced.has(photoId)) { URL.revokeObjectURL(url); urls.delete(photoId) }
  }

  function retry(item?: Attachment) {
    if (item?.photoId) {
      const url = urls.get(item.photoId)
      if (url) URL.revokeObjectURL(url)
      urls.delete(item.photoId)
      for (const m of getMessages()) for (const a of m.attachments) if (a.photoId === item.photoId) a.displayUrl = undefined
    }
    return restore()
  }
  function dispose() { disposed = true; generation++; reset() }
  return { restore, retry, dispose }
}
