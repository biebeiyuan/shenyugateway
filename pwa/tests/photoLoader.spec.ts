import 'fake-indexeddb/auto'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPhotoLoader } from '../src/session/photoLoader'
import { closePhotoStore, putPhoto, storedPhotoIds, prunePhotos } from '../src/session/photoStore'
import { wireMessages } from '../src/api/client'
import type { UiMessage } from '../src/types'

const event = { id:'user-event', event_at:'2026-09-19T00:00:00Z' }
const context = {gatewayUrl:'https://gateway.test',authToken:'private-token',sessionTag:'one'}
const album = {id:'local',name:'照片',mime:'image/jpeg',fingerprint:'a'.repeat(64),photo_id:'phot_one',title:'想留的',content:'原话'}
function msg(role:'user'|'assistant'='user'): UiMessage {
  return {id:'m',role,archiveEvent:event,replyVersionId:role==='assistant'?event.id:undefined,content:'',echo:'',echoSegments:[],thinking:'',thinkingSegments:[],events:[],attachments:[{id:'local',name:'照片',mime:'image/jpeg',fingerprint:'a'.repeat(64)}]}
}
function json(value: unknown) { return new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}}) }
function pixels() {return new Response(new Blob(['photo'],{type:'image/jpeg'}),{headers:{'Content-Type':'image/jpeg'}})}
beforeEach(async()=>{
  await closePhotoStore()
  await new Promise<void>(resolve=>{const r=indexedDB.deleteDatabase('shenyu_pwa_photos');r.onsuccess=()=>resolve()})
  vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:private-display')
  vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>{})
})
afterEach(()=>vi.restoreAllMocks())
it('does not request transcript persistence when stable photo references are unchanged',async()=>{
  const m=msg();m.attachments=[];const rows=[m]
  const onReferences=vi.fn()
  vi.stubGlobal('fetch',vi.fn(async()=>json({media:{},photos:{}})))
  const loader=createPhotoLoader(()=>context,()=>rows,onReferences)
  await loader.restore()
  expect(onReferences).not.toHaveBeenCalled()
  loader.dispose()
})
it('restores device bytes by fingerprint after a server handoff without uploading ordinary images',async()=>{
  const meta=await putPhoto('old-local-id',new Blob(['local'],{type:'image/jpeg'}),'image/jpeg')
  const m=msg(); m.attachments[0].fingerprint=meta.fingerprint
  const rows=[m]
  const fetcher=vi.fn(async()=>json({media:{},photos:{}}));vi.stubGlobal('fetch',fetcher)
  const loader=createPhotoLoader(()=>context,()=>rows)
  await loader.restore()
  expect(m.attachments[0].dataUrl).toMatch(/^data:image\/jpeg;base64,/)
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(fetcher.mock.calls[0][1]?.body).not.toContain('base64')
  loader.dispose()
})
it('resolves an evicted saved photo remotely without filling dataUrl or consuming cache slots',async()=>{
  for(let i=0;i<31;i++) await putPhoto(String(i),new Blob([String(i)]),'image/jpeg')
  await prunePhotos()
  const m=msg();const rows=[m]
  const fetcher=vi.fn(async(url:string, init?:RequestInit)=> url.endsWith('/resolve') ? json({media:{},photos:{['a'.repeat(64)]:album}}):pixels())
  vi.stubGlobal('fetch',fetcher)
  const loader=createPhotoLoader(()=>context,()=>rows)
  await loader.restore()
  expect(m.attachments[0]).toMatchObject({photoId:'phot_one',displayUrl:'blob:private-display'})
  expect(m.attachments[0].dataUrl).toBeUndefined()
  expect(JSON.stringify(wireMessages(rows))).not.toContain('blob:')
  expect(await storedPhotoIds()).toHaveLength(30)
  const imageCall=fetcher.mock.calls.find(([url])=>url.includes('/photo/'))!
  expect(imageCall[0]).not.toContain('private-token')
  expect(new Headers(imageCall[1]?.headers).get('Authorization')).toBe('Bearer private-token')
  loader.dispose()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:private-display')
})
it('keeps inflight reference recovery independent of incomplete-text recovery',async()=>{
  const m=msg('assistant');m.attachments=[];m.truncated=true
  const rows=[m]
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith('/resolve')?json({media:{['assistant:'+event.id]:[album]},photos:{}}):pixels()))
  const loader=createPhotoLoader(()=>context,()=>rows)
  await loader.restore()
  expect(m.attachments[0].photoId).toBe('phot_one')
  expect(m.truncated).toBe(true)
  expect(m.content).toBe('')
  loader.dispose()
})
it('does not declare a photo cleared just because the reference server is offline, and retry works',async()=>{
  const m=msg();const rows=[m]
  const fetcher=vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(json({media:{},photos:{['a'.repeat(64)]:album}})).mockResolvedValueOnce(pixels())
  vi.stubGlobal('fetch',fetcher)
  const loader=createPhotoLoader(()=>context,()=>rows)
  await loader.restore()
  expect(m.attachments[0].photoState).toBe('error')
  await loader.restore()
  expect(m.attachments[0].displayUrl).toBe('blob:private-display')
  loader.dispose()
})
it('marks an evicted unsaved photo cleared only after a successful resolution',async()=>{
  const m=msg();const rows=[m]
  vi.stubGlobal('fetch',vi.fn(async()=>json({media:{},photos:{}})))
  const loader=createPhotoLoader(()=>context,()=>rows)
  await loader.restore()
  expect(m.attachments[0].photoState).toBe('cleared')
  expect(URL.createObjectURL).not.toHaveBeenCalled()
  loader.dispose()
})
it('does not attach a late response to a different session or selected reply',async()=>{
  let release!:(response:Response)=>void
  const m=msg('assistant');m.attachments=[]; const rows=[m]
  let ctx={...context}
  vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{release=resolve})))
  const loader=createPhotoLoader(()=>ctx,()=>rows)
  const pending=loader.restore()
  await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
  m.archiveEvent={...event,id:'other-reply'};m.replyVersionId='other-reply'
  ctx={...context,sessionTag:'two'}
  release(json({media:{['assistant:'+event.id]:[album]},photos:{}}))
  await pending
  expect(m.attachments).toHaveLength(0)
  loader.dispose()
})

it('treats unreadable device storage as unknown, not proof of eviction',async()=>{
  const m=msg();const rows=[m]
  const idb=globalThis.indexedDB
  vi.stubGlobal('indexedDB',undefined)
  vi.stubGlobal('fetch',vi.fn(async()=>json({media:{},photos:{}})))
  const loader=createPhotoLoader(()=>context,()=>rows)
  try {
    await loader.restore()
    expect(m.attachments[0].photoState).toBe('error')
  } finally {loader.dispose();vi.stubGlobal('indexedDB',idb)}
})
