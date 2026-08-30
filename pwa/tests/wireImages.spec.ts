import { describe, expect, it } from 'vitest'
import { EXPIRED_IMAGE_MARKER, wireContent, wireMessages } from '../src/api/client'
import type { Attachment, UiMessage } from '../src/types'

function userWith(attachments: Attachment[], content = '看这个'): UiMessage {
  return {
    id: 'u1',
    role: 'user',
    content,
    echo: '',
    echoSegments: [],
    attachments,
    thinking: '',
    thinkingSegments: [],
    events: [],
  }
}

const live: Attachment = {
  id: 'img-live',
  name: 'p.jpg',
  mime: 'image/jpeg',
  fingerprint: 'a'.repeat(64),
  dataUrl: 'data:image/jpeg;base64,AAAA',
}

const expired: Attachment = {
  id: 'img-expired',
  name: 'old.jpg',
  mime: 'image/jpeg',
  fingerprint: 'b'.repeat(64),
}

describe('wireContent with local photo expiry', () => {
  it('sends real bytes while the photo is still on this device', () => {
    const blocks = wireContent(userWith([live])) as Array<Record<string, any>>
    expect(blocks[1]).toEqual({ type: 'image_url', image_url: { url: 'data:image/jpeg;base64,AAAA' } })
  })

  it('sends the fingerprint instead of bytes once the photo expired locally', () => {
    const blocks = wireContent(userWith([expired])) as Array<Record<string, any>>
    expect(blocks[1]).toEqual({
      type: 'image',
      source: { type: EXPIRED_IMAGE_MARKER, fingerprint: 'b'.repeat(64) },
    })
    // 关键点：过期块里没有任何图片字节。
    expect(JSON.stringify(blocks)).not.toContain('base64')
  })

  // 网关的两个图片块判别器都认这个形状是图片块，历史归一化会跳过它，所以
  // 「真图」和「指纹块」归一化后完全等价——分支检测看不见，prompt cache epoch
  // 不会被重置。写死这个形状：改了它就会静默打掉整个缓存 epoch。
  it('keeps the exact block shape the gateway recognises as an image block', () => {
    const blocks = wireContent(userWith([expired])) as Array<Record<string, any>>
    const block = blocks[1]
    expect(block.type).toBe('image')
    expect(block.source.type).toBe(EXPIRED_IMAGE_MARKER)
    // 刻意不叫 shenyu_history_image：那个标记的 fingerprint 是 JSON 块的哈希，
    // 不是图片字节的哈希，同名会把两件事混为一谈。
    expect(block.source.type).not.toBe('shenyu_history_image')
    expect(Object.keys(block).sort()).toEqual(['source', 'type'])
    expect(Object.keys(block.source).sort()).toEqual(['fingerprint', 'type'])
  })

  it('mixes live and expired photos in one message', () => {
    const blocks = wireContent(userWith([live, expired])) as Array<Record<string, any>>
    expect(blocks).toHaveLength(3)
    expect(blocks[0]).toEqual({ type: 'text', text: '看这个' })
    expect(blocks[1].type).toBe('image_url')
    expect(blocks[2].type).toBe('image')
  })

  it('drops an expired photo that has no fingerprint at all', () => {
    // 护栏之前存下的旧附件没有指纹，无从指认，只能不送。
    const legacy: Attachment = { id: 'img-old', name: 'x.jpg', mime: 'image/jpeg' }
    const blocks = wireContent(userWith([legacy])) as Array<Record<string, any>>
    expect(blocks).toEqual([{ type: 'text', text: '看这个' }])
  })

  it('never loses the text when every photo is gone and unidentifiable', () => {
    const legacy: Attachment = { id: 'img-old', name: 'x.jpg', mime: 'image/jpeg' }
    // 有文字时留一个 text block 就够——网关归一化后与纯字符串等价（已在
    // context_window 侧核对过），关键是这一轮的文字一个字都不能丢。
    expect(wireContent(userWith([legacy], '只剩文字了'))).toEqual([
      { type: 'text', text: '只剩文字了' },
    ])
  })

  it('falls back to a plain string when there is neither text nor an identifiable photo', () => {
    const legacy: Attachment = { id: 'img-old', name: 'x.jpg', mime: 'image/jpeg' }
    // 空 blocks 数组会被上游当成没有内容，退回字符串形态更安全。
    expect(wireContent(userWith([legacy], ''))).toBe('')
  })

  it('still sends an image-only message as blocks', () => {
    const blocks = wireContent(userWith([expired], '')) as Array<Record<string, any>>
    expect(blocks).toHaveLength(1)
    expect(blocks[0].type).toBe('image')
  })

  it('shrinks a ten-photo conversation once the older photos expire', () => {
    const rows: UiMessage[] = []
    for (let index = 0; index < 10; index++) {
      const big = 'A'.repeat(400_000)
      rows.push(userWith([{
        id: `img-${index}`,
        name: 'p.jpg',
        mime: 'image/jpeg',
        fingerprint: String(index).repeat(64).slice(0, 64),
        // 只有最后两条还留在本机。
        dataUrl: index >= 8 ? `data:image/jpeg;base64,${big}` : undefined,
      }], `第 ${index} 轮`))
    }
    const bytes = JSON.stringify(wireMessages(rows)).length
    // 全部带图时约 3.82MB（本轮实测）；只剩两张真图后应当远小于 1MB。
    expect(bytes).toBeLessThan(1_000_000)
    const wired = JSON.stringify(wireMessages(rows))
    expect(wired.split(EXPIRED_IMAGE_MARKER).length - 1).toBe(8)
  })
})

describe('process-local URLs must never go on the wire', () => {
  // 2026-08-30 线上 500：回填用了 createObjectURL，那个 blob: 地址被当真图上传，
  // 上游取不到 → illegal base64 data at input byte 0。回填现在走 data URL；
  // 这几条守的是「万一又出现进程内地址，也不能上线」。
  it('sends the fingerprint instead of a blob URL', () => {
    const blobbed: Attachment = {
      id: 'img-blob', name: 'p.jpg', mime: 'image/jpeg',
      fingerprint: 'c'.repeat(64), dataUrl: 'blob:https://host/9f8c-4d2a',
    }
    const blocks = wireContent(userWith([blobbed])) as Array<Record<string, any>>
    const serialized = JSON.stringify(blocks)
    expect(serialized).not.toContain('blob:')
    expect(blocks[1]).toEqual({
      type: 'image',
      source: { type: EXPIRED_IMAGE_MARKER, fingerprint: 'c'.repeat(64) },
    })
  })

  it('drops a blob URL with no fingerprint rather than sending it', () => {
    const blobbed: Attachment = { id: 'x', name: 'p.jpg', mime: 'image/jpeg', dataUrl: 'blob:null/abc' }
    expect(JSON.stringify(wireContent(userWith([blobbed])))).not.toContain('blob:')
  })

  it('still sends genuine data URLs', () => {
    const real: Attachment = {
      id: 'img-real', name: 'p.jpg', mime: 'image/jpeg',
      fingerprint: 'd'.repeat(64), dataUrl: 'data:image/jpeg;base64,AAAA',
    }
    const blocks = wireContent(userWith([real])) as Array<Record<string, any>>
    expect(blocks[1]).toEqual({ type: 'image_url', image_url: { url: 'data:image/jpeg;base64,AAAA' } })
  })
})
