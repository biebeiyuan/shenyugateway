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
    // MCP servers card is alive: empty list on a fresh gateway, add form opens.
    await expect(page.getByTestId('config-mcp-card')).toBeVisible()
    await expect(page.getByTestId('mcp-empty')).toBeVisible()
    await page.getByTestId('mcp-add-server').click()
    const mcpName = page.getByTestId('mcp-form-name').locator('input')
    await mcpName.fill('smoke_server')
    await expect(mcpName).toHaveValue('smoke_server')
    await page.getByTestId('mcp-form-cancel').click()
    await expect(page.getByTestId('mcp-form')).toBeHidden()
  })
})

test('sessions page protects single-heartbeat deletion with confirmation', async ({ page }) => {
  let heartbeatDeleted = false
  let deleteBody: unknown = null
  const session = {
    id: 'session-smoke',
    session_tag: 'smoke-session',
    client_name: 'e2e',
    started_at: '2026-08-10T00:00:00Z',
    last_active_at: '2026-08-10T00:00:00Z',
    first_message_at: '2026-08-10T00:00:00Z',
    message_count: 1,
    context_state_json: '{}',
    stored_message_count: 1,
    last_message_at: '2026-08-10T00:00:00Z',
    user_message_count: 1,
    assistant_message_count: 0,
    tool_message_count: 0,
    heartbeat_count: 1,
    latest_user_text: 'smoke',
  }
  const heartbeat = {
    id: 'hb-smoke',
    session_id: session.id,
    content: '只用于验证删除确认。',
    turn_number: 1,
    created_at: '2026-08-10T00:00:00Z',
    injected_at: null,
  }
  await page.route('**/api/gateway/sessions**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'DELETE' && path.endsWith('/heartbeats')) {
      deleteBody = request.postDataJSON()
      heartbeatDeleted = true
      await route.fulfill({ json: { ok: true, deleted: 1 } })
      return
    }
    if (path === '/api/gateway/sessions/smoke-session') {
      await route.fulfill({
        json: {
          session,
          stats: {
            messages: 1,
            user_messages: 1,
            assistant_messages: 0,
            tool_messages: 0,
            heartbeats: heartbeatDeleted ? 0 : 1,
            cold_start_snapshots: 0,
            context_snapshots: 0,
            raw_request_windows: 0,
          },
          latest_cold_start_snapshot: null,
          context_snapshots: [],
          raw_request_windows: [],
          cold_start_snapshots: [],
          recent_messages: [],
          heartbeats: heartbeatDeleted ? [] : [heartbeat],
        },
      })
      return
    }
    await route.fulfill({
      json: {
        sessions: [{ ...session, heartbeat_count: heartbeatDeleted ? 0 : 1 }],
        limit: 200,
        query: '',
      },
    })
  })

  await openAdminRoute(page, '/sessions', async () => {
    await expect(page.getByTestId('page-sessions')).toBeVisible()
    const search = page.getByTestId('sessions-search').locator('input')
    await search.fill('smoke-session')
    await expect(search).toHaveValue('smoke-session')

    await page.locator('.n-tabs-tab').filter({ hasText: 'Heartbeat' }).click()
    const deleteButton = page.getByTestId('heartbeat-delete-hb-smoke')
    await expect(deleteButton).toBeVisible()
    await deleteButton.click()
    expect(deleteBody).toBeNull()
    await expect(page.getByText('删除这条 Heartbeat？不会删除线程，且无法撤销。')).toBeVisible()
    await page.getByRole('button', { name: '确认删除' }).click()
    await expect(deleteButton).toBeHidden()
    expect(deleteBody).toEqual({ ids: ['hb-smoke'] })
  })
})

test('calendar page loads and exposes the day offset setting', async ({ page }) => {
  await openAdminRoute(page, '/calendar', async () => {
    await expect(page.getByTestId('page-calendar')).toBeVisible()
    await page.getByTestId('calendar-settings-toggle').click()
    await expect(page.getByTestId('calendar-day-offset')).toBeVisible()
  })
})

test('Mem page loads and its search field accepts input', async ({ page }) => {
  await openAdminRoute(page, '/mem0', async () => {
    await expect(page.getByTestId('page-mem')).toBeVisible()
    await expect(page.getByRole('button', { name: '可自动想起' })).toBeVisible()
    const storedTab = page.getByRole('button', { name: '已收起' })
    await storedTab.click()
    await expect(storedTab).toHaveClass(/active/)
    const search = page.getByTestId('mem-search')
    await search.fill('smoke')
    await expect(search).toHaveValue('smoke')
  })
})

test('memory graph page loads and exposes anchor management', async ({ page }) => {
  const anchor = {
    id: 'e1',
    entity_type: 'person',
    canonical_name: '老周',
    description: '',
    status: 'active',
    aliases: [{
      id: 'a1', entity_id: 'e1', alias: '老周', normalized_alias: '老周',
      status: 'confirmed', is_primary: true, provenance: 'manual',
    }],
    mention_count: 1,
    relation_count: 0,
    source_type_counts: {},
    last_mentioned_at: null,
  }
  await page.route('**/api/gateway/memory-graph?*', async (route) => {
    await route.fulfill({
      json: { ok: true, available: true, entities: [anchor], relations: [], entity_count: 1, relation_count: 0 },
    })
  })
  await page.route('**/api/gateway/memory-graph/entities/*/mentions*', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        items: [{
          source_table: 'journal',
          source_type: 'journal',
          source_id: 'journal-smoke',
          origin: 'exact_alias',
          title: '三月的信',
          excerpt: '今天和老周吃饭。',
          content: '今天和老周吃饭，聊了很久。饭后又散了散步。',
          content_complete: true,
          event_date: '2026-03-14T00:00:00Z',
        }],
      },
    })
  })
  await page.route('**/api/gateway/memory-graph/recall-preview', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        count: 1,
        items: [{
          source_id: 'journal-smoke',
          source_type: 'journal',
          source_table: 'journal',
          title: '和老周见面',
          event_date: '2026-07-23T00:00:00Z',
          content: '今天和老周吃饭，聊了很久。',
          recall_match: { group: 'direct', label: '直达：已确认锚点「老周」', anchor: { name: '老周' } },
        }],
      },
    })
  })
  await page.route('**/api/gateway/memory-graph/sources/**', async (route) => {
    await route.fulfill({ json: { ok: true, mentions: [] } })
  })
  await page.route('**/api/gateway/memory-graph/name-candidates*', async (route) => {
    await route.fulfill({ json: { ok: true, candidates: [] } })
  })
  await openAdminRoute(page, '/memory-graph', async () => {
    await expect(page.getByTestId('page-memory-graph')).toBeVisible()
    const search = page.getByTestId('memory-graph-search').locator('input')
    await search.fill('老周')
    await expect(search).toHaveValue('老周')
    await expect(page.getByRole('button', { name: '建立锚点' })).toBeVisible()
    // Picking a name runs a real recall and pins the result on the board.
    await page.getByRole('button', { name: '锚点：老周' }).click()
    await expect(page.getByTestId('memory-graph-tab-recall')).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByText('今天和老周吃饭，聊了很久。')).toBeVisible()
    await expect(page.getByText('提到了「老周」')).toBeVisible()
    // The word is a confirmed anchor, so the hub offers to manage it.
    await page.getByRole('button', { name: '管理这个名字' }).click()
    const overlay = page.getByTestId('memory-graph-originals-overlay')
    await expect(overlay).toBeVisible()
    await expect(overlay.getByText('今天和老周吃饭，聊了很久。饭后又散了散步。')).toBeVisible()
    await expect(overlay.getByText('命中词')).toBeVisible()
    await overlay.getByRole('button', { name: '放回去' }).click()
    await expect(overlay).toBeHidden()
    // Typing a fresh word recalls again on the same board.
    const recall = page.getByTestId('memory-graph-recall-input').locator('input')
    await recall.fill('老周')
    await page.getByRole('button', { name: '想起', exact: true }).click()
    await expect(page.getByText('今天和老周吃饭，聊了很久。')).toBeVisible()
    await expect(page.getByText('提到了「老周」')).toBeVisible()
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

test('logs page exposes per-round cache and response evidence', async ({ page }) => {
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
    upstream_response_evidence: {
      version: 1,
      protocol: 'anthropic',
      mode: 'stream',
      thinking_requested: true,
      upstream_format: 'anthropic_events',
      normalized_format: 'openai_chunks',
      upstream: {
        events: 8,
        thinking_blocks: 1,
        thinking_deltas: 2,
        thinking_content_seen: true,
        usage_seen: true,
        usage_values_seen: true,
        finish_seen: true,
      },
      normalized: {
        events: 5,
        thinking_blocks: 0,
        thinking_deltas: 2,
        thinking_content_seen: true,
      },
    },
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
    upstream_response_evidence: round.upstream_response_evidence,
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
    await page.getByTestId('log-tab-response-cache-structure-round-1').click()
    await expect(detail).toContainText('上游 anthropic_events：块 1 / 增量 2 / 正文 有')
    await expect(detail).toContainText('若 PWA 未显示，应检查 PWA 解析或展示')
  })
})

test('archive page loads', async ({ page }) => {
  await openAdminRoute(page, '/archive', async () => {
    await expect(page.getByTestId('page-archive')).toBeVisible()
  })
})

// 2026-08-30：日历展开后第一行被顶成 120px 高，留下一大块白。原因是月初前导空格子
// 用了 .empty，而本页空状态块（「这天很安静」）也叫 .empty 且带 padding: 60px 0。
// 只读 CSS 源码看不出来——两条规则各自都对，是类名撞了。所以这里断言计算后的行高。
test('archive calendar has no blank row when a month starts late in the week', async ({ page }) => {
  await openAdminRoute(page, '/archive', async () => {
    await expect(page.getByTestId('page-archive')).toBeVisible()
    const toggle = page.locator('.cal-toggle')
    if (!(await toggle.count())) return
    await toggle.click()
    const grid = page.locator('.cal-grid')
    await expect(grid).toBeVisible()
    const rows = await grid.evaluate((el) => getComputedStyle(el).gridTemplateRows)
    // 每一行都该是格子的高度，没有哪一行被撑成三倍
    const heights = rows.split(' ').map((value) => Math.round(parseFloat(value)))
    expect(heights.every((height) => height <= 40)).toBe(true)
    // 占位格子不占高度，但仍占列位（否则 1 号会跑到周一）
    const blank = grid.locator('.cal-cell.blank').first()
    if (await blank.count()) {
      expect(await blank.evaluate((el) => Math.round(el.getBoundingClientRect().height))).toBe(0)
    }
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
  await page.route('**/api/project-map', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        live: {
          commit: '1234567890abcdef',
          revision: '1234567890abcdef',
          worktree_dirty: false,
          observed_at: '2026-07-22T14:00:00+08:00',
          last_confirmed_at: '2026-07-22T13:00:00+08:00',
        },
        summary: {
          status: 'confirmed',
          component_count: 2,
          confirmed_count: 2,
          pending_count: 0,
          error_count: 0,
          zone_count: 2,
          bridge_count: 1,
          document_count: 1,
          delivery_count: 1,
          delivery_product_count: 1,
        },
        components: [
          {
            id: 'stars',
            title: '星星库',
            status: 'ok',
            summary: '让真正相关的联想记忆回来。',
            resident_effect: '星星不会每轮乱跳。',
            core: ['只让相关的星星浮现。'],
            files: ['shenyu_gateway/context_builder.py', 'shenyu_gateway/memory_island.py'],
            reviewed: { reviewed_at: '2026-07-22T13:00:00+08:00', reviewed_by: 'Codex' },
            zone_ids: ['zone-2'],
          },
          {
            id: 'mem',
            title: 'Mem',
            status: 'ok',
            summary: '让具体事实在需要时回来。',
            resident_effect: '承诺和名字不会轻易丢掉。',
            core: ['只在有锚点时召回。'],
            files: ['shenyu_gateway/context_builder.py', 'shenyu_gateway/memory_island.py'],
            reviewed: { reviewed_at: '2026-07-22T12:00:00+08:00', reviewed_by: 'Codex' },
            zone_ids: ['zone-2'],
          },
        ],
        zones: [
          {
            id: 'zone-1',
            number: '一',
            title: '入口与运行时',
            summary: '让请求安全进入。',
            responsibilities: ['让请求安全进入。'],
            core_files: ['gateway.py'],
            component_ids: [],
          },
          {
            id: 'zone-2',
            number: '五',
            title: '上下文与记忆',
            summary: '整理此刻需要带上的记忆。',
            responsibilities: ['整理此刻需要带上的记忆。'],
            core_files: ['shenyu_gateway/context_builder.py'],
            component_ids: ['stars', 'mem'],
          },
        ],
        request_flow: [
          {
            id: 'flow-1',
            label: '客户端',
            meaning: '你发来的话从这里出发。',
            zone_ids: [],
            details: [],
          },
          {
            id: 'flow-2',
            label: 'ContextBuilder',
            meaning: '整理此刻真正需要带上的记忆。',
            zone_ids: ['zone-2'],
            details: ['Calendar / Mem / Stars / Room'],
          },
        ],
        bridges: [{
          '桥梁': 'context_builder.py',
          '连接区域': '上下文、记忆、Room',
          '审计重点': '实际注入内容',
        }],
        component_bridges: [{
          id: 'stars--mem',
          left_id: 'stars',
          right_id: 'mem',
          via_files: ['shenyu_gateway/memory_island.py'],
          meaning: '它们共同经过 memory_island.py，改动时需要一起确认。',
        }],
        documents: [{
          '文档': 'docs/architecture/SYSTEM_ZONES.md',
          '职责': '现行代码分区、跨区桥梁和审计入口',
          '什么时候更新': '主要调用链改变时',
        }],
        products: [{
          '产品对象': 'PWA 聊天端',
          '常用叫法 / 旧名': '手机聊天',
          '后端入口': 'pwa/src/App.vue',
          'Admin/API': 'POST /v1/chat/completions',
          '现行文档': 'REQUEST_CONTEXT.md',
        }],
        deliveries: [{
          id: 'delivery-smoke',
          completed_at: '2026-08-06T10:18:33+08:00',
          title: 'PWA 新增可编辑上游请求头',
          product: 'PWA 聊天端',
          kind: 'feature',
          summary: '模型面板可以选择 Claude Code 请求头预设。',
          touchpoint: 'PWA → 模型选择 → 请求头',
          why: '上游兼容需要受控的请求身份。',
          status: 'pushed',
          verification: ['PWA 单测与手机 POST 映射通过'],
          paths: ['pwa/src/App.vue', 'shenyu_gateway/upstream_client.py'],
          docs: ['docs/architecture/REQUEST_CONTEXT.md'],
          commit: '03ea5989b809065e',
          lesson: '浏览器不能直接覆盖 User-Agent。',
          debug_ref: '',
          recorded_by: 'Codex',
          product_map: { '产品对象': 'PWA 聊天端' },
          zone_ids: [],
        }],
        changes: [],
        warnings: [],
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
    await expect(page.getByTestId('bookshelf-book-project-map')).toBeVisible()

    await page.getByTestId('bookshelf-book-project-map').click()
    await expect(page.getByTestId('project-map-atlas')).toBeVisible()
    await expect(page.getByTestId('project-map-status')).toHaveText('地图与现场一致')
    await expect(page.getByTestId('project-map-delivery-peek')).toContainText('PWA 新增可编辑上游请求头')
    await page.getByTestId('project-map-delivery-peek').click()
    const deliveryPanel = page.getByTestId('project-map-deliveries')
    await expect(deliveryPanel).toContainText('PWA 新增可编辑上游请求头')
    await deliveryPanel.locator('details').first().locator('summary').click()
    await expect(deliveryPanel).toContainText('浏览器不能直接覆盖 User-Agent。')
    await page.getByTestId('project-map-tab-overview').click()
    await page.getByTestId('project-map-overview-components').click()
    await expect(page.getByTestId('project-map-atlas')).toContainText('只让相关的星星浮现。')
    await page.getByTestId('project-map-overview-zones').click()
    await expect(page.getByTestId('project-map-zone-index')).toContainText('入口与运行时')
    await page.getByTestId('project-map-overview-bridges').click()
    await expect(page.getByTestId('project-map-bridge-index')).toContainText('context_builder.py')
    await page.getByTestId('project-map-tab-flow').click()
    await expect(page.getByTestId('project-map-flow')).toContainText('ContextBuilder')
    await page.getByTestId('project-map-tab-connections').click()
    const connectionPanel = page.getByTestId('project-map-connections')
    await expect(connectionPanel).toContainText('Mem')
    await expect(connectionPanel).toContainText('memory_island.py')
    await expect(connectionPanel).not.toContainText('context_builder.py')
    await page.getByTestId('project-map-tab-changes').click()
    await expect(page.getByTestId('project-map-atlas')).toContainText('八个生活机制都已确认')
    await expect(page.getByTestId('project-map-tab-changes')).toHaveText('机制确认')
    await expect(page.getByText('这册只在 Admin 里出现，不进入沈予的上下文。')).toBeVisible()
    await page.keyboard.press('Escape')

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
  await page.route('**/api/gateway/room/scribbles?*', async (route) => {
    await route.fulfill({
      json: {
        scribbles: [{
          id: 'room-windowsill-smoke',
          content: '这句通过房间窗台落进普通窗台。',
          origin: 'room',
          created_at: '2026-08-14T08:00:00+00:00',
        }],
        count: 1,
      },
    })
  })
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
    await expect(hand.getByText('这句通过房间窗台落进普通窗台。')).toBeVisible()
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
