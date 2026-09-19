import { expect, test, type Page } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || 18110}`
const TOKEN = process.env.E2E_GATEWAY_TOKEN || 'shenyu-e2e-smoke'
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAPAAAACgAQMAAAAIFXMmAAAABlBMVEW0yNwAAACR202XAAAAHElEQVR42u3BMQEAAADCoPVPbQdvoAAAAACA1wATYAAB+o0sSQAAAABJRU5ErkJggg=='
const EVENT_AT = '2026-09-19T00:00:00Z'
const reference = (id = 'call-old', photo_id = 'phot_one') => ({id, photo_id, title:'想留的', content:'以前写下的话', name:'想留的', mime:'image/png'})
const userMedia = [
  {id:'local-saved',name:'保存过的照片',mime:'image/png',fingerprint:'a'.repeat(64)},
  {id:'local-cleared',name:'普通照片',mime:'image/png',fingerprint:'b'.repeat(64)},
]

async function setup(page:Page, failImages=false) {
  const errors:string[]=[]
  page.on('pageerror', error=>errors.push(error.message))
  const requests:any[]=[]
  const imageRequests:string[]=[]
  const shares:Record<string,any[]>= {'r-old':[reference()]}
  let rows:any[]=[
    {role:'user',content:'这两张照片',archive_event:{id:'u-old',event_at:EVENT_AT},media:userMedia},
    {role:'assistant',content:'这一张我留着了。',archive_event:{id:'r-old',event_at:EVENT_AT},media:[reference()]},
  ]
  const seed=rows.map((m,index)=>({id:`seed-${index}`,role:m.role,content:m.content,echo:'',echoSegments:[],thinking:'',thinkingSegments:[],events:[],attachments: index===0 ? userMedia : [],archiveEvent:m.archive_event,replyVersionId:index===1?'r-old':undefined}))
  await page.context().addCookies([{name:'shenyu_token',value:TOKEN,url:new URL(BASE).origin,sameSite:'Lax'}])
  await page.addInitScript(({seed,token})=>{
    if (localStorage.getItem('album-e2e-seeded')) return
    localStorage.setItem('album-e2e-seeded','true')
    localStorage.setItem('shenyu_token',token)
    localStorage.setItem('shenyu_pwa_session','one')
    localStorage.setItem('shenyu_pwa_messages',JSON.stringify(seed))
    localStorage.setItem('shenyu_pwa_model','test-model')
  },{seed,token:TOKEN})
  await page.route('**/api/gateway/weather',r=>r.fulfill({json:{available:false}}))
  await page.route('**/api/config',r=>r.fulfill({json:{max_client_messages:75,upstream_model:'test-model'}}))
  await page.route('**/api/upstream-presets',r=>r.fulfill({json:{presets:[]}}))
  await page.route('**/v1/models',r=>r.fulfill({json:{data:[{id:'test-model'}]}}))
  await page.route('**/api/gateway/sessions**',r=>{
    const path=new URL(r.request().url()).pathname
    if(path.endsWith('/reply-recovery')) return r.fulfill({json:{replies:[]}})
    if(path.endsWith('/sessions')) return r.fulfill({json:{sessions:[{session_tag:'one',display_name:'照片那页',message_count:4},{session_tag:'two',display_name:'另一页',message_count:2}]}})
    return r.fulfill({json:{context_snapshots:[{messages:path.endsWith('/one')?rows:[{role:'user',content:'另一个会话',archive_event:{id:'u-two',event_at:EVENT_AT}}]}],recent_messages:[]}})
  })
  await page.route('**/api/gateway/album/resolve',r=>{
    const body=r.request().postDataJSON()
    const media:Record<string,unknown>={}
    if(body.session_tag==='one') for(const e of body.events) {
      if(e.role==='assistant' && shares[e.event_id]) media[`assistant:${e.event_id}`]=shares[e.event_id]
      if(e.role==='user' && e.event_id==='u-old') media['user:u-old']=userMedia
    }
    return r.fulfill({json:{media,photos:{['a'.repeat(64)]:reference()}}})
  })
  await page.route('**/api/gateway/album/photo/*',r=>{
    imageRequests.push(r.request().url())
    expect(r.request().headers().authorization).toBe(`Bearer ${TOKEN}`)
    return failImages ? r.fulfill({status:503,body:'unavailable'}) : r.fulfill({contentType:'image/png',body:Buffer.from(PNG,'base64')})
  })
  await page.route('**/v1/chat/completions',r=>{
    const body=r.request().postDataJSON();requests.push(body)
    expect(r.request().headers()['x-shenyu-album-photos']).toBe('true')
    const id=body.metadata.reply_version_id
    const item=reference(`call-${id}`,requests.length===1?'phot_one':'phot_two')
    shares[id]=[item]
    rows=[...body.messages,{role:'assistant',content:'给你这张。',archive_event:body.metadata.reply_archive_event,media:[item]}]
    const event={phase:'tool_end',name:'shenyu_gateway_tool',target_tool:'shenyu_album_send',tool_call_id:item.id,reply_version_id:id,ok:true,photo:item}
    return r.fulfill({contentType:'text/event-stream',body:
      `event: shenyu_tool\ndata: ${JSON.stringify({type:'shenyu.tool_event',event})}\n\n`+
      `data: ${JSON.stringify({choices:[{delta:{content:'给你这张。'}}]})}\n\ndata: [DONE]\n\n`})
  })
  return {requests,imageRequests,errors,allowImages:()=>{failImages=false}}
}

for (const width of [390,1280]) test(`PWA album references survive send, reload, roll and session handoff (${width})`,async({page},info)=>{
  await page.setViewportSize({width,height:844})
  const state=await setup(page)
  await page.goto(`${BASE}/chat/`)
  await expect(page.locator('.message-images img')).toHaveCount(2)
  await expect(page.getByText('本机图片已清理',{exact:true})).toBeVisible()
  await expect.poll(()=>page.locator('.message-images img').evaluateAll(images=>images.every(i=>(i as HTMLImageElement).naturalWidth>0))).toBe(true)
  const shared=page.locator('.message-row.assistant .message-images img').last()
  await expect(shared).toHaveAttribute('data-photo-id','phot_one')
  await shared.click()
  await expect(page.locator('.photo-viewer')).toBeVisible()
  await page.locator('.photo-viewer button').first().click()
  await page.locator('textarea').first().fill('再发一次')
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await expect(page.locator('.message-row.assistant .message-images img')).toHaveCount(2)
  expect(JSON.stringify(state.requests[0].messages)).not.toMatch(/base64|blob:/)
  await page.reload()
  await expect(page.locator('.message-row.assistant .message-images img')).toHaveCount(2)
  await page.getByRole('button',{name:'重新生成',exact:true}).last().click()
  await expect(shared).toHaveAttribute('data-photo-id','phot_two')
  await page.getByRole('button',{name:'上一版回答',exact:true}).last().click()
  await expect(shared).toHaveAttribute('data-photo-id','phot_one')
  await page.getByRole('button',{name:'下一版回答',exact:true}).last().click()
  await expect(shared).toHaveAttribute('data-photo-id','phot_two')
  await page.getByRole('button',{name:'打开菜单',exact:true}).click()
  await page.locator('.session-item').filter({hasText:'另一页'}).click()
  await expect(page.locator('.message-images img')).toHaveCount(0)
  await page.getByRole('button',{name:'打开菜单',exact:true}).click()
  await page.locator('.session-item').filter({hasText:'照片那页'}).click()
  await expect(page.locator('.message-row.assistant .message-images img')).toHaveCount(2)
  await expect(shared).toHaveAttribute('data-photo-id','phot_two')
  expect(state.imageRequests.every(url=>!url.includes(TOKEN))).toBe(true)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  expect(state.errors).toEqual([])
  // Capture the completed handoff, not the sidebar's closing transition or
  // the top of the conversation while its restored images are still loading.
  await expect(page.locator('.sidebar')).not.toHaveClass(/sidebar-open/)
  await expect.poll(()=>shared.evaluate(image=>(image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  await shared.scrollIntoViewIfNeeded()
  await page.screenshot({path:info.outputPath(`album-${width}.png`),animations:'disabled'})
})

test('PWA distinguishes a temporary photo load error and retries',async({page})=>{
  const state=await setup(page,true)
  await page.goto(`${BASE}/chat/`)
  const retry=page.locator('.message-row.assistant .message-image-retry')
  await expect(retry).toBeVisible()
  state.allowImages()
  await retry.click()
  await expect(page.locator('.message-row.assistant .message-images img')).toHaveCount(1)
  expect(state.errors).toEqual([])
})
