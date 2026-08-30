import 'fake-indexeddb/auto'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  STORED_PHOTO_LIMIT,
  getPhoto,
  getPhotos,
  photoFingerprint,
  prunePhotos,
  putPhoto,
  closePhotoStore,
  storedPhotoIds,
} from '../src/session/photoStore'

function blobOf(text: string): Blob {
  return new Blob([text], { type: 'image/jpeg' })
}

beforeEach(async () => {
  // 每个用例一个干净库。必须先 close 再 delete：连接开着时 deleteDatabase 会
  // 一直阻塞（第一版只把 promise 置空，六个用例全部超时）。
  await closePhotoStore()
  await new Promise<void>((resolve) => {
    const request = indexedDB.deleteDatabase('shenyu_pwa_photos')
    request.onsuccess = () => resolve()
    request.onerror = () => resolve()
    request.onblocked = () => resolve()
  })
})

describe('photoStore', () => {
  it('stores the bytes and returns them intact', async () => {
    const blob = blobOf('这是一张图的字节')
    const meta = await putPhoto('img-1', blob, 'image/jpeg')

    expect(meta.byteSize).toBe(blob.size)
    expect(meta.fingerprint).toHaveLength(64)

    const stored = await getPhoto('img-1')
    expect(stored).toBeDefined()
    expect(await stored!.blob.text()).toBe('这是一张图的字节')
  })

  // 指纹必须与网关侧 store/_album.py::photo_fingerprint 是同一个算法，
  // 否则过期后网关认不出这张图是相册里的哪一张。
  it('fingerprints bytes with sha256, stably and distinctly', async () => {
    const same1 = await photoFingerprint(blobOf('一样的字节'))
    const same2 = await photoFingerprint(blobOf('一样的字节'))
    const other = await photoFingerprint(blobOf('不一样的字节'))

    expect(same1).toBe(same2)
    expect(same1).not.toBe(other)
    expect(same1).toMatch(/^[0-9a-f]{64}$/)
  })

  it('matches the known sha256 of a fixed input', async () => {
    // echo -n "abc" | sha256sum
    const digest = await photoFingerprint(new Blob(['abc']))
    expect(digest).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  })

  it('keeps only the newest photos and reports which ones went', async () => {
    for (let index = 0; index < STORED_PHOTO_LIMIT + 5; index++) {
      await putPhoto(`img-${index}`, blobOf(`bytes ${index}`), 'image/jpeg')
    }

    const removed = await prunePhotos()

    expect(removed).toHaveLength(5)
    // 淘汰的是最早的五张。
    expect(removed).toEqual(['img-0', 'img-1', 'img-2', 'img-3', 'img-4'])
    const left = await storedPhotoIds()
    expect(left).toHaveLength(STORED_PHOTO_LIMIT)
    expect(await getPhoto('img-0')).toBeUndefined()
    expect(await getPhoto(`img-${STORED_PHOTO_LIMIT + 4}`)).toBeDefined()
  })

  it('does nothing when the store is under the limit', async () => {
    await putPhoto('img-a', blobOf('a'), 'image/jpeg')
    expect(await prunePhotos()).toEqual([])
    expect(await storedPhotoIds()).toEqual(['img-a'])
  })

  it('respects an explicit smaller limit', async () => {
    for (let index = 0; index < 6; index++) {
      await putPhoto(`img-${index}`, blobOf(`b${index}`), 'image/jpeg')
    }
    expect(await prunePhotos(2)).toHaveLength(4)
    expect(await storedPhotoIds()).toHaveLength(2)
  })

  it('fetches a batch and simply omits the ones that expired', async () => {
    await putPhoto('img-here', blobOf('still here'), 'image/jpeg')

    const found = await getPhotos(['img-here', 'img-gone'])

    expect([...found.keys()]).toEqual(['img-here'])
    expect(await getPhotos([])).toEqual(new Map())
  })
})
