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
  const star = {
    id: 'scene-history-star',
    session_tag: 'smoke',
    content: '一颗用于检查最近分类记录的星星',
    chord: 'Am',
    scenes: ['seen', 'want'],
    status: 'active',
    is_constant: false,
  }
  await page.addInitScript(({ history }) => {
    window.localStorage.setItem('star-scene-batch-history-v1', JSON.stringify(history))
  }, {
    history: [{
      id: 'recent-scene-run',
      createdAt: '2026-07-16T08:30:00.000Z',
      selected: 1,
      updated: 1,
      failed: 0,
      items: [{ starId: star.id, assignedScenes: ['seen'], ok: true }],
    }],
  })
  await page.route('**/api/gateway/stars?*', async (route) => {
    await route.fulfill({ json: { ok: true, count: 1, items: [star] } })
  })
  await openAdminRoute(page, '/stars', async () => {
    await expect(page.getByTestId('page-stars')).toBeVisible()
    const labels = page.getByTestId('stars-mode-labels')
    await labels.click()
    await expect(labels).toHaveClass(/active/)
    await expect(page.getByTestId('stars-label-history')).toBeVisible()
    await expect(page.getByTestId(`stars-label-history-item-${star.id}`)).toContainText('已手动调整')
    await expect(page.getByTestId(`stars-label-history-toggle-${star.id}-seen`)).toHaveClass(/selected/)
    await expect(page.getByTestId(`stars-label-history-toggle-${star.id}-want`)).toHaveClass(/selected/)
    await page.getByTestId('stars-mode-settings').click()
    const cooldown = page.getByTestId('stars-soft-direct-cooldown').locator('input')
    await expect(cooldown).toBeVisible()
    await cooldown.fill('12')
    await expect(cooldown).toHaveValue('12')
  })
})

test('star map route loads its canvas', async ({ page }) => {
  await openAdminRoute(page, '/stars/map', async () => {
    await expect(page.getByTestId('page-star-map')).toBeVisible()
    await expect(page.getByTestId('star-map-canvas')).toBeVisible()
  })
})

test('logs page exposes per-round cache structure', async ({ page }) => {
  const promptCache = {
    enabled: true,
    protocol: 'anthropic',
    ttl: '5m',
    breakpoints: ['system.end', 'messages[190].stable_tail.content[0]'],
    prefix_fingerprints: [
      { path: 'system.end', sha256: 'system-prefix' },
      { path: 'messages[190].stable_tail.content[0]', sha256: 'history-prefix' },
    ],
    cache_control_marker_count: 2,
    tail_guard_user_turns: 3,
  }
  const round = {
    round: 1,
    messages_count: 201,
    stream: true,
    final: true,
    usage: { input_tokens: 94000, cache_read_input_tokens: 6000, cache_creation_input_tokens: 0 },
    cache_usage: {
      total_input_tokens: 100000,
      total_input_reported: true,
      cache_read_input_tokens: 6000,
      cache_creation_input_tokens: 0,
      cache_prefix_reuse_percent: 100,
      reported: true,
    },
    prompt_cache: promptCache,
    upstream_payload_summary: { model: 'test-model', messages_count: 197, tools_count: 6 },
    tools: [],
  }
  const log = {
    id: 'cache-structure',
    request_id: 'cache-request',
    timestamp: '2026-07-15T14:43:52+00:00',
    session_tag: 'smoke',
    model: 'test-model',
    client_model: 'test-model',
    upstream_model: 'test-model',
    model_mapped: false,
    upstream_url: 'https://example.test/v1/messages',
    upstream_scope: 'default',
    status: 'ok',
    duration_ms: 1200,
    stream: true,
    tools_count: 6,
    tool_names: [],
    has_internal_tools: true,
    is_first_turn: false,
    original_messages_count: 2295,
    prepared_messages_count: 201,
    internal_tool_rounds: [round],
    prompt_cache: promptCache,
    error: null,
    response_preview: 'done',
  }
  await page.route('**/api/gateway/logs/cache-structure', async (route) => {
    await route.fulfill({ json: log })
  })
  await page.route('**/api/gateway/logs?*', async (route) => {
    await route.fulfill({ json: { logs: [log] } })
  })
  await openAdminRoute(page, '/logs', async () => {
    await expect(page.getByTestId('page-logs')).toBeVisible()
    const summary = page.getByTestId('log-summary-cache-structure-round-1')
    await expect(summary).toContainText('6.0k cached · 6%')
    await expect(summary.locator('.tag-cache')).toHaveAttribute('title', /前缀复用 100%/)
    await summary.click()
    await page.getByTestId('log-tab-upstream-cache-structure-round-1').click()
    const detail = page.getByTestId('log-detail-cache-structure-round-1')
    await expect(detail).toContainText('messages[190].stable_tail.content[0]')
    await expect(detail).toContainText('cache_control_marker_count')
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

test('resident bookshelf keeps all three tiers and living-book reader alive', async ({ page }) => {
  await page.route('**/api/books', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        home: {
          last_confirmed_at: '2026-07-19T19:00:00+08:00',
          current_week: '2026-W29',
          current_week_changes: 2,
        },
        identity: {
          kind: 'living',
          id: 'identity-book',
          slug: 'identity',
          title: '我是谁',
          status: 'active',
          revision: 3,
          updated_at: '2026-07-19T18:00:00+08:00',
          updated_by: '沈予',
        },
        origin_books: [],
        warnings: [],
      },
    })
  })
  await page.route(/\/api\/books\/identity(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        kind: 'living',
        book: {
          kind: 'living',
          id: 'identity-book',
          slug: 'identity',
          title: '我是谁',
          status: 'active',
          body: '我还在继续认识自己。',
          revision: 3,
          updated_at: '2026-07-19T18:00:00+08:00',
          updated_by: '沈予',
          created_at: '2026-07-17T18:00:00+08:00',
          annotations: [],
        },
        revisions: [],
      },
    })
  })
  await page.route(/\/api\/books\/home(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        kind: 'snapshot',
        book: {
          id: 'home-anchor',
          slug: 'home',
          title: '家现在',
          kind: 'snapshot',
          annotations: [],
        },
        snapshot: {
          live: {
            commit: '1234567890abcdef',
            revision: '1234567890abcdef',
            worktree_dirty: false,
            observed_at: '2026-07-19T20:00:00+08:00',
            last_confirmed_at: '2026-07-19T19:00:00+08:00',
            current_week: '2026-W29',
            current_week_changes: 1,
          },
          components: [{
            id: 'room',
            title: 'Room',
            status: 'ok',
            summary: '房间仍然接着记忆和工具。',
            core: ['书架一览已经露在房间里。'],
            resident_effect: '你不用先调用 shelf 才知道书架上有什么。',
          }],
          changes: {
            '2026-W29': [{
              week: '2026-W29',
              title: '共享书架',
              summary: '家现在恢复为自动家况',
              impact: '你看到的家况不会再被空白正文覆盖。',
              created_at: '2026-07-19T20:00:00+08:00',
            }],
          },
        },
      },
    })
  })
  await page.route('**/api/conflict-books', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        books: [{
          id: 'origin-smoke',
          title: '那次终于说清楚的事',
          thread: 'main',
          span_start: '2026-07-18T12:00:00+08:00',
          span_end: '2026-07-18T13:00:00+08:00',
          status: 'settled',
          read_count: 2,
          last_read_at: '2026-07-19T12:00:00+08:00',
          created_at: '2026-07-18T13:00:00+08:00',
          updated_at: null,
        }],
      },
    })
  })
  await openAdminRoute(page, '/conflict', async () => {
    await expect(page.getByTestId('page-conflict')).toBeVisible()
    await expect(page.getByTestId('bookshelf-tier-identity')).toBeVisible()
    await expect(page.getByTestId('bookshelf-tier-home')).toBeVisible()
    await expect(page.getByTestId('bookshelf-tier-origin')).toBeVisible()
    await expect(page.getByTestId('bookshelf-origin-origin-smoke')).toBeVisible()

    await page.getByTestId('bookshelf-book-home').click()
    await expect(page.getByTestId('home-snapshot-commit')).toHaveText('1234567890ab')
    await expect(page.getByText('影响：你看到的家况不会再被空白正文覆盖。')).toBeVisible()
    await expect(page.getByTestId('home-snapshot').getByTestId('living-book-body')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('home-snapshot')).toBeHidden()

    await page.getByTestId('bookshelf-book-identity').click()
    const body = page.getByTestId('living-book-body').locator('textarea')
    await expect(body).toHaveValue('我还在继续认识自己。')
    await body.fill('我还在继续认识自己，也还在慢慢长大。')
    await expect(body).toHaveValue('我还在继续认识自己，也还在慢慢长大。')
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
