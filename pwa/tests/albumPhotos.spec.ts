import { createApp, h, nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import ChatMessageRow from '../src/components/ChatMessageRow.vue'
import type { UiMessage } from '../src/types'

function message(extra: Partial<UiMessage> = {}): UiMessage {
  return {id:'m',role:'assistant',content:'给你看',echo:'',echoSegments:[],thinking:'',thinkingSegments:[],events:[],attachments:[{id:'call',photoId:'phot_one',name:'想留的',mime:'image/jpeg',displayUrl:'blob:saved'}],...extra}
}
function mount(m:UiMessage, onOpenPhoto=vi.fn(), onRetryPhoto=vi.fn()) {
  const host=document.createElement('div')
  const app=createApp({render:()=>h(ChatMessageRow,{message:m,metaLabel:'',onOpenPhoto,onRetryPhoto})})
  app.mount(host)
  return {host,app,onOpenPhoto,onRetryPhoto}
}
describe('reference-backed photo bubbles',()=>{
  it('shows Shenyu shared pictures as normal clickable pictures',async()=>{
    const {host,app,onOpenPhoto}=mount(message())
    const img=host.querySelector('.message-images img') as HTMLImageElement
    expect(img).not.toBeNull()
    expect(img.getAttribute('src')).toBe('blob:saved')
    img.click();await nextTick()
    expect(onOpenPhoto).toHaveBeenCalledWith(0)
    expect(host.textContent).toContain('给你看')
    app.unmount()
  })
  it('shows saved original user pictures after cache eviction without calling them expired',()=>{
    const {host,app}=mount(message({role:'user'}))
    expect(host.querySelector('.message-images img')).not.toBeNull()
    expect(host.textContent).not.toContain('过期')
    app.unmount()
  })
  it('distinguishes local eviction from temporary failure and supports retry',async()=>{
    const m=message({role:'user',attachments:[
      {id:'old',name:'old',mime:'image/jpeg',photoState:'cleared'},
      {id:'saved',name:'saved',mime:'image/jpeg',photoId:'phot_one',photoState:'error'},
    ]})
    const {host,app,onRetryPhoto}=mount(m)
    expect(host.textContent).toContain('本机图片已清理')
    expect(host.textContent).toContain('暂时加载不了')
    const retry=host.querySelector('.message-image-retry') as HTMLButtonElement
    expect(retry).not.toBeNull()
    retry.click();await nextTick()
    expect(onRetryPhoto).toHaveBeenCalledWith('saved')
    app.unmount()
  })
  it('never labels a not-yet-loaded album ref as locally deleted',()=>{
    const m=message();delete m.attachments[0].displayUrl
    const {host,app}=mount(m)
    expect(host.textContent).toContain('加载')
    expect(host.textContent).not.toContain('已清理')
    app.unmount()
  })
})
