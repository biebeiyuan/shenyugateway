import { computed, nextTick, reactive, ref, type Ref } from 'vue'
import type { Attachment, UiMessage } from '../types'
import type { RequestContext } from '../api/client'
import { TranscriptStore, StorageConflictError, snapshotTranscript, transcriptContentStamp, transcriptKey, type ReadingPosition, type TranscriptState, type RecoveryCopy, type RecoveryCopyInfo } from './transcriptStore'
import { getPhotos, photoDataUrl } from './photoStore'
import { mergeConcurrentTranscript } from './restore'

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
  const conflicts = reactive(new Set<string>())
  const epochs = new Map<string, number>()
  const recovering = ref(false), recoveryNotice = ref('')
  const recoveryCopies = ref<RecoveryCopyInfo[]>([])
  const selectedRecovery = ref<RecoveryCopy | null>(null)
  const activeKey = () => transcriptKey(deps.context().gatewayUrl, deps.context().sessionTag)
  const conflicted = computed(() => conflicts.has(activeKey()))
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
    if (!ready.value || disposed || restoring || recovering.value) return Promise.resolve(false)
    const context = { ...deps.context() }
    const key = transcriptKey(context.gatewayUrl, context.sessionTag)
    const epoch = epochs.get(key) || 0
    let state: TranscriptState
    try { state = snapshot() } catch {
      error.value = '本机记录无法序列化，上一份记录未改变。'
      return Promise.resolve(false)
    }
    pendingWrites.value++
    const task = (queues.get(key) || Promise.resolve()).catch(() => undefined).then(async () => {
      // A resync invalidates captured stale snapshots, not just their revision.
      if (epoch !== (epochs.get(key) || 0)) return false
      if (conflicts.has(key)) throw new StorageConflictError()
      const revision = await store.save(key, state, revisions.get(key) || 0)
      revisions.set(key, revision)
      if (key === transcriptKey(deps.context().gatewayUrl, deps.context().sessionTag)) {
        savedAt.value = new Date().toISOString(); error.value = ''
      }
      return true
    })
    queues.set(key, task)
    return task.then(value => value, reason => {
      if (epoch !== (epochs.get(key) || 0)) return false
      if (reason instanceof StorageConflictError) conflicts.add(key)
      if (key === activeKey()) error.value = reason instanceof Error ? reason.message : '本机保存失败，上一份完整记录仍在。'
      return false
    }).finally(() => { pendingWrites.value-- })
  }

  function scheduleSave() {
    if (!ready.value || disposed || restoring || recovering.value) return
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => { void save() }, 250)
  }

  async function load(context: RequestContext) {
    const key = transcriptKey(context.gatewayUrl, context.sessionTag)
    await queues.get(key)?.catch(() => undefined)
    const record = await store.load(key)
    revisions.set(key, record?.revision || 0)
    // A read alone cannot unlock a stale writer: its live state may still be
    // older. Only the protected resync below may clear the conflict latch.
    return record
  }

  async function refreshRecoveryCopies() {
    const key = activeKey()
    selectedRecovery.value = null
    recoveryCopies.value = []
    try {
      const copies = await store.listRecoveryCopies(key)
      if (!disposed && key === activeKey()) recoveryCopies.value = copies
    } catch {
      if (!disposed && key === activeKey()) error.value = '保留副本暂时无法读取；没有删除任何记录。'
    }
  }

  async function inspectRecoveryCopy(id: string) {
    const key = activeKey()
    try {
      const copy = await store.loadRecoveryCopy(key, id)
      if (!disposed && key === activeKey()) selectedRecovery.value = copy
    } catch (reason) {
      if (key === activeKey()) error.value = reason instanceof Error ? reason.message : '副本暂时无法读取'
    }
  }

  async function protectedRestore(copyId?: string, isCurrent: () => boolean = () => true): Promise<boolean> {
    if (!ready.value || disposed || recovering.value) return false
    const key = activeKey()
    if (!copyId && !conflicts.has(key)) return false
    if (copyId && conflicts.has(key)) {
      error.value = '请先重新同步当前对话，再找回这份草稿；本页和副本都未改变。'
      return false
    }
    const epoch = (epochs.get(key) || 0) + 1
    epochs.set(key, epoch)
    recovering.value = true
    clearTimeout(saveTimer)
    const current = () => !disposed && isCurrent() && key === activeKey() && epoch === epochs.get(key)
    try {
      // Finish already-running writes, discard all queued pre-resync snapshots.
      await queues.get(key)?.catch(() => undefined)
      if (!current()) return false
      const local = snapshot()
      const captured = transcriptContentStamp(local)
      const assertUnchanged = () => {
        if (!current()) throw new Error('页面已切换，未把旧会话恢复到新页面。')
        if (transcriptContentStamp(snapshot()) !== captured) throw new Error('本页有新改动，已保留当前内容；请重新同步。')
      }
      await store.saveRecoveryCopy(key, local, copyId ? 'before-draft' : 'local')
      assertUnchanged()
      const latest = await store.load(key)
      if (!latest) throw new Error('最新记录暂时无法读取；本页副本已保留，未替换页面。')
      let next: TranscriptState
      if (copyId) {
        // Draft retrieval must not rebase a stale transcript onto a newer CAS.
        if (latest.revision !== revisions.get(key)) throw new StorageConflictError()
        const copy = await store.loadRecoveryCopy(key, copyId)
        if (!copy) throw new Error('没有找到这份会话副本，未替换输入内容。')
        next = { ...local, draft: copy.state.draft, pendingAttachments: copy.state.pendingAttachments, editId: null }
      } else {
        await store.saveRecoveryCopy(key, latest.state, 'saved')
        next = mergeConcurrentTranscript(latest.state, local)
      }
      assertUnchanged()
      // Still CAS-protected: another write during the read/checkpoint/merge
      // makes this fail without changing live state. Never blindly retry it.
      next.viewport = position()
      const revision = await store.save(key, next, latest.revision)
      assertUnchanged()
      // A swipe while storage was busy must not fail recovery or jump backwards.
      next.viewport = position()
      await apply(next, current)
      if (!current()) return false
      revisions.set(key, revision)
      conflicts.delete(key)
      error.value = ''
      savedAt.value = new Date().toISOString()
      recoveryNotice.value = copyId
        ? '草稿已放回输入框，替换前的内容也已保留。没有发送消息。'
        : '已重新同步，可以继续保存。本页和另一页的原记录都在保留副本中，分歧草稿可单独找回。'
      await refreshRecoveryCopies()
      return true
    } catch (reason) {
      // Failed recovery does not turn a stale page into an authorized writer.
      if (reason instanceof StorageConflictError) conflicts.add(key)
      if (current()) error.value = reason instanceof Error ? reason.message : '重新同步失败，本页与已保存记录都未删除。'
      return false
    } finally {
      recovering.value = false
    }
  }

  const recoverConflict = (isCurrent?: () => boolean) => protectedRestore(undefined, isCurrent)
  const restoreRecoveryDraft = (id: string, isCurrent?: () => boolean) => protectedRestore(id, isCurrent)

  async function removeRecoveryCopy(id: string): Promise<boolean> {
    if (!ready.value || disposed || recovering.value) return false
    const key = activeKey()
    try {
      const removed = await store.removeRecoveryCopy(key, id)
      if (!disposed && key === activeKey()) {
        await refreshRecoveryCopies()
        recoveryNotice.value = removed ? '已移除这份恢复副本，当前聊天和其他副本未改变。' : '这份副本已不在本机，当前聊天未改变。'
      }
      return removed
    } catch {
      if (!disposed && key === activeKey()) error.value = '副本未能移除，请重试；当前聊天没有改变。'
      return false
    }
  }

  async function apply(state: TranscriptState, isCurrent: () => boolean = () => true) {
    if (disposed || !isCurrent()) return
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

  function downloadRecord(value: unknown) {
    const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url; link.download = `shenyu-local-record-${Date.now()}.json`
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  function exportCurrent() {
    try {
      downloadRecord({ schema: 1, context: { gatewayUrl: deps.context().gatewayUrl, sessionTag: deps.context().sessionTag },
        state: snapshot(), legacyUnboundRaw: localStorage.getItem('shenyu_pwa_messages') })
    } catch { error.value = '本页暂时无法导出，请保持页面打开；没有删除记录。' }
  }

  async function exportRecoveryCopy(id: string) {
    const key = activeKey()
    try {
      const copy = await store.loadRecoveryCopy(key, id)
      if (copy && !disposed && key === activeKey()) downloadRecord(copy)
    } catch { if (key === activeKey()) error.value = '副本暂时无法导出，原件仍然保留。' }
  }

  function dispose() {
    clearTimeout(saveTimer)
    // This is an extra checkpoint only. Durable work is submitted during use.
    const final = save()
    disposed = true
    void final.finally(() => store.close())
  }

  return { store, ready, error, savedAt, saving, save, scheduleSave, load, apply, position, restorePosition, exportCurrent, dispose,
    conflicted, recovering, recoveryNotice, recoveryCopies, selectedRecovery, recoverConflict, restoreRecoveryDraft,
    refreshRecoveryCopies, inspectRecoveryCopy, exportRecoveryCopy, removeRecoveryCopy }
}
