import type { Attachment, UiMessage } from '../types'
import { decodeStoredMessages, encodeStoredMessages } from './persistence'
import { storedAttachments } from './media'

export type ReadingPosition = { atBottom: boolean; messageId?: string; offset?: number }
export type TranscriptState = {
  messages: UiMessage[]
  draft: string
  pendingAttachments: Attachment[]
  editId: string | null
  viewport: ReadingPosition
}
export type SavedTranscript = { revision: number; savedAt: string; state: TranscriptState }
type SessionRecord = Omit<TranscriptState, 'messages'> & {
  schema: 1; key: string; revision: number; savedAt: string; rowKeys: string[]
}
type MessageRecord = { key: string; scope: string; json: string }

export class StorageConflictError extends Error {
  constructor() { super('另一页已经保存了新记录，本页暂停写入以免覆盖。请保留本页并导出未保存内容。') }
}

export function transcriptKey(gateway: string, session: string, base = window.location.href): string {
  const url = new URL(gateway.trim() || new URL(base).origin, base)
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('网关地址不正确')
  return JSON.stringify([`${url.origin}${url.pathname.replace(/\/+$/, '')}`, session])
}

export function snapshotTranscript(state: TranscriptState): TranscriptState {
  return {
    messages: encodeStoredMessages(state.messages), draft: state.draft,
    pendingAttachments: storedAttachments(state.pendingAttachments), editId: state.editId,
    viewport: { ...state.viewport },
  }
}

function rowKey(scope: string, message: UiMessage): string {
  return JSON.stringify([scope, message.role, message.archiveEvent?.id || message.replyVersionId || message.id])
}
function validate(record: SessionRecord): void {
  if (record.schema !== 1 || !Number.isInteger(record.revision) || record.revision < 1
    || !Array.isArray(record.rowKeys) || record.rowKeys.some(key => typeof key !== 'string')
    || new Set(record.rowKeys).size !== record.rowKeys.length) {
    throw new Error('本机记录来自其他版本或不完整，已停止覆写')
  }
}

// One atomic manifest + changed-message transaction per save. Superseded branch
// rows remain stored, but never reappear in the active branch sent to the model.
export class TranscriptStore {
  private connection?: Promise<IDBDatabase>
  constructor(private readonly name = 'shenyu-pwa-transcripts-v1') {}

  private open(): Promise<IDBDatabase> {
    if (this.connection) return this.connection
    this.connection = new Promise((resolve, reject) => {
      const request = indexedDB.open(this.name, 1)
      request.onupgradeneeded = () => {
        request.result.createObjectStore('sessions', { keyPath: 'key' })
        const rows = request.result.createObjectStore('messages', { keyPath: 'key' })
        rows.createIndex('scope', 'scope')
        request.result.createObjectStore('legacy', { keyPath: 'key' })
        request.result.createObjectStore('lists')
      }
      let blocked = false
      request.onblocked = () => { blocked = true; reject(new Error('另一页正在升级本机记录，请先关闭旧页面')) }
      request.onerror = () => { this.connection = undefined; reject(request.error) }
      request.onsuccess = () => {
        const db = request.result
        if (blocked) { db.close(); this.connection = undefined; return }
        db.onversionchange = () => { db.close(); this.connection = undefined }
        resolve(db)
      }
    })
    return this.connection
  }

  close(): void {
    const connection = this.connection
    this.connection = undefined
    void connection?.then(db => db.close()).catch(() => undefined)
  }

  private async transaction<T>(stores: string[], write: boolean,
    run: (tx: IDBTransaction, result: (value: T) => void, fail: (error: unknown) => void) => void): Promise<T> {
    const db = await this.open()
    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction(stores, write ? 'readwrite' : 'readonly', { durability: 'strict' })
      let output: T, failure: unknown
      const fail = (error: unknown) => { failure = error; try { tx.abort() } catch { reject(error) } }
      tx.oncomplete = () => resolve(output)
      tx.onabort = () => reject(failure || tx.error || new Error('本机保存中断，上一份记录未改变'))
      tx.onerror = () => { failure ||= tx.error }
      try { run(tx, value => { output = value }, fail) } catch (error) { fail(error) }
    })
  }

  async load(key: string): Promise<SavedTranscript | null> {
    return this.transaction(['sessions', 'messages'], false, (tx, result, fail) => {
      const request = tx.objectStore('sessions').get(key)
      request.onsuccess = () => {
        try {
          const record = request.result as SessionRecord | undefined
          if (!record) { result(null); return }
          validate(record)
          const messages: UiMessage[] = new Array(record.rowKeys.length)
          const finish = () => result({ revision: record.revision, savedAt: record.savedAt,
            state: { messages, draft: record.draft || '', pendingAttachments: storedAttachments(record.pendingAttachments),
              editId: record.editId || null, viewport: record.viewport || { atBottom: true } } })
          if (!messages.length) { finish(); return }
          let remaining = messages.length
          record.rowKeys.forEach((row, index) => {
            const read = tx.objectStore('messages').get(row)
            read.onsuccess = () => {
              try {
                if (!read.result || read.result.scope !== key) throw new Error('本机消息记录不完整，已停止覆写')
                const decoded = decodeStoredMessages([JSON.parse(read.result.json)])
                if (decoded.length !== 1) throw new Error('本机消息无法读取，已停止覆写')
                messages[index] = decoded[0]
                if (--remaining === 0) finish()
              } catch (error) { fail(error) }
            }
          })
        } catch (error) { fail(error) }
      }
    })
  }

  async save(key: string, state: TranscriptState, expectedRevision: number): Promise<number> {
    // Capture before the first await. A subsequent session switch must not alter
    // which gateway, session, draft or message this queued transaction writes.
    const detached = snapshotTranscript(state)
    const records: MessageRecord[] = detached.messages.map(message => ({
      key: rowKey(key, message), scope: key, json: JSON.stringify(message),
    }))
    if (new Set(records.map(row => row.key)).size !== records.length) throw new Error('消息身份重复，未覆盖本机记录')
    return this.transaction(['sessions', 'messages'], true, (tx, result, fail) => {
      const sessions = tx.objectStore('sessions'), rows = tx.objectStore('messages')
      const request = sessions.get(key)
      request.onsuccess = () => {
        try {
          const previous = request.result as SessionRecord | undefined
          if (previous) validate(previous)
          if ((previous?.revision || 0) !== expectedRevision) throw new StorageConflictError()
          for (const record of records) {
            const old = rows.get(record.key)
            old.onsuccess = () => {
              try { if (old.result?.json !== record.json) rows.put(record) } catch (error) { fail(error) }
            }
          }
          const { messages: _messages, ...metadata } = detached
          const revision = expectedRevision + 1
          sessions.put({ ...previous, ...metadata, schema: 1, key, revision,
            savedAt: new Date().toISOString(), rowKeys: records.map(row => row.key) } satisfies SessionRecord)
          result(revision)
        } catch (error) { fail(error) }
      }
    })
  }

  async readRetainedMessages(key: string): Promise<UiMessage[]> {
    return this.transaction(['messages'], false, (tx, result, fail) => {
      const request = tx.objectStore('messages').index('scope').getAll(key)
      request.onsuccess = () => {
        try { result(decodeStoredMessages(request.result.map((row: MessageRecord) => JSON.parse(row.json)))) }
        catch (error) { fail(error) }
      }
    })
  }

  async legacyBackup(key: string): Promise<string | null> {
    return this.transaction(['legacy'], false, (tx, result) => {
      const request = tx.objectStore('legacy').get(key)
      request.onsuccess = () => result(request.result?.raw ?? null)
    })
  }

  async migrateLegacySource(key: string, raw: string): Promise<void> {
    // This binding is global to the old single-slot format, not to the current
    // last-opened session. Changing settings or session must never relabel it.
    const source = await this.transaction<{ scope: string; raw: string }>(['legacy'], true, (tx, result, fail) => {
      const legacy = tx.objectStore('legacy')
      const request = legacy.get('single-slot-source-v1')
      request.onsuccess = () => {
        try {
          const value = request.result || { key: 'single-slot-source-v1', scope: key, raw }
          if (!request.result) legacy.put(value)
          result({ scope: value.scope, raw: value.raw })
        } catch (error) { fail(error) }
      }
    })
    const original: unknown = JSON.parse(source.raw)
    if (Array.isArray(original) && !original.length) return
    await this.migrateLegacy(source.scope, source.raw)
  }

  async migrateLegacy(key: string, raw: string): Promise<void> {
    // Never guess ownership from a deep-link URL. The caller supplies the old
    // stored gateway + session, and the exact raw value is kept independently.
    const backup = await this.legacyBackup(key)
    if (backup !== null) return
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) throw new Error('旧记录无法读取，未进行迁移')
    const messages = decodeStoredMessages(parsed)
    if (messages.length !== parsed.length) throw new Error('旧记录含无法识别的行，原件已保留')
    const current = await this.load(key)
    if (!current) {
      try {
        await this.save(key, { messages, draft: '', pendingAttachments: [], editId: null, viewport: { atBottom: true } }, 0)
      } catch (error) {
        if (!(error instanceof StorageConflictError)) throw error
      }
    }
    // Verify the durable copy before marking migration complete. Retrying after
    // a process death can finish the marker, but can never replace a newer copy.
    if (!await this.load(key)) throw new Error('迁移未能核验，旧记录仍然保留')
    await this.transaction(['legacy'], true, (tx, result) => {
      const request = tx.objectStore('legacy').get(key)
      request.onsuccess = () => {
        if (!request.result) tx.objectStore('legacy').put({ key, raw })
        result(undefined)
      }
    })
  }

  async loadList<T>(key: string): Promise<T | undefined> {
    return this.transaction(['lists'], false, (tx, result) => {
      const request = tx.objectStore('lists').get(key)
      request.onsuccess = () => result(request.result)
    })
  }
  async saveList(key: string, value: unknown): Promise<void> {
    return this.transaction(['lists'], true, (tx, result) => { tx.objectStore('lists').put(value, key); result(undefined) })
  }
}
