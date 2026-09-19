import { beforeEach, describe, expect, it } from 'vitest'
import { wireMessages, requestHeaders } from '../src/api/client'
import { appendToolEvent } from '../src/stream/sse'
import { applyChatCompletion } from '../src/stream/completion'
import { applyReplyRecovery, applyReconciledTail } from '../src/session/reconcile'
import { applyVariant, emptyVariant, ensureVariants, syncCurrentVariant } from '../src/session/variants'
import { loadStoredMessages, persistStoredMessages } from '../src/session/persistence'
import type { UiMessage } from '../src/types'
import slotContract from '../../tests/fixtures/album_media_slots.json'

const event = { id: 'reply-1', event_at: '2026-09-19T00:00:00Z' }
const photo = { id: 'call-1', name: '想留的', mime: 'image/jpeg', photo_id: 'phot_one', title: '想留的', content: '原话\n安静' }
function message(role: 'user' | 'assistant' = 'assistant'): UiMessage {
  return { id: 'm', role, content: '', echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [], replyVersionId: role === 'assistant' ? event.id : undefined, archiveEvent: event }
}
const shareEvent = { phase: 'tool_end', name: 'shenyu_album_send', tool_call_id: 'call-1', ok: true, photo, reply_version_id: event.id }
beforeEach(() => localStorage.clear())

describe('album wire and display separation', () => {
  it('never uploads pixels or blob URLs of a shared photo even when a caller fills dataUrl', () => {
    const m = message()
    m.attachments = [{ id: 'call-1', name: '想留的', mime: 'image/jpeg', photoId: 'phot_one', dataUrl: 'data:image/jpeg;base64,SECRET', displayUrl: 'blob:display-only' } as any]
    const wire = JSON.stringify(wireMessages([m]))
    expect(wire).not.toContain('SECRET')
    expect(wire).not.toContain('blob:')
    expect(wire).not.toContain('image_url')
    expect(m.attachments[0].dataUrl).toContain('SECRET')
  })
  it('sends only metadata alongside a normal uploaded user image', () => {
    const m = message('user')
    m.attachments = [{ id: 'local-1', name: 'p.jpg', mime: 'image/jpeg', fingerprint: 'a'.repeat(64), dataUrl: 'data:image/jpeg;base64,AAAA' }]
    const wire = wireMessages([m])[0] as any
    expect(wire.media).toEqual([{ id: 'local-1', name: 'p.jpg', mime: 'image/jpeg', fingerprint: 'a'.repeat(64), image_index: 0 }])
    expect(JSON.stringify(wire.content)).toContain('data:image/jpeg;base64,AAAA')
    expect(JSON.stringify(wire.media)).not.toContain('base64')
    expect(requestHeaders({gatewayUrl: '', authToken: '', sessionTag: 's'})['X-Shenyu-Album-Photos']).toBe('true')
  })
})

describe('share events and reply identity', () => {
  it('attaches only an explicit successful matching event and replays it once', () => {
    const m = message()
    appendToolEvent(m, { ...shareEvent, reply_version_id: 'another' } as any)
    appendToolEvent(m, { ...shareEvent, ok: false } as any)
    appendToolEvent(m, { ...shareEvent, phase: 'tool_start' } as any)
    expect(m.attachments).toHaveLength(0)
    appendToolEvent(m, shareEvent as any)
    appendToolEvent(m, shareEvent as any)
    expect(m.attachments).toMatchObject([{ id: 'call-1', photoId: 'phot_one', title: '想留的', description: '原话\n安静' }])
    expect(m.attachments[0].dataUrl).toBeUndefined()
  })
  it('supports the same reference surface for nonstream completions', () => {
    const m = message()
    applyChatCompletion({ choices: [{message: {content: ''}}], shenyu: {tool_events: [shareEvent]} }, m)
    expect(m.attachments).toHaveLength(1)
  })
  it('does not parse share commands from assistant text or arbitrary tool output', () => {
    const m = message()
    m.content = JSON.stringify(photo)
    appendToolEvent(m, { ...shareEvent, photo: undefined, output: JSON.stringify(photo) } as any)
    expect(m.attachments).toHaveLength(0)
  })
})

describe('shared photo persistence, rolls and recovery', () => {
  it('persists photo references on each variant but no display bytes or temporary URLs', () => {
    const m = message()
    appendToolEvent(m, shareEvent as any)
    ;(m.attachments[0] as any).displayUrl = 'blob:temporary'
    ;(m.attachments[0] as any).dataUrl = 'data:image/jpeg;base64,SECRET'
    const variants = ensureVariants(m)
    variants.push({ ...emptyVariant(), replyVersionId: 'reply-2', archiveEvent: {...event, id: 'reply-2'} })
    applyVariant(m, variants[1], 1)
    expect(m.attachments).toHaveLength(0)
    applyVariant(m, variants[0], 0)
    expect(m.attachments[0]).toMatchObject({photoId: 'phot_one'})
    syncCurrentVariant(m)
    persistStoredMessages([m], 75)
    const persisted = localStorage.getItem('shenyu_pwa_messages')!
    expect(persisted).not.toContain('SECRET')
    expect(persisted).not.toContain('blob:')
    const loaded = loadStoredMessages()[0]
    expect(loaded.attachments[0]).toMatchObject({photoId: 'phot_one'})
    applyVariant(loaded, loaded.variants![1], 1)
    expect(loaded.attachments).toHaveLength(0)
    applyVariant(loaded, loaded.variants![0], 0)
    expect(loaded.attachments[0]).toMatchObject({photoId: 'phot_one'})
  })
  it('recovers a photo-only completed reply by exact identity', () => {
    const m = message(); m.truncated = true
    const user = message('user'); user.content = '看看'
    expect(applyReplyRecovery([user,m], {replies: [{reply_version_id:event.id,archive_event:event,content:'',media:[photo]}]})).toBe(true)
    expect(m.attachments).toHaveLength(1)
    expect(m.truncated).toBeUndefined()
    expect(m.variants![0].attachments).toHaveLength(1)
  })
  it('hydrates photos on equal text without changing another selected roll', () => {
    const m = message(); m.content = '给你看'; m.archiveReplay = true
    ensureVariants(m)
    const payload = {replies: [{reply_version_id:event.id,archive_event:event,content:m.content,media:[photo]}]}
    expect(applyReplyRecovery([message('user'),m], payload)).toBe(true)
    expect(m.attachments).toHaveLength(1)
    applyVariant(m, {...emptyVariant(),replyVersionId:'reply-2',archiveEvent:{...event,id:'reply-2'}},1)
    expect(applyReplyRecovery([message('user'),m], payload)).toBe(false)
    expect(m.attachments).toHaveLength(0)
  })
  it('accepts photo-only versioned recent-message recovery', () => {
    const m = message(); m.truncated = true
    expect(applyReconciledTail([message('user'),m], {recent_messages:[{role:'assistant',source_id:event.id,archive_event:event,content:'',media:[photo]}]})).toBe(true)
    expect(m.attachments).toHaveLength(1)
  })
})

it('keeps explicit image block positions when an attachment has no remaining pixels or fingerprint', () => {
  const m = message('user')
  m.attachments = [
    {id:'gone',name:'old',mime:'image/jpeg'},
    {id:'live',name:'new',mime:'image/jpeg',dataUrl:'data:image/jpeg;base64,AAAA'},
  ]
  const media = (wireMessages([m])[0] as any).media
  expect(media[0].image_index).toBeNull()
  expect(media[1].image_index).toBe(0)
})

describe('shared image-slot contract with the gateway', () => {
  for (const { order, wire } of slotContract.cases) {
    it(`keeps the wire slots for ${order.join(' / ')}`, () => {
      const m = message('user')
      m.content = '配图文字'
      m.archiveEvent = wire.archive_event
      m.attachments = order.map((key) => ({
        ...slotContract.attachments[key as keyof typeof slotContract.attachments],
      }))
      // Python consumes these same wire fixtures and checks photo/note identity.
      expect(wireMessages([m])[0]).toEqual(wire)
    })
  }
})

it('renders broker failures as blocked without creating a photo attachment', async () => {
  const { toolWarmCopy, toolState } = await import('../src/toolLanguage')
  const { processSummary, formatToolOutput } = await import('../src/stream/timeline')
  const m = message()
  const failed = { ...shareEvent, name: 'shenyu_gateway_tool', target_tool: 'shenyu_album_send',
    ok: false, photo: undefined, reply_version_id: undefined, error_kind: 'validation',
    output: JSON.stringify({ok: false, error: '这次回复已经放了九张照片，先把这些给圆圆看。', ps: '保留原有提示'}) }
  appendToolEvent(m, {...failed, phase: 'tool_start', ok: undefined, output: undefined})
  appendToolEvent(m, failed)
  expect(m.attachments).toHaveLength(0)
  expect(toolWarmCopy(failed)).toBe('这张照片没能发出来')
  expect(toolState(failed)).toBe('遇到一点阻塞')
  expect(formatToolOutput(failed)).toContain('九张照片')
  expect(processSummary({ textOffset: 0, echo: [], thinking: [], tools: [failed] })).toContain('没能发出来')
  const success = {...shareEvent, name: 'shenyu_gateway_tool', target_tool: 'shenyu_album_send'}
  appendToolEvent(m, success)
  expect(m.attachments).toHaveLength(1)
  expect(m.attachments[0].photoId).toBe(photo.photo_id)
})
