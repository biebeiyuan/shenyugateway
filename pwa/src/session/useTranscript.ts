import { computed, nextTick, ref, type Ref } from 'vue'
import type { Attachment, UiMessage } from '../types'
import type { RequestContext } from '../api/client'
import { TranscriptStore, StorageConflictError, snapshotTranscript, transcriptKey, type ReadingPosition, type TranscriptState } from './transcriptStore'
import { getPhotos, photoDataUrl } from './photoStore'

type Deps = {
  context: () => RequestContext
  messages: Ref<UiMessage[]>
  draft: Ref<string>
  pendingAttachments: Ref<Attachment[]>
  editId: Ref<string | null>
  stream: Ref<HTMLElement | null>
}

export function useTranscript(deps: Deps) {
  const store = new TranscriptStore()
  const ready = ref(false), error = ref(''), savedAt = ref(''), pendingWrites = ref(0)
  const revisions = new Map<string, number>()
  const queues = new Map<string, Promise<unknown>>()
  const conflicts = new Set<string>()
  let disposed = false, restoring = false
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  const saving = computed(() => pendingWrites.value > 0)

  function position(): ReadingPosition {
    const stream = deps.stream.value
    if (!stream) return { atBottom: true }
    if (stream.scrollHeight - stream.scrollTop - stream.clientHeight < 80) return { atBottom: true }
    const top = stream.getBoundingClientRect().top
    const first = Array.from(stream.querySelectorAll<HTMLElement>('[data-message-id]'))
      .find(row => row.getBoundingClientRect().bottom > top)
    return { atBottom: false, messageId: first?.dataset.messageId, offset: first ? first.getBoundingClientRect().top - top : 0 }
  }

  function restorePosition(value: ReadingPosition) {
    const stream = deps.stream.value
    if (!stream) return
    if (value.atBottom) { stream.scrollTop = stream.scrollHeight; return }
    const row = Array.from(stream.querySelectorAll<HTMLElement>('[data-message-id]'))
      .find(item => item.dataset.messageId === value.messageId)
    if (row) stream.scrollTop += row.getBoundingClientRect().top - stream.getBoundingClientRect().top - (value.offset || 0)
  }

  function snapshot(): TranscriptState {
    return snapshotTranscript({ messages: deps.messages.value, draft: deps.draft.value,
      pendingAttachments: deps.pendingAttachments.value, editId: deps.editId.value, viewport: position() })
  }

  function save(): Promise<boolean> {
    clearTimeout(saveTimer)
    if (!ready.value || disposed || restoring) return Promise.resolve(false)
    const context = { ...deps.context() }
    const key = transcriptKey(context.gatewayUrl, context.sessionTag)
    let state: TranscriptState
    try { state = snapshot() } catch {
      error.value = '本机记录无法序列化，上一份记录未改变。'
      return Promise.resolve(false)
    }
    pendingWrites.value++
    const task = (queues.get(key) || Promise.resolve()).catch(() => undefined).then(async () => {
      if (conflicts.has(key)) throw new StorageConflictError()
      const revision = await store.save(key, state, revisions.get(key) || 0)
      revisions.set(key, revision)
      if (key === transcriptKey(deps.context().gatewayUrl, deps.context().sessionTag)) {
        savedAt.value = new Date().toISOString(); error.value = ''
      }
    })
    queues.set(key, task)
    return task.then(() => true, reason => {
      if (reason instanceof StorageConflictError) conflicts.add(key)
      error.value = reason instanceof Error ? reason.message : '本机保存失败，上一份完整记录仍在。'
      return false
    }).finally(() => { pendingWrites.value-- })
  }

  function scheduleSave() {
    if (!ready.value || disposed || restoring) return
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => { void save() }, 250)
  }

  async function load(context: RequestContext) {
    const key = transcriptKey(context.gatewayUrl, context.sessionTag)
    await queues.get(key)?.catch(() => undefined)
    const record = await store.load(key)
    revisions.set(key, record?.revision || 0)
    return record
  }

  async function apply(state: TranscriptState, isCurrent: () => boolean = () => true) {
    restoring = true
    clearTimeout(saveTimer)
    deps.messages.value = state.messages
    deps.draft.value = state.draft
    deps.pendingAttachments.value = state.pendingAttachments
    deps.editId.value = state.editId
    await nextTick()
    if (isCurrent()) restorePosition(state.viewport)
    restoring = false
    // Draft image bytes use the existing 30-photo store, never transcript storage.
    void getPhotos(state.pendingAttachments.map(item => item.id)).then(photos => {
      if (!isCurrent() || disposed) return
      for (const attachment of deps.pendingAttachments.value) {
        const photo = photos.get(attachment.id)
        if (photo) attachment.dataUrl = photoDataUrl(photo)
      }
    }).catch(() => undefined)
  }

  function exportCurrent() {
    const blob = new Blob([JSON.stringify({ schema: 1, context: { gatewayUrl: deps.context().gatewayUrl,
      sessionTag: deps.context().sessionTag }, state: snapshot(), legacyUnboundRaw: localStorage.getItem('shenyu_pwa_messages') }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url; link.download = `shenyu-local-record-${Date.now()}.json`
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  function dispose() {
    clearTimeout(saveTimer)
    // This is an extra checkpoint only. Durable work is submitted during use.
    const final = save()
    disposed = true
    void final.finally(() => store.close())
  }

  return { store, ready, error, savedAt, saving, save, scheduleSave, load, apply, position, restorePosition, exportCurrent, dispose }
}
