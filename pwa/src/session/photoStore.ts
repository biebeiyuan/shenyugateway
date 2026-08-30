// 聊天图的本机保管处。
//
// 之前附件根本不落盘（persistence.ts 存与读都置空 attachments），刷新即失。
// 原因大概是怕挤爆 localStorage——一张 1600px dataURL 约 560KB，5MB 配额只装
// 九张。localStorage 存字符串，本来就不是放图片的容器。
//
// 这里用 IndexedDB 存 Blob：省掉 base64 的 33% 膨胀，配额是几百 MB 级。消息里
// 只留 attachment id 和指纹，图本身按 id 取。
//
// 保留最近 STORED_PHOTO_LIMIT 张，更早的本机淘汰——「随手发的图不用全留」。
// 注意这只管手机上还能不能看到图；发给上游的仍是最近两轮，那是网关的事
// （context_layers.py::trim_client_image_blocks）。真想长期留一张，走相册
// （shenyu_album_save），那边不限张数、不会过期。

const DB_NAME = 'shenyu_pwa_photos'
const DB_VERSION = 1
const STORE = 'photos'

// 照分享里那份设计：最近 30 张。按长边 1080 / 质量 0.7 约 150KB/张，合计约 4.5MB。
export const STORED_PHOTO_LIMIT = 30

export type StoredPhoto = {
  id: string
  mime: string
  // 存 ArrayBuffer 而不是 Blob。structured clone 对 ArrayBuffer 的支持处处一致，
  // 而 Blob 在 IndexedDB 里历史上踩过坑（旧版 Safari），测试环境的 shim 也不保留
  // 它。读回时再包成 Blob，调用方拿到的仍是 Blob。
  bytes: ArrayBuffer
  // 图片字节的 sha256，与网关侧 store/_album.py::photo_fingerprint 同一个算法。
  // 过期后 PWA 用它代替真图上传，网关据此认出这张图是相册里的哪一张。
  fingerprint: string
  byteSize: number
  savedAt: number
}

export type PhotoMeta = Omit<StoredPhoto, 'bytes'>

export type LoadedPhoto = PhotoMeta & { blob: Blob }

let dbPromise: Promise<IDBDatabase> | null = null

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('indexedDB unavailable'))
      return
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: 'id' })
        store.createIndex('savedAt', 'savedAt')
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('indexedDB open failed'))
  })
  // 打开失败不缓存失败的 promise，下次还能重试。
  dbPromise.catch(() => { dbPromise = null })
  return dbPromise
}

function runRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('indexedDB request failed'))
  })
}

async function digestHex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

export async function photoFingerprint(blob: Blob): Promise<string> {
  return await digestHex(await blob.arrayBuffer())
}

function toLoaded(row: StoredPhoto): LoadedPhoto {
  const { bytes, ...meta } = row
  return { ...meta, blob: new Blob([bytes], { type: row.mime }) }
}

export async function putPhoto(id: string, blob: Blob, mime: string): Promise<PhotoMeta> {
  const bytes = await blob.arrayBuffer()
  const fingerprint = await digestHex(bytes)
  const meta: PhotoMeta = { id, mime, fingerprint, byteSize: blob.size, savedAt: Date.now() }
  const db = await openDb()
  const tx = db.transaction(STORE, 'readwrite')
  tx.objectStore(STORE).put({ ...meta, bytes } satisfies StoredPhoto)
  await new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error || new Error('indexedDB write failed'))
    tx.onabort = () => reject(tx.error || new Error('indexedDB write aborted'))
  })
  return meta
}

export async function getPhoto(id: string): Promise<LoadedPhoto | undefined> {
  const db = await openDb()
  const tx = db.transaction(STORE, 'readonly')
  const row = await runRequest<StoredPhoto | undefined>(tx.objectStore(STORE).get(id))
  return row ? toLoaded(row) : undefined
}

export async function getPhotos(ids: string[]): Promise<Map<string, LoadedPhoto>> {
  const found = new Map<string, LoadedPhoto>()
  if (!ids.length) return found
  const db = await openDb()
  const tx = db.transaction(STORE, 'readonly')
  const store = tx.objectStore(STORE)
  const rows = await Promise.all(ids.map((id) => runRequest<StoredPhoto | undefined>(store.get(id))))
  for (const row of rows) {
    if (row) found.set(row.id, toLoaded(row))
  }
  return found
}

/**
 * 只留最近 limit 张，更早的删掉。返回被淘汰的 id，供调用方标记那些气泡。
 */
export async function prunePhotos(limit = STORED_PHOTO_LIMIT): Promise<string[]> {
  const db = await openDb()
  const tx = db.transaction(STORE, 'readwrite')
  const store = tx.objectStore(STORE)
  // 只读 key，不把 blob 拉进内存——淘汰不需要看图。
  const keys = await runRequest<IDBValidKey[]>(store.index('savedAt').getAllKeys())
  const removed: string[] = []
  if (keys.length > limit) {
    for (const key of keys.slice(0, keys.length - limit)) {
      store.delete(key)
      removed.push(String(key))
    }
  }
  await new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error || new Error('indexedDB prune failed'))
    tx.onabort = () => reject(tx.error || new Error('indexedDB prune aborted'))
  })
  return removed
}

export async function storedPhotoIds(): Promise<string[]> {
  const db = await openDb()
  const tx = db.transaction(STORE, 'readonly')
  const keys = await runRequest<IDBValidKey[]>(tx.objectStore(STORE).index('savedAt').getAllKeys())
  return keys.map((key) => String(key))
}

// 测试与诊断用。必须真的 close()：连接还开着时 indexedDB.deleteDatabase 会一直
// 阻塞，只把 promise 置空是不够的。生产代码不该需要手动关库。
export async function closePhotoStore() {
  const pending = dbPromise
  dbPromise = null
  if (!pending) return
  try {
    (await pending).close()
  } catch {
    // 本来就没开成，没什么要关的。
  }
}
