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
    await expect(page.getByTestId('page-home')).toBeVisible()
    const memButton = page.getByTestId('home-module-mem0')
    await expect(memButton).toBeVisible()
    await memButton.click()
    await expect(page).toHaveURL(/#\/mem0$/)
    await expect(page.getByTestId('page-mem')).toBeVisible()
  })
})

test('config page loads and accepts input without saving', async ({ page }) => {
  await openAdminRoute(page, '/config', async () => {
    await expect(page.getByTestId('page-config')).toBeVisible()
    const upstreamInput = page.getByTestId('config-upstream-url').locator('input')
    await upstreamInput.fill('https://example.test/v1')
    await expect(upstreamInput).toHaveValue('https://example.test/v1')
  })
})

test('sessions page loads and its search field accepts input', async ({ page }) => {
  await openAdminRoute(page, '/sessions', async () => {
    await expect(page.getByTestId('page-sessions')).toBeVisible()
    const search = page.getByTestId('sessions-search').locator('input')
    await search.fill('smoke-session')
    await expect(search).toHaveValue('smoke-session')
  })
})

test('calendar page loads', async ({ page }) => {
  await openAdminRoute(page, '/calendar', async () => {
    await expect(page.getByTestId('page-calendar')).toBeVisible()
  })
})

test('Mem page loads and its search field accepts input', async ({ page }) => {
  await openAdminRoute(page, '/mem0', async () => {
    await expect(page.getByTestId('page-mem')).toBeVisible()
    const search = page.getByTestId('mem-search')
    await search.fill('smoke')
    await expect(search).toHaveValue('smoke')
  })
})

test('Stars page loads and switches modes', async ({ page }) => {
  await openAdminRoute(page, '/stars', async () => {
    await expect(page.getByTestId('page-stars')).toBeVisible()
    const labels = page.getByTestId('stars-mode-labels')
    await labels.click()
    await expect(labels).toHaveClass(/active/)
  })
})

test('star map route loads its canvas', async ({ page }) => {
  await openAdminRoute(page, '/stars/map', async () => {
    await expect(page.getByTestId('page-star-map')).toBeVisible()
    await expect(page.getByTestId('star-map-canvas')).toBeVisible()
  })
})

test('logs page loads', async ({ page }) => {
  await openAdminRoute(page, '/logs', async () => {
    await expect(page.getByTestId('page-logs')).toBeVisible()
  })
})

test('Hisense page loads', async ({ page }) => {
  await openAdminRoute(page, '/hisense', async () => {
    await expect(page.getByTestId('page-hisense')).toBeVisible()
  })
})

test('archive page loads', async ({ page }) => {
  await openAdminRoute(page, '/archive', async () => {
    await expect(page.getByTestId('page-archive')).toBeVisible()
  })
})

test('conflict page loads', async ({ page }) => {
  await openAdminRoute(page, '/conflict', async () => {
    await expect(page.getByTestId('page-conflict')).toBeVisible()
  })
})

test('Room page keeps its mapped labels, dates, and fold sections alive', async ({ page }) => {
  await page.route('**/api/gateway/room/traces?*', async (route) => {
    await route.fulfill({
      json: {
        traces: [{
          id: 'trace-newspaper-basket',
          session_id: 'room-smoke',
          action: 'newspaper_basket',
          detail: { mode: 'list' },
          scribble: null,
          created_at: '2024-07-15T10:30:00+00:00',
        }],
        count: 1,
      },
    })
  })

  await openAdminRoute(page, '/room', async () => {
    await expect(page.getByTestId('page-room')).toBeVisible()
    await expect(page.getByTestId('room-newspaper-panel')).toBeVisible()
    await expect(page.getByTestId('room-newspaper-generate')).toBeEnabled()
    await expect(page.getByText('旧报纸篓', { exact: true })).toBeVisible()
    await expect(page.getByText('翻了旧报纸', { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('NaN')

    const windowsill = page.getByTestId('room-fold-windowsill')
    const hand = page.getByTestId('room-fold-hand')
    const drawer = page.getByTestId('room-fold-drawer')
    await expect(windowsill).toHaveAttribute('open', '')
    await expect(hand).not.toHaveAttribute('open', '')
    await expect(drawer).not.toHaveAttribute('open', '')

    await hand.locator('summary').click()
    await expect(hand).toHaveAttribute('open', '')
    await drawer.locator('summary').click()
    await expect(drawer).toHaveAttribute('open', '')
    await expect(drawer.locator('textarea')).toBeVisible()
  })
})

test('tool errors page loads', async ({ page }) => {
  await openAdminRoute(page, '/tool-errors', async () => {
    await expect(page.getByTestId('page-tool-errors')).toBeVisible()
  })
})
