import 'fake-indexeddb/auto'
import { beforeEach, describe, expect, it } from 'vitest'
import { wireContent, EXPIRED_IMAGE_MARKER } from '../src/api/client'
import {
  FALLBACK_SESSION_MESSAGE_LIMIT,
  loadStoredMessages,
  persistStoredMessages,
} from '../src/session/persistence'
import {
  STORED_PHOTO_LIMIT,
  closePhotoStore,
  getPhotos,
  photoDataUrl,
  prunePhotos,
  putPhoto,
} from '../src/session/photoStore'
import type { UiMessage } from '../src/types'

// 三个模块合起来才是「本机最近 30 张」这件事：photoStore 管字节和淘汰，
// persistence 管元数据跨刷新，client 管过期后送什么。分开测各自都绿，
// 接起来仍可能漏——所以这里走一遍完整生命周期。

beforeEach(async () => {
  await closePhotoStore()
  localStorage.clear()
  await new Promise<void>((resolve) => {
    const request = indexedDB.deleteDatabase('shenyu_pwa_photos')
    request.onsuccess = () => resolve()
    request.onerror = () => resolve()
    request.onblocked = () => resolve()
  })
})

describe('local photo lifecycle', () => {
  it('keeps the newest 30 across a refresh and uploads fingerprints for the rest', async () => {
    const overflow = 5
    const total = STORED_PHOTO_LIMIT + overflow
    const messages: UiMessage[] = []
    for (let index = 0; index < total; index++) {
      const meta = await putPhoto(
        `img-${index}`,
        new Blob([`bytes-${index}`], { type: 'image/jpeg' }),
        'image/jpeg',
      )
      messages.push({
        id: `u${index}`,
        role: 'user',
        content: `第 ${index} 轮`,
        echo: '',
        echoSegments: [],
        attachments: [{
          id: `img-${index}`,
          name: 'p.jpg',
          mime: 'image/jpeg',
          fingerprint: meta.fingerprint,
          dataUrl: 'data:image/jpeg;base64,AAAA',
        }],
        thinking: '',
        thinkingSegments: [],
        events: [],
      })
    }

    expect(await prunePhotos()).toHaveLength(overflow)

    // 刷新：元数据从 localStorage 回来，dataUrl 一律为空。
    persistStoredMessages(messages, FALLBACK_SESSION_MESSAGE_LIMIT)
    const restored = loadStoredMessages()
    expect(restored).toHaveLength(total)
    expect(restored.every((message) => !message.attachments[0].dataUrl)).toBe(true)

    // 启动回填：本机还留着的接回去（App.vue::restoreLocalPhotos 的等价流程）。
    const wanted = restored.flatMap((message) =>
      message.attachments.filter((attachment) => !attachment.dataUrl).map((attachment) => attachment.id))
    const found = await getPhotos(wanted)
    for (const message of restored) {
      for (const attachment of message.attachments) {
        const stored = found.get(attachment.id)
        // 与 App.vue::restoreLocalPhotos 一致：回填 data URL，不是 blob: 地址。
        if (stored) attachment.dataUrl = photoDataUrl(stored)
      }
    }

    const withPhoto = restored.filter((message) => message.attachments[0].dataUrl)
    const expired = restored.filter((message) => !message.attachments[0].dataUrl)
    expect(withPhoto).toHaveLength(STORED_PHOTO_LIMIT)
    expect(expired).toHaveLength(overflow)
    // 淘汰的是最早的那几张。
    expect(expired.map((message) => message.id)).toEqual(['u0', 'u1', 'u2', 'u3', 'u4'])

    const oldest = JSON.stringify(wireContent(restored[0]))
    expect(oldest).toContain(EXPIRED_IMAGE_MARKER)
    expect(oldest).not.toContain('base64')
    // 过期只影响图，这一轮说过的话一个字都不能少。
    expect(oldest).toContain('第 0 轮')

    const newest = JSON.stringify(wireContent(restored[total - 1]))
    // 回填后仍是能上线的 data URL —— blob: 地址上游取不到（线上 500）。
    expect(newest).toContain('data:image/jpeg;base64,')
    expect(newest).not.toContain('blob:')
    expect(newest).not.toContain(EXPIRED_IMAGE_MARKER)
  })
})
