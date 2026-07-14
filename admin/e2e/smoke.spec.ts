import { expect, test, type Page } from '@playwright/test'

const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || 18110}`
const ADMIN_URL = new URL('/admin/', BASE_URL).toString()
const GATEWAY_TOKEN = process.env.E2E_GATEWAY_TOKEN || 'shenyu-e2e-smoke'
const APP_ORIGIN = new URL(BASE_URL).origin

type BrowserFailureWatch = {
  assertClean: () => Promise<void>
}

function watchForBrowserFailures(page: Page): BrowserFailureWatch {
  const pageErrors: string[] = []
  const assetFailures: string[] = []
  const criticalResourceTypes = new Set(['document', 'script', 'stylesheet'])

  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).origin !== APP_ORIGIN) return
    if (!criticalResourceTypes.has(request.resourceType())) return
    assetFailures.push(`${request.resourceType()} ${request.url()} ${request.failure()?.errorText || ''}`.trim())
  })
  page.on('response', (response) => {
    const request = response.request()
    if (new URL(response.url()).origin !== APP_ORIGIN) return
    if (!criticalResourceTypes.has(request.resourceType()) || response.status() < 400) return
    assetFailures.push(`${request.resourceType()} ${response.status()} ${response.url()}`)
  })

  return {
    async assertClean() {
      await page.waitForTimeout(100)
      expect(pageErrors, 'uncaught browser errors').toEqual([])
      expect(assetFailures, 'failed same-origin documents, scripts, or stylesheets').toEqual([])
    },
  }
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{
    name: 'shenyu_token',
    value: GATEWAY_TOKEN,
    url: APP_ORIGIN,
    sameSite: 'Lax',
  }])
  await page.addInitScript(({ token }) => {
    window.localStorage.setItem('shenyu_token', token)
  }, { token: GATEWAY_TOKEN })
})

async function openAdminRoute(
  page: Page,
  route: string,
  assertReady: () => Promise<void>,
) {
  const failures = watchForBrowserFailures(page)
  await page.goto(`${ADMIN_URL}#${route}`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#app')).toBeVisible()
  await expect.poll(async () => (await page.locator('#app').innerText()).trim().length).toBeGreaterThan(0)
  await assertReady()
  await failures.assertClean()
}

test('home navigation is alive', async ({ page }) => {
  await openAdminRoute(page, '/', async () => {
    const memButton = page.getByRole('button', { name: /便签/ })
    await expect(memButton).toBeVisible()
    await memButton.click()
    await expect(page).toHaveURL(/#\/mem0$/)
    await expect(page.getByRole('heading', { name: '便签', exact: true })).toBeVisible()
  })
})

test('config page loads and accepts input without saving', async ({ page }) => {
  await openAdminRoute(page, '/config', async () => {
    await expect(page.getByText('Running', { exact: true })).toBeVisible()
    const upstreamInput = page.getByPlaceholder('https://api.anthropic.com')
    await upstreamInput.fill('https://example.test/v1')
    await expect(upstreamInput).toHaveValue('https://example.test/v1')
  })
})

test('sessions page loads and its search field accepts input', async ({ page }) => {
  await openAdminRoute(page, '/sessions', async () => {
    const search = page.getByPlaceholder('搜索线程标识或客户端名称')
    await search.fill('smoke-session')
    await expect(search).toHaveValue('smoke-session')
  })
})

test('calendar page loads', async ({ page }) => {
  await openAdminRoute(page, '/calendar', async () => {
    await expect(page.getByText('日历写作', { exact: true })).toBeVisible()
  })
})

test('Mem page loads and its search field accepts input', async ({ page }) => {
  await openAdminRoute(page, '/mem0', async () => {
    await expect(page.getByRole('heading', { name: '便签', exact: true })).toBeVisible()
    const search = page.getByPlaceholder('搜索内容…')
    await search.fill('smoke')
    await expect(search).toHaveValue('smoke')
  })
})

test('Stars page loads and switches modes', async ({ page }) => {
  await openAdminRoute(page, '/stars', async () => {
    await expect(page.getByRole('heading', { name: '星星', exact: true })).toBeVisible()
    const labels = page.getByRole('button', { name: '标签', exact: true })
    await labels.click()
    await expect(labels).toHaveClass(/active/)
  })
})

test('star map route loads its canvas', async ({ page }) => {
  await openAdminRoute(page, '/stars/map', async () => {
    await expect(page.getByRole('heading', { name: '记忆星图', exact: true })).toBeVisible()
    await expect(page.locator('canvas.star-canvas')).toBeVisible()
  })
})

test('logs page loads', async ({ page }) => {
  await openAdminRoute(page, '/logs', async () => {
    await expect(page.getByText('自动刷新', { exact: true })).toBeVisible()
  })
})

test('Hisense page loads', async ({ page }) => {
  await openAdminRoute(page, '/hisense', async () => {
    await expect(page.getByRole('heading', { name: '沈予的空间', exact: true })).toBeVisible()
  })
})

test('archive page loads', async ({ page }) => {
  await openAdminRoute(page, '/archive', async () => {
    await expect(page.locator('.archive-view .cal-toggle')).toBeVisible()
  })
})

test('conflict page loads', async ({ page }) => {
  await openAdminRoute(page, '/conflict', async () => {
    await expect(page.locator('.conflict-view')).toBeVisible()
    await expect(page.getByRole('button', { name: '刷新', exact: true })).toBeVisible()
  })
})

test('Room page keeps the in-place newspaper panel alive', async ({ page }) => {
  await openAdminRoute(page, '/room', async () => {
    await expect(page.getByRole('heading', { name: '房间', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '订阅报纸', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /做一期/ })).toBeVisible()
  })
})

test('tool errors page loads', async ({ page }) => {
  await openAdminRoute(page, '/tool-errors', async () => {
    await expect(page.getByRole('heading', { name: '工具报错', exact: true })).toBeVisible()
  })
})
