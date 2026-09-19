import { expect, test, type Page } from '@playwright/test'

const TOKEN = process.env.E2E_GATEWAY_TOKEN || 'shenyu-e2e-smoke'
const AT = '2026-09-19T01:00:00Z'
function message(role: 'user' | 'assistant', id: string, content: string) {
  return { role, id, content, echo: '', echoSegments: [], thinking: '', thinkingSegments: [], attachments: [], events: [],
    archiveEvent: { id, event_at: AT }, ...(role === 'assistant' ? { replyVersionId: id } : {}) }
}
async function saved(page: Page) {
  return page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('shenyu-pwa-transcripts-v1', 1)
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error)
    })
    try {
      const tx = db.transaction(['sessions', 'messages'], 'readonly')
      const get = <T>(request: IDBRequest<T>) => new Promise<T>((resolve, reject) => {
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error)
      })
      return { sessions: await get(tx.objectStore('sessions').getAll()),
        rows: await get(tx.objectStore('messages').getAll()) }
    } finally { db.close() }
  })
}
async function fixtures(page: Page) {
  const hidden = new Set<string>()
  const mutations: unknown[] = []
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.context().addCookies([{ name: 'shenyu_token', value: TOKEN, domain: '127.0.0.1', path: '/' }])
  await page.addInitScript(({ token, seed }) => {
    localStorage.setItem('shenyu_pwa_gateway_token', token)
    if (!localStorage.getItem('retention-fixture-installed')) {
      localStorage.setItem('shenyu_pwa_session', 'A')
      localStorage.setItem('shenyu_pwa_messages', JSON.stringify(seed))
      localStorage.setItem('retention-fixture-installed', 'true')
    }
  }, { token: TOKEN, seed: [message('user', 'u-A', 'question A'), {
    ...message('assistant', 'r-A', 'reply A'), thinking: 'local thought stays',
    events: [{ phase: 'tool_end', name: 'shenyu_recall', tool_call_id: 'call-A', ok: true, output: 'local result stays' }],
  }] })
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/gateway/sessions') {
      const filter = url.searchParams.get('visibility')
      return route.fulfill({ json: { sessions: ['A', 'B'].filter(tag => filter === 'hidden' ? hidden.has(tag) : !hidden.has(tag))
        .map(tag => ({ session_tag: tag, display_name: `conversation ${tag}`, hidden_at: hidden.has(tag) ? AT : null })) } })
    }
    if (url.pathname.endsWith('/visibility')) {
      const tag = url.pathname.split('/')[4]
      const body = route.request().postDataJSON()
      mutations.push({ method: route.request().method(), path: url.pathname, ...body })
      if (body.hidden) hidden.add(tag); else hidden.delete(tag)
      return route.fulfill({ json: { ok: true } })
    }
    if (route.request().method() === 'DELETE') throw new Error('A browser list action attempted destructive deletion')
    if (url.pathname.endsWith('/reply-recovery')) return route.fulfill({ json: { replies: [] } })
    if (url.pathname.includes('/sessions/')) {
      const tag = url.pathname.split('/')[4]
      return route.fulfill({ json: { context_snapshots: [{ messages: [message('user', `u-${tag}`, `question ${tag}`),
        message('assistant', `r-${tag}`, `reply ${tag}`)].map(row => ({ role: row.role, content: row.content, archive_event: row.archiveEvent })) }], recent_messages: [] } })
    }
    if (url.pathname.endsWith('/album/resolve')) return route.fulfill({ json: { media: {}, photos: {} } })
    return route.fulfill({ json: {} })
  })
  await page.route('**/v1/models', route => route.fulfill({ json: { data: [{ id: 'isolated-test' }] } }))
  return { errors, mutations }
}

test('PWA preserves process records and draft through session switching, reload, and hide/restore', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const fixture = await fixtures(page)
  await page.goto('/chat/')
  await expect(page.locator('textarea')).toBeEnabled()
  await page.locator('textarea').fill('draft for A')
  await expect.poll(async () => (await saved(page)).sessions.some(row => row.draft === 'draft for A')).toBe(true)
  await page.getByRole('button', { name: '打开菜单', exact: true }).click()
  await page.locator('.session-item').filter({ hasText: 'conversation B' }).click()
  await expect(page.locator('.message-stream')).toContainText('reply B')
  await page.getByRole('button', { name: '打开菜单', exact: true }).click()
  await page.locator('.session-item').filter({ hasText: 'conversation A' }).click()
  await expect(page.locator('textarea')).toHaveValue('draft for A')
  await page.reload()
  await expect(page.locator('textarea')).toHaveValue('draft for A')
  const record = (await saved(page)).rows.map(row => JSON.parse(row.json)).find(row => row.replyVersionId === 'r-A')
  expect(record.thinking).toBe('local thought stays')
  expect(record.events[0].output).toBe('local result stays')
  await page.getByRole('button', { name: '打开菜单', exact: true }).click()
  await page.locator('.session-item').filter({ hasText: 'conversation A' }).click({ button: 'right' })
  await page.getByRole('button', { name: '收起对话', exact: true }).click()
  await page.getByRole('button', { name: '查看已收起', exact: true }).click()
  await expect(page.locator('.session-item').filter({ hasText: 'conversation A' })).toHaveCount(1)
  await page.locator('.session-item').filter({ hasText: 'conversation A' }).click({ button: 'right' })
  await page.getByRole('button', { name: '放回最近对话', exact: true }).click()
  await expect(page.locator('.session-item')).toHaveCount(0)
  await expect(page.locator('.sidebar-empty')).toContainText('还没有已收起的对话')
  expect(fixture.mutations).toHaveLength(2)
  expect((await saved(page)).rows.some(row => JSON.parse(row.json).thinking === 'local thought stays')).toBe(true)
  expect(fixture.errors).toEqual([])
  await page.screenshot({ path: info.outputPath('retention-mobile.png'), animations: 'disabled' })
})

test('PWA commits send identity before POST and keeps tool output after reload', async ({ page }) => {
  const fixture = await fixtures(page)
  let checked = false
  await page.route('**/v1/chat/completions', async route => {
    const body = route.request().postDataJSON()
    const record = (await saved(page)).rows.map(row => JSON.parse(row.json))
      .find(row => row.replyVersionId === body.metadata.reply_version_id)
    expect(record?.truncated).toBeUndefined()
    expect(record?.archiveEvent.id).toBe(body.metadata.reply_version_id)
    checked = true
    const call = { name: 'shenyu_recall', tool_call_id: 'live-call' }
    const frames = [{ ...call, phase: 'tool_start', input: { query: 'hello' } },
      { ...call, phase: 'tool_end', ok: true, output: 'live retained result' }]
      .map(event => `event: shenyu_tool\ndata: ${JSON.stringify({ type: 'shenyu.tool_event', event })}\n\n`).join('')
    await route.fulfill({ contentType: 'text/event-stream', body: frames +
      'data: {"choices":[{"delta":{"reasoning_content":"retained thought","content":"new reply complete"}}]}\n\ndata: [DONE]\n\n' })
  })
  await page.goto('/chat/')
  await page.locator('textarea').fill('new question')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.message-stream')).toContainText('new reply complete')
  await expect(page.getByRole('button', { name: '停止生成', exact: true })).toHaveCount(0)
  expect(checked).toBe(true)
  await page.reload()
  await expect(page.locator('.message-stream')).toContainText('new reply complete')
  const final = (await saved(page)).rows.map(row => JSON.parse(row.json)).find(row => row.content === 'new reply complete')
  expect(final.thinking).toBe('retained thought')
  expect(final.events.find((event: any) => event.phase === 'tool_end').output).toBe('live retained result')
  await page.locator('.message-row.assistant').last().locator('.process-strip').first().click()
  await page.locator('.process-timeline-item').filter({ hasText: /recall/i }).first().click()
  await expect(page.locator('.process-code').last()).toContainText('live retained result')
  expect(fixture.errors).toEqual([])
})

test('installed PWA opens a query URL offline without losing its draft or forcing a takeover reload', async ({ page, context }) => {
  const fixture = await fixtures(page)
  await page.goto('/chat/')
  await page.evaluate(async () => { await navigator.serviceWorker.ready })
  await page.reload()
  await page.locator('textarea').fill('offline draft survives')
  await expect.poll(async () => (await saved(page)).sessions.some(row => row.draft === 'offline draft survives')).toBe(true)
  await page.evaluate(() => {
    document.documentElement.dataset.takeoverProbe = 'present'
    navigator.serviceWorker.dispatchEvent(new Event('controllerchange'))
  })
  await expect(page.locator('html')).toHaveAttribute('data-takeover-probe', 'present')
  await context.setOffline(true)
  await page.goto('/chat/?session=A&offline-proof=1')
  await expect(page.locator('textarea')).toHaveValue('offline draft survives')
  await expect(page.locator('.message-stream')).toContainText('reply A')
  expect(fixture.errors).toEqual([])
})

test('two real pages recover a stale-writer conflict without a reload, then retrieve the retained draft', async ({ page, context }, info) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const first = await fixtures(page)
  await page.goto('/chat/')
  await expect(page.locator('textarea')).toBeEnabled()
  const other = await context.newPage()
  const second = await fixtures(other)
  await other.goto('/chat/')
  await other.locator('textarea').fill('draft saved by the second page')
  await expect.poll(async () => (await saved(other)).sessions.some(row => row.draft === 'draft saved by the second page')).toBe(true)
  await page.locator('textarea').fill('draft written in the first page')
  await expect(page.getByTestId('recover-local-record')).toBeVisible()
  await other.close()
  await page.evaluate(() => { document.documentElement.dataset.conflictProbe = 'same-page' })
  await page.getByTestId('recover-local-record').click()
  await expect(page.locator('textarea')).toHaveValue('draft saved by the second page')
  await expect(page.getByTestId('recover-local-record')).toHaveCount(0)
  await expect(page.locator('html')).toHaveAttribute('data-conflict-probe', 'same-page')
  await page.getByRole('button', { name: '查看保留副本', exact: true }).click()
  await page.getByRole('button', { name: /重新同步前的本页/ }).click()
  await expect(page.getByTestId('recovery-copy-preview')).toContainText('draft written in the first page')
  await page.getByRole('button', { name: '找回这份草稿', exact: true }).click()
  await expect.poll(async () => (await saved(page)).sessions.some(row => row.draft === 'draft written in the first page')).toBe(true)
  // Copy cleanup is explicit and scoped; cancel leaves it intact, confirming
  // cannot remove the main conversation or its current draft/tool records.
  await page.getByRole('button', { name: /重新同步前的本页/ }).click()
  const beforeRemoval = await saved(page)
  const copies = page.locator('.recovery-copy-row')
  const count = await copies.count()
  page.once('dialog', dialog => dialog.dismiss())
  await page.getByTestId('remove-recovery-copy').click()
  await expect(copies).toHaveCount(count)
  page.once('dialog', async dialog => {
    expect(dialog.message()).toContain('无法恢复')
    await dialog.accept()
  })
  await page.getByTestId('remove-recovery-copy').click()
  await expect(copies).toHaveCount(count - 1)
  expect(await saved(page)).toEqual(beforeRemoval)
  await expect.poll(() => page.locator('.build-proof > div').evaluateAll(rows => rows.every(row => row.getBoundingClientRect().width > 200))).toBe(true)
  await page.screenshot({ path: info.outputPath('conflict-recovery-mobile.png'), animations: 'disabled' })
  await page.reload()
  await expect(page.locator('textarea')).toHaveValue('draft written in the first page')
  expect(first.errors).toEqual([])
  expect(second.errors).toEqual([])
})

// Two internally consistent deployments of the production build, on a private
// loopback server. Only build identity and its hashed JS URL change. The first
// worker omits the new read-only message, like an already installed old worker.
import { createServer } from 'node:http'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { createHash } from 'node:crypto'
async function updateFixture() {
  const root = resolve('../pwa/dist')
  const files = new Map<string, Buffer>()
  for (const path of readdirSync(root, { recursive: true, withFileTypes: true })) {
    if (path.isFile()) {
      const file = resolve(path.parentPath, path.name)
      files.set('/chat/' + relative(root, file).replaceAll('\\', '/'), readFileSync(file))
    }
  }
  const build = JSON.parse(files.get('/chat/build-info.json')!.toString())
  const nextId = `${build.buildId}-review-update`
  const index = files.get('/chat/index.html')!.toString()
  const jsPath = index.match(/src="([^"]+\.js)"/)![1]
  const nextJs = files.get(jsPath)!.toString().replaceAll(build.buildId, nextId)
  const nextJsPath = `/chat/assets/review-${createHash('sha256').update(nextJs).digest('hex').slice(0, 12)}.js`
  const nextIndex = index.replace(jsPath, nextJsPath)
  const worker = files.get('/chat/sw.js')!.toString()
  const messageStart = worker.indexOf('// Read-only build evidence')
  const messageEnd = worker.indexOf('async function deployedBuild()')
  expect(messageStart).toBeGreaterThan(0)
  expect(messageEnd).toBeGreaterThan(messageStart)
  const oldWorker = worker.slice(0, messageStart) + worker.slice(messageEnd)
  const nextWorker = worker.replaceAll(build.buildId, nextId).replaceAll(jsPath, nextJsPath)
  let upgraded = false
  const server = createServer((request, response) => {
    const path = new URL(request.url!, 'http://fixture').pathname
    let content = files.get(path)
    if (path === '/chat/' || path === '/chat/index.html') content = Buffer.from(upgraded ? nextIndex : index)
    if (path === '/chat/sw.js') content = Buffer.from(upgraded ? nextWorker : oldWorker)
    if (path === '/chat/build-info.json') content = Buffer.from(JSON.stringify(upgraded ? { ...build, buildId: nextId } : build))
    if (path === nextJsPath) content = Buffer.from(nextJs)
    response.writeHead(content ? 200 : 404, { 'Cache-Control': 'no-store',
      'Content-Type': path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css'
        : path.endsWith('.json') ? 'application/json' : path.endsWith('/') || path.endsWith('.html') ? 'text/html' : 'application/octet-stream' })
    response.end(content || 'not found')
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as { port: number }
  return { base: `http://127.0.0.1:${address.port}`, nextId, upgrade: () => { upgraded = true },
    close: () => new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())) }
}

test('a downloaded update waits safely across two installed pages and becomes the offline build after closing them', async ({ page, context }, info) => {
  test.setTimeout(60_000)
  const deployment = await updateFixture()
  const pages: Page[] = [page]
  try {
    await page.setViewportSize({ width: 390, height: 844 })
    const first = await fixtures(page)
    await page.goto(deployment.base + '/chat/')
    await page.evaluate(async () => { await navigator.serviceWorker.ready })
    await page.reload()
    await page.locator('textarea').fill('draft across a real waiting worker')
    await expect.poll(async () => (await saved(page)).sessions.some(row => row.draft === 'draft across a real waiting worker')).toBe(true)
    const other = await context.newPage(); pages.push(other)
    const second = await fixtures(other)
    await other.goto(deployment.base + '/chat/')
    await expect(other.locator('textarea')).toHaveValue('draft across a real waiting worker')
    await page.evaluate(() => { document.documentElement.dataset.updateProbe = 'still-here' })
    deployment.upgrade()
    await page.evaluate(async () => { await (await navigator.serviceWorker.getRegistration('/chat/'))!.update() })
    await page.getByRole('button', { name: '打开菜单', exact: true }).click()
    await page.getByTestId('open-chat-settings').click()
    await expect(page.getByTestId('offline-update-status')).toContainText('已准备')
    await expect(page.getByTestId('offline-update-status')).toContainText('关闭')
    await expect(page.locator('.build-proof')).toContainText(deployment.nextId)
    await expect(page.locator('html')).toHaveAttribute('data-update-probe', 'still-here')
    await expect.poll(() => page.locator('.build-proof > div').evaluateAll(rows => rows.every(row => row.getBoundingClientRect().width > 200))).toBe(true)
    await page.locator('.build-proof').scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath('waiting-update-mobile.png'), animations: 'disabled' })
    await page.close()
    expect(await other.evaluate(async () => Boolean((await navigator.serviceWorker.getRegistration('/chat/'))!.waiting))).toBe(true)
    await expect(other.locator('textarea')).toHaveValue('draft across a real waiting worker')
    await other.close()
    const reopened = await context.newPage(); pages.push(reopened)
    const third = await fixtures(reopened)
    await reopened.goto(deployment.base + '/chat/')
    await reopened.evaluate(async () => { await navigator.serviceWorker.ready })
    await reopened.reload()
    await expect(reopened.locator('textarea')).toHaveValue('draft across a real waiting worker')
    await context.setOffline(true)
    await reopened.goto(deployment.base + '/chat/?update-offline-proof=1')
    await expect(reopened.locator('textarea')).toHaveValue('draft across a real waiting worker')
    await reopened.getByRole('button', { name: '打开菜单', exact: true }).click()
    await reopened.getByTestId('open-chat-settings').click()
    await expect(reopened.locator('.build-proof')).toContainText(deployment.nextId)
    expect(first.errors).toEqual([]); expect(second.errors).toEqual([]); expect(third.errors).toEqual([])
  } finally {
    await context.setOffline(false)
    await Promise.all(pages.map(value => value.close().catch(() => {})))
    await deployment.close()
  }
})
