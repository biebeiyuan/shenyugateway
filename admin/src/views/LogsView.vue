<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { NButton, NEmpty, NTag, useMessage } from 'naive-ui'
import {
  fetchLogs,
  fetchLogDetail,
  type LogEntry,
  type LogDetail,
  type UpstreamResponseEvidence,
} from '@/api/logs'

const message = useMessage()

const logs = ref<LogEntry[]>([])
const expIds = ref(new Set<string>())
const detCache = ref<Record<string, LogDetail>>({})
const autoRefresh = ref(true)
const loading = ref(false)
const loadingDet = ref(new Set<string>())
const aTabs = ref<Record<string, string>>({})
let timer: ReturnType<typeof setInterval> | null = null

// 网关工具名 → 这条工具大致做了什么（给非技术视角看的）
const GATEWAY_TOOL_HINTS: Record<string, string> = {
  shenyu_recall: '翻找以前的事',
  shenyu_recall_main_thread: '查最近主线对话',
  shenyu_search_mem_notes: '搜便签',
  shenyu_list_mem_notes: '列便签',
  shenyu_write_mem_note: '写一条便签',
  shenyu_update_mem_note: '改一条便签',
  shenyu_bulk_update_mem_notes: '批量改便签',
  shenyu_delete_mem_note: '删一条便签',
  shenyu_create_star: '写一颗星',
  shenyu_search_stars: '搜星星',
  shenyu_list_stars: '列星星',
  shenyu_star_review: '星星 review',
  shenyu_star_feedback: '给星星召回反馈',
  shenyu_connect_constellation: '连星座',
  shenyu_mark_constant: '标记恒星',
  shenyu_add_calendar: '写一页日历日记',
  shenyu_read_heartbeat: '读自己留的心跳',
  shenyu_last_seen: '看上次聊了什么',
  shenyu_books: '查看或书写共享书架',
  shenyu_conflict_list: '看来历书书架',
  shenyu_conflict_read: '翻开一本来历书',
  shenyu_conflict_annotate: '在来历书里批注',
  shenyu_notebook_list: '看手边的事',
  shenyu_notebook_write: '记一条手边的事',
  shenyu_notebook_update: '改一条手边的事',
  shenyu_supabase_guide: '查 Supabase 表结构',
  shenyu_gateway_tool: '记忆库总入口（broker）',
  room_drawer_notes: '翻圆儿的纸条抽屉',
  room_wooden_box: '翻木盒子里的心跳',
  room_star_map: '看星图墙',
  room_notebook: '翻房间笔记本',
  room_scribble: '读写窗台涂鸦本',
  room_wall_pins: '看墙上便签',
  room_conflict_shelf: '翻来历书架',
  room_sit_by_window: '坐在窗边',
  room_octopus_pillow: '抱章鱼抱枕',
  room_locked_drawer: '打开上锁抽屉',
  supabase_query: '查 Supabase 表',
  supabase_insert: '往 Supabase 写一行',
  supabase_update: '改 Supabase 的行',
  supabase_delete: '删 Supabase 的行',
}

function isGatewayTool(name: string): boolean {
  return name.startsWith('shenyu_') || name.startsWith('supabase_') || name.startsWith('room_')
}

function toolHint(name: string): string {
  return GATEWAY_TOOL_HINTS[name] || ''
}

const TAB_NAMES = ['overview', 'tools', 'messages', 'system', 'response', 'upstream', 'meta', 'raw'] as const
const TAB_LABELS: Record<string, string> = {
  overview: '概览', tools: '工具执行', messages: 'Messages',
  response: 'Response', system: 'System', upstream: 'Upstream', meta: 'Meta', raw: 'Raw JSON',
}

onMounted(async () => {
  await loadLogs()
  if (autoRefresh.value) {
    timer = setInterval(() => { loadLogs() }, 3000)
  }
})

onUnmounted(() => {
  if (timer) { clearInterval(timer); timer = null }
})

async function loadLogs() {
  loading.value = true
  try {
    const data = await fetchLogs(30)
    logs.value = data.logs || []
  } catch {
    message.error('Failed to load logs')
  } finally {
    loading.value = false
  }
}

function toggleAuto() {
  if (autoRefresh.value) {
    timer = setInterval(() => { loadLogs() }, 3000)
  } else {
    if (timer) { clearInterval(timer); timer = null }
  }
}

function esc(s: unknown): string {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function clsName(status: string): string {
  if (status === 'error' || status === 'client_disconnected' || status === 'interrupted') return 'error'
  if (status === 'ok' || status === 'success') return 'ok'
  if (status === 'streaming') return 'streaming'
  return 'pending'
}

function timeStr(ts: string | null | undefined): string {
  return (ts || '').substring(11, 19)
}

function fmtNum(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k'
  return String(n)
}

// Prefer the backend-normalized total input; keep a protocol-aware fallback for old logs.
function totalInputTokens(log: LogEntry, round?: any): number | null {
  const cache = round?.cache_usage || log.cache_usage
  if (cache?.total_input_reported && typeof cache.total_input_tokens === 'number') {
    return cache.total_input_tokens > 0 ? cache.total_input_tokens : null
  }
  const u = round?.usage || log.usage
  if (!u || typeof u !== 'object') return null
  if (typeof u.cache_input_tokens === 'number' && u.cache_input_tokens > 0) return u.cache_input_tokens
  if (typeof u.prompt_tokens === 'number' && u.prompt_tokens > 0) return u.prompt_tokens
  if (typeof u.input_tokens !== 'number') return null
  const protocol = round?.prompt_cache?.protocol || log.prompt_cache?.protocol
  const total = protocol === 'anthropic'
    ? u.input_tokens + usageCacheRead(u) + usageCacheWrite(u)
    : u.input_tokens
  return total > 0 ? total : null
}

function totalInputLabel(log: LogEntry, round?: any): string {
  const t = totalInputTokens(log, round)
  return t === null ? '' : `${fmtNum(t)} input`
}

function cacheReadTokens(log: LogEntry, round?: any): number {
  const cache = round?.cache_usage || log.cache_usage
  if (typeof cache?.cache_read_input_tokens === 'number') {
    return Math.max(0, cache.cache_read_input_tokens)
  }
  return usageCacheRead(round?.usage || log.usage)
}

function cacheReadPercent(log: LogEntry, round?: any): number | null {
  const read = cacheReadTokens(log, round)
  const total = totalInputTokens(log, round)
  if (total === null || read > total) return null
  return Math.round(read * 1000 / total) / 10
}

function cachePrefixReusePercent(log: LogEntry, round?: any): number | null {
  const cache = round?.cache_usage || log.cache_usage
  if (typeof cache?.cache_prefix_reuse_percent === 'number') return cache.cache_prefix_reuse_percent
  const usage = round?.usage || log.usage
  return usageCachePrefixReusePercent(usage)
}

function cacheLabel(log: LogEntry, round?: any): string {
  const read = cacheReadTokens(log, round)
  if (read <= 0) return ''
  const percent = cacheReadPercent(log, round)
  const percentLabel = percent === null ? '' : ` · ${percent}%`
  return `⚡ ${fmtNum(read)} cached${percentLabel}`
}

function cacheTitle(log: LogEntry, round?: any): string {
  const cache = round?.cache_usage || log.cache_usage
  const read = cacheReadTokens(log, round)
  if (read <= 0) return ''
  const usage = round?.usage || log.usage
  const write = typeof cache?.cache_creation_input_tokens === 'number'
    ? Math.max(0, cache.cache_creation_input_tokens)
    : usageCacheWrite(usage)
  const total = totalInputTokens(log, round)
  const coverage = cacheReadPercent(log, round)
  const prefixReuse = cachePrefixReusePercent(log, round)
  const totalText = total === null ? '' : ` · 总输入 ${total.toLocaleString()} tokens`
  const coverageText = coverage === null ? '' : ` · 缓存率 ${coverage}%`
  const prefixText = prefixReuse === null ? '' : ` · 前缀复用 ${prefixReuse}%`
  return `供应商上报缓存读取 ${read.toLocaleString()} tokens${totalText}${coverageText} · 新写 ${write.toLocaleString()} tokens${prefixText}。缓存率是读取 ÷ 总输入，不是费用节省比例。`
}

function roundKey(id: string, round?: any): string {
  return round ? `${id}:round:${round.round}` : `${id}:request`
}

async function toggleDetail(id: string, round?: any) {
  const key = roundKey(id, round)
  if (expIds.value.has(key)) {
    expIds.value.delete(key)
  } else {
    expIds.value.add(key)
    aTabs.value[key] = aTabs.value[key] || (round ? 'response' : 'overview')
    loadDetailTab(id)
  }
}

async function loadDetailTab(id: string) {
  if (detCache.value[id]) {
    return
  }
  loadingDet.value.add(id)
  try {
    const detail = await fetchLogDetail(id)
    detCache.value[id] = detail
  } catch {
    message.error(`Failed to load detail for ${id}`)
  } finally {
    loadingDet.value.delete(id)
  }
}

function switchTab(id: string, tab: string, round?: any) {
  const key = roundKey(id, round)
  aTabs.value[key] = tab
  if (!detCache.value[id]) {
    loadDetailTab(id)
  }
}

function collapseAll() {
  expIds.value.clear()
  detCache.value = {}
}

function displayRounds(log: LogEntry): any[] {
  const rounds = Array.isArray(log.internal_tool_rounds) ? log.internal_tool_rounds : []
  if (rounds.length) return rounds
  return [{
    round: 1,
    final: true,
    usage: log.usage,
    cache_usage: log.cache_usage,
    finish_reason: log.finish_reason,
    response_preview: log.response_preview,
    upstream_duration_ms: log.duration_ms,
    tools: [],
  }]
}

function roundTone(log: LogEntry, round: any, index: number, rounds: any[]): string {
  if (log.status === 'error') return 'error'
  return round.final === true || index === rounds.length - 1 ? 'ok' : 'intermediate'
}

function roundTime(log: LogEntry, round: any): string {
  if (!round || round.round <= 1) return timeStr(log.timestamp)
  return `${timeStr(log.timestamp)} +${round.round - 1}`
}

function roundDuration(log: LogEntry, round: any): number {
  return Number(round?.upstream_duration_ms ?? log.duration_ms) || 0
}

function usageInput(usage: Record<string, any> | null | undefined): number {
  return Number(usage?.prompt_tokens ?? usage?.input_tokens) || 0
}

function usageOutput(usage: Record<string, any> | null | undefined): number {
  return Number(usage?.completion_tokens ?? usage?.output_tokens) || 0
}

function usageCacheRead(usage: Record<string, any> | null | undefined): number {
  return Number(
    usage?.cache_read_input_tokens
    ?? usage?.prompt_tokens_details?.cached_tokens
    ?? usage?.input_tokens_details?.cached_tokens,
  ) || 0
}

function usageCacheWrite(usage: Record<string, any> | null | undefined): number {
  return Number(
    usage?.cache_creation_input_tokens
    ?? usage?.prompt_tokens_details?.cached_creation_tokens
    ?? usage?.input_tokens_details?.cached_creation_tokens,
  ) || 0
}

function usageCachePrefixReusePercent(usage: Record<string, any> | null | undefined): number | null {
  const read = usageCacheRead(usage)
  const write = usageCacheWrite(usage)
  if (read + write <= 0) return null
  return Math.round(read * 1000 / (read + write)) / 10
}

function decisionText(value: unknown): string {
  const key = String(value || '')
  if (key === 'retained') return '安稳地留在原位'
  if (key === 'rewritten') return '这次换了一些内容'
  return '状态还没有记录下来'
}

function reasonText(value: unknown): string {
  const key = String(value || '')
  const labels: Record<string, string> = {
    retained_overlap: '和上次足够接近，所以没有打扰它',
    overlap_below_threshold: '这次想起的内容变化比较大',
    content_changed: '同一条记忆的内容有更新',
    direct_candidate: '出现了需要直接带上的新内容',
    direct_star_id: '用户直接点名了这颗星的 ID',
    direct_exact_phrase: '用户复述了只属于这颗星的原句',
    direct_recall_unique: '回忆意图唯一指向一颗星，且已过冷却期',
    inactive_item: '旧岛里有内容已收起，需要重新整理',
    history_branch: '历史分支改变，按当前对话重新整理',
    message_high_water: '消息窗口触发裁剪，按当前窗口重新整理',
    empty_transition: '内容从有到无，或从无到有',
    forced: '这次被明确要求重新整理',
    proposal_applied: '采用了本次召回结果',
    due_reminder: '有便签写的日子到了，挂上来给他看一次',
  }
  return labels[key] || key || '没有额外原因'
}

function islandRenderedText(detail: LogDetail): string {
  return String(detail.memory_island_content?.rendered_text || '').trim()
}

function islandItemHtml(item: any, status?: string): string {
  const text = String(item?.text || '').trim() || '内容未记录'
  const label = String(item?.label || '').trim()
  const statusLabel: Record<string, string> = {
    added: '新增',
    updated: '更新',
    before: '原来',
    removed: '移除',
  }
  return `<div class="island-memory-item ${status ? `memory-${status}` : ''}"><div class="memory-item-top">${label ? `<span class="memory-item-label">${esc(label)}</span>` : ''}${statusLabel[status || ''] ? `<span class="memory-change-label">${statusLabel[status || '']}</span>` : ''}</div><div class="memory-item-text">${esc(text)}</div></div>`
}

function islandLaneHtml(title: string, icon: string, lane: any): string {
  if (!lane) return ''
  const current = Array.isArray(lane.current) ? lane.current : []
  const removed = Array.isArray(lane.removed) ? lane.removed : []
  const updated = Array.isArray(lane.updated) ? lane.updated : []
  const addedCount = Number(lane.added_count) || 0
  const removedCount = Number(lane.removed_count) || 0
  const updatedCount = Number(lane.updated_count) || 0
  let html = `<div class="island-lane"><div class="island-lane-head"><div class="island-lane-title"><span>${icon}</span>${esc(title)}</div><div class="island-lane-count">现在 ${current.length} · <b class="count-added">+${addedCount}</b> <b class="count-updated">~${updatedCount}</b> <b class="count-removed">−${removedCount}</b></div></div>`
  html += '<div class="island-current-title">现在岛上是这些</div>'
  html += current.length
    ? `<div class="island-memory-list">${current.map((item: any) => islandItemHtml(item, item.change === 'retained' ? '' : item.change)).join('')}</div>`
    : '<div class="empty-soft">现在这里是空的。</div>'
  if (updated.length) {
    html += `<div class="island-change-group"><div class="island-change-title change-updated">这次更新</div>${updated.map((item: any) => `<div class="memory-update-pair">${islandItemHtml(item.before, 'before')}<span class="memory-update-arrow">→</span>${islandItemHtml(item.after, 'updated')}</div>`).join('')}</div>`
  }
  if (removed.length) {
    html += `<div class="island-change-group"><div class="island-change-title change-removed">这次离开小岛</div><div class="island-memory-list">${removed.map((item: any) => islandItemHtml(item, 'removed')).join('')}</div></div>`
  }
  html += '</div>'
  return html
}

function renderOverview(detail: LogDetail): string {
  const island = detail.memory_island || {}
  const content = detail.memory_island_content
  const star = island.star || {}
  const mem = island.mem || {}
  const cache = detail.cache_usage
  const changed = Boolean(island.changed)
  const islandTone = changed ? 'island-changed' : 'island-calm'
  const islandTitle = changed ? '小岛这次轻轻换了位置' : '小岛还在原来的地方'
  const islandSubtitle = changed
    ? '实际送给沈予的记忆内容有变化，下面可以直接看到。'
    : '这次沿用了上一轮的小岛，没有重新搬动。'

  let html = `<div class="island-hero ${islandTone}"><div class="island-orb">${changed ? '✦' : '◌'}</div><div><div class="island-hero-title">${islandTitle}</div><div class="island-hero-sub">${islandSubtitle}</div></div></div>`
  html += '<div class="soft-grid">'
  html += `<div class="soft-card"><div class="soft-label">星星</div><div class="soft-value">${decisionText(star.decision)}</div><div class="soft-note">${reasonText(star.reason)}${typeof star.overlap === 'number' ? ` · 重合 ${(star.overlap * 100).toFixed(0)}%` : ''}</div></div>`
  html += `<div class="soft-card"><div class="soft-label">Mem</div><div class="soft-value">${decisionText(mem.decision)}</div><div class="soft-note">${reasonText(mem.reason)}${typeof mem.overlap === 'number' ? ` · 重合 ${(mem.overlap * 100).toFixed(0)}%` : ''}</div></div>`
  html += `<div class="soft-card"><div class="soft-label">这座小岛</div><div class="soft-value">${content?.star_count ?? star.chosen_count ?? 0} 颗星 · ${content?.mem_count ?? mem.chosen_count ?? 0} 条 Mem</div><div class="soft-note">${esc(content?.version || detail.memory_island_version || '版本未记录')}</div></div>`
  html += '</div>'

  if (content?.stars || content?.mem_notes) {
    html += '<div class="island-section"><div class="island-section-title">现在的小岛，以及这次变了什么</div><div class="island-lanes">'
    html += islandLaneHtml('星星', '✦', content.stars)
    html += islandLaneHtml('Mem', '▤', content.mem_notes)
    html += '</div></div>'
  }

  const rendered = islandRenderedText(detail)
  if (rendered || (!content?.stars && !content?.mem_notes)) {
    html += `<div class="island-section"><div class="island-section-title">${content?.stars || content?.mem_notes ? '送给沈予的完整原文' : '这次真正送过去的小岛'}</div>`
    html += rendered
      ? `<div class="island-content">${esc(rendered)}</div>`
      : '<div class="empty-soft">这条旧日志没有单独保存小岛正文，可以去 System 里看完整上下文。</div>'
    html += '</div>'
  }

  html += '<div class="island-section"><div class="island-section-title">缓存留下的原始回声</div>'
  if (!detail.prompt_cache?.enabled) {
    html += '<div class="empty-soft">这次没有启用 prompt cache。</div>'
  } else if (cache?.reported) {
    const coverage = cacheReadPercent(detail)
    const prefixReuse = cachePrefixReusePercent(detail)
    html += `<div class="cache-raw"><span>读取 ${Number(cache.cache_read_input_tokens || 0).toLocaleString()}</span><span>写入 ${Number(cache.cache_creation_input_tokens || 0).toLocaleString()}</span>${coverage === null ? '' : `<span>缓存率 ${coverage}%</span>`}${prefixReuse === null ? '' : `<span>前缀复用 ${prefixReuse}%</span>`}<span>${cache.rounds || 1} 轮</span></div>`
    html += '<div class="soft-footnote">顶部缓存率使用缓存读取 ÷ 总输入；前缀复用只比较缓存读取和缓存新写入。两者都不等于费用节省比例。</div>'
  } else {
    html += '<div class="empty-soft">这次 API usage 没有提供可识别的缓存读写字段，因此缓存状态未知；不能据此判断供应商内部是否命中缓存。</div>'
  }
  html += '</div>'
  return html
}

function finishText(reason: unknown, final: boolean): string {
  if (final) return '这一轮把话好好说完了'
  if (reason === 'tool_calls') return '说到这里，先去做一件事'
  if (reason === 'length') return '这一轮碰到了长度边界'
  return '这一轮结束，故事还会继续'
}

function renderRoundTools(round: any): string {
  const tools = round.tools || []
  if (!tools.length) return ''
  const items = tools.map((tool: any) => {
    const hint = toolHint(tool.target_tool || tool.name)
    const result = tool.ok === false ? '没有成功' : tool.cached_duplicate ? '沿用了刚才的结果' : '已经做好了'
    return `<div class="round-tool"><div><span class="round-tool-icon">⌁</span><strong>${esc(tool.target_tool || tool.name)}</strong>${hint ? `<span class="round-tool-hint">${esc(hint)}</span>` : ''}</div><span class="round-tool-result ${tool.ok === false ? 'failed' : ''}">${result}${typeof tool.duration_ms === 'number' ? ` · ${tool.duration_ms}ms` : ''}</span></div>`
  }).join('')
  return `<div class="round-tool-list"><div class="round-small-title">这一轮做了什么</div>${items}</div>`
}

function selectedRound(detail: LogDetail, roundNumber?: number): any | null {
  if (!roundNumber || !Array.isArray(detail.internal_tool_rounds)) return null
  return detail.internal_tool_rounds.find((round) => round.round === roundNumber) || null
}

function responseEvidenceText(evidence?: UpstreamResponseEvidence | null): string {
  if (!evidence) return ''
  const upstream = evidence.upstream || {}
  const normalized = evidence.normalized || {}
  const requested = evidence.thinking_requested ? 'Thinking 已请求' : 'Thinking 未请求'
  const rawThinking = `上游 ${evidence.upstream_format || 'unknown'}：块 ${upstream.thinking_blocks || 0} / 增量 ${upstream.thinking_deltas || 0} / 正文 ${upstream.thinking_content_seen ? '有' : '无'}`
  const normalizedThinking = `网关输出 ${evidence.normalized_format || 'unknown'}：块 ${normalized.thinking_blocks || 0} / 增量 ${normalized.thinking_deltas || 0} / 正文 ${normalized.thinking_content_seen ? '有' : '无'}`
  const terminal = `usage ${upstream.usage_seen ? (upstream.usage_values_seen ? '有值' : '空') : '未见'} / 完成信号 ${upstream.finish_seen ? '有' : '未见'}`
  let verdict = ''
  if (!upstream.events) {
    verdict = '结论：尚未收到可判断的上游响应事件'
  } else if (!upstream.thinking_content_seen) {
    verdict = '结论：上游标准响应里没有可显示的 Thinking'
  } else if (!normalized.thinking_content_seen) {
    verdict = '结论：上游有 Thinking，但网关转换后丢失'
  } else {
    verdict = '结论：网关已把 Thinking 交给客户端；若 PWA 未显示，应检查 PWA 解析或展示'
  }
  return [requested, rawThinking, normalizedThinking, terminal, verdict].join('\n')
}

function renderContent(detail: LogDetail, tab: string, roundNumber?: number): string {
  const round = selectedRound(detail, roundNumber)
  if (tab === 'overview') return renderOverview(detail)
  if (tab === 'system') {
    const full = detail.system_additions_full || detail.system_additions_preview || '(无)'
    return esc(full)
  }

  if (tab === 'messages') {
    const msgs = round?.messages || detail.prepared_messages || []
    const previews = round?.messages_preview || detail.prepared_messages_preview || []
    if (!msgs.length && previews.length) {
      const expectedCount = round?.messages_count || detail.prepared_messages_count || 0
      const omitted = expectedCount > previews.length ? expectedCount - previews.length : 0
      let notice = '<div class="empty-soft">未保留完整消息正文，以下是每条最多 500 字的预览；需要全文时在设置页打开“保留完整请求内容”，再看之后的新请求。</div>'
      if (omitted) {
        const legacyHead = detail.persisted && (detail.persistence_schema_version || 1) < 2
        notice += `<div class="empty-soft">${legacyHead
          ? `这条是旧格式的持久化记录：只存了最早的 ${previews.length} 条预览，最新的 ${omitted} 条缺失。`
          : `持久化历史只保留最新 ${previews.length} 条预览，更早的 ${omitted} 条已省略。`}</div>`
      }
      return notice + previews.map((m: any) => {
        const roleLabel = m.name ? `${m.role} (${m.name})` : m.role
        let extra = ''
        if (m.tool_calls && m.tool_calls.length) {
          extra = m.tool_calls.map((tc: any) =>
            `<div class="tc-block"><div class="tc-name">🔧 ${esc(tc.name || 'unknown')}</div><div class="tc-args">${esc(tc.arguments_preview || '')}</div></div>`,
          ).join('')
        }
        return `<div class="mb"><div class="mr ${m.role}">${esc(roleLabel)}</div><div class="mc">${esc(m.content_preview || '')}</div><div class="rev-meta">${m.content_chars || 0} chars</div>${extra}</div>`
      }).join('')
    }
    if (!msgs.length) return '(无消息)'
    return msgs.map((m: any) => {
      let content = ''
      if (typeof m.content === 'string') content = m.content
      else if (m.content) content = JSON.stringify(m.content, null, 2)
      let extra = ''
      if (m.tool_calls && m.tool_calls.length) {
        extra = m.tool_calls.map((tc: any) => {
          const fn = tc.function || {}
          let args = fn.arguments || '{}'
          try { args = JSON.stringify(JSON.parse(args), null, 2) } catch { /* ok */ }
          return `<div class="tc-block"><div class="tc-name">🔧 ${esc(fn.name || 'unknown')}</div><div class="tc-args">${esc(args)}</div></div>`
        }).join('')
      }
      let roleLabel = m.role
      if (m.role === 'tool' && m.name) roleLabel = `tool (${m.name})`
      return `<div class="mb"><div class="mr ${m.role}">${esc(roleLabel)}</div><div class="mc">${esc(content)}</div>${extra}</div>`
    }).join('')
  }

  if (tab === 'tools') {
    if (round) {
      const tools = round.tools || []
      if (!tools.length) return '<div class="empty-soft">这一轮没有执行网关工具。</div>'
      return `<div class="tool-section"><div class="tool-section-title">这一轮做了 ${tools.length} 件事</div>${tools.map((tool: any) => {
        const hint = toolHint(tool.target_tool || tool.name)
        return `<div class="tool-call-item"><div class="tool-call-row"><span class="tc-call-name">🔧 ${esc(tool.target_tool || tool.name)}</span>${hint ? `<span class="tc-call-hint">${esc(hint)}</span>` : ''}<span class="tool-timing">${tool.duration_ms || 0}ms</span></div>${tool.args_preview ? `<div class="tool-detail-block">${esc(tool.args_preview)}</div>` : ''}${tool.result_preview ? `<div class="tool-detail-block ${tool.ok === false ? 'tool-fail' : 'tool-ok'}">${esc(tool.result_preview)}</div>` : ''}</div>`
      }).join('')}</div>`
    }
    const names = detail.tool_names_all || detail.tool_names || []
    if (!names.length) return '(无工具)'

    // 上半部分：保持原样，工具名清单
    let listText = names.map((n, i) => `${i + 1}. ${n}`).join('\n')
    listText += `\n\n总计 ${names.length} 个工具`
    if (detail.has_internal_tools) listText += '\n含内部工具'
    let out = `<div class="tools-list">${esc(listText)}</div>`

    // 下半部分一：这条请求里，沈予实际调用了哪些网关工具、做了什么
    const rounds = detail.internal_tool_rounds || []
    let totalCalls = 0
    const roundsHtml: string[] = []
    if (Array.isArray(rounds)) {
      for (const r of rounds) {
        const tools = r.tools || []
        if (!tools.length) continue
        totalCalls += tools.length
        const toolItems = tools.map((t) => {
          const hint = toolHint(t.name)
          const targetLabel = t.target_tool ? `<span class="tool-target">→ ${esc(t.target_tool)}</span>` : ''
          const timingBadge = typeof t.duration_ms === 'number' ? `<span class="tool-timing">${t.duration_ms}ms</span>` : ''
          const cachedMark = t.cached_duplicate ? '<span class="tc-cached">（命中缓存）</span>' : ''
          const okClass = t.cached_duplicate ? '' : (t.ok === true ? ' tool-ok' : t.ok === false ? ' tool-fail' : '')

          let detail = ''
          if (t.args_preview && t.args_preview !== '{}') {
            detail += `<div class="tool-detail-block">${esc(t.args_preview)}</div>`
          }
          if (t.result_preview) {
            detail += `<div class="tool-detail-block${okClass}">${esc(t.result_preview)}</div>`
          }

          return `<div class="tool-call-item"><div class="tool-call-row"><span class="tc-call-name">🔧 ${esc(t.name)}</span>${targetLabel}${hint ? `<span class="tc-call-hint">${esc(hint)}</span>` : ''}${timingBadge}${cachedMark}</div>${detail}</div>`
        }).join('')
        const roundLabel = rounds.length > 1 ? `<div class="tool-round-header">第 ${r.round} 轮 · ${tools.length} 次调用</div>` : ''
        roundsHtml.push(`<div class="tool-round-group">${roundLabel}${toolItems}</div>`)
      }
    }
    if (totalCalls) {
      out += `<div class="tool-section"><div class="tool-section-title">本次调用的网关工具 · ${totalCalls} 次${rounds.length > 1 ? ` · ${rounds.length} 轮` : ''}</div>${roundsHtml.join('')}</div>`
    } else if (detail.has_internal_tools) {
      out += `<div class="tool-section"><div class="tool-section-title">本次调用的网关工具</div><div class="tool-empty">这条请求挂了网关工具，但沈予没有实际调用。</div></div>`
    }

    // 下半部分二：这条请求上下文里展开的客户端工具（非网关的）
    const clientTools = names.filter((n) => !isGatewayTool(n))
    if (clientTools.length) {
      const items = clientTools.map((n) => `<div class="tool-call-row"><span class="tc-call-name">🧩 ${esc(n)}</span></div>`).join('')
      out += `<div class="tool-section"><div class="tool-section-title">上下文里的客户端工具 · ${clientTools.length} 个</div>${items}</div>`
    } else {
      out += `<div class="tool-section"><div class="tool-section-title">上下文里的客户端工具</div><div class="tool-empty">无（这条请求只带了网关工具）。</div></div>`
    }

    return out
  }

  if (tab === 'upstream') {
    const fullPayload = round?.upstream_payload || detail.upstream_payload
    if (fullPayload) return esc(JSON.stringify(fullPayload, null, 2))
    const payloadSummary = round?.upstream_payload_summary || detail.upstream_payload_summary || null
    return esc(JSON.stringify({
      note: '未保留完整 Upstream payload；下方缓存结构不含消息正文。',
      prompt_cache: round?.prompt_cache || detail.prompt_cache || null,
      upstream_payload_summary: payloadSummary,
      upstream_response_evidence: round?.upstream_response_evidence || detail.upstream_response_evidence || null,
    }, null, 2))
  }

  if (tab === 'response') {
    let parts: string[] = []
    parts.push(`状态: ${detail.status}`)
    parts.push(`耗时: ${round ? roundDuration(detail, round) : detail.duration_ms}ms`)
    parts.push(`模型: ${detail.model}`)
    parts.push(`上游: ${detail.upstream_url}`)
    if (detail.stream) parts.push('流式')
    const responseEvidence = responseEvidenceText(
      round?.upstream_response_evidence || detail.upstream_response_evidence,
    )
    if (round?.anthropic_thinking?.preserved) {
      const thinking = round.anthropic_thinking
      parts.push(`Thinking 已保留 ${thinking.blocks || 0} 块${thinking.signature_present ? ' · signature ✓' : ''}${thinking.redacted_present ? ' · redacted ✓' : ''}`)
    }
    let html = parts.join(' · ') + '\n\n'
    if (responseEvidence) html += responseEvidence + '\n\n'
    const responseText = round
      ? (round.response_full ?? round.response_preview)
      : (detail.response_full ?? detail.response_preview)
    if (detail.error) {
      html += esc(detail.error)
    } else if (responseText) {
      html += esc(responseText)
    } else {
      html += '(流式请求无预览 / 无响应)'
    }
    return html
  }

  if (tab === 'meta') {
    return esc(JSON.stringify({
      id: detail.id,
      request_id: detail.request_id,
      timestamp: detail.timestamp,
      model: detail.model,
      stream: detail.stream,
      session_tag: detail.session_tag,
      is_first_turn: detail.is_first_turn,
      original_messages_count: detail.original_messages_count,
      prepared_messages_count: detail.prepared_messages_count,
      tools_count: detail.tools_count,
      has_internal_tools: detail.has_internal_tools,
      request_payloads_retained: detail.request_payloads_retained,
      system_additions_chars: detail.system_additions_chars,
      upstream_payload_summary: detail.upstream_payload_summary,
      upstream_response_evidence: detail.upstream_response_evidence,
      upstream_url: detail.upstream_url,
      status: detail.status,
      duration_ms: detail.duration_ms,
      error: detail.error,
    }, null, 2))
  }

  if (tab === 'raw') {
    return esc(JSON.stringify(round || detail, null, 2))
  }

  return ''
}
</script>

<template>
  <div class="logs-page" data-testid="page-logs">
    <div class="controls">
      <label class="auto-label">
        <input v-model="autoRefresh" type="checkbox" style="accent-color:#8b5cf6" @change="toggleAuto">
        自动刷新
      </label>
      <NButton size="tiny" :loading="loading" @click="loadLogs">刷新</NButton>
      <NButton size="tiny" @click="collapseAll">收起全部</NButton>
      <span class="count">{{ logs.length }} 条</span>
    </div>

    <div v-if="!logs.length" class="empty-box">
      <NEmpty description="等待请求..." />
    </div>

    <div v-for="log in logs" :key="log.id" class="request-group" :class="{ 'has-rounds': displayRounds(log).length > 1 }">
      <div v-if="displayRounds(log).length > 1" class="request-group-label">
        <span>一次工具往返</span>
        <span>{{ displayRounds(log).length }} 轮慢慢接上</span>
      </div>

      <template v-for="(round, roundIndex) in displayRounds(log)" :key="roundKey(log.id, round)">
        <div
          class="log-card"
          :class="roundTone(log, round, roundIndex, displayRounds(log))"
          :data-testid="`log-card-${log.id}-round-${round.round}`"
        >
          <div
            class="log-sum"
            :data-testid="`log-summary-${log.id}-round-${round.round}`"
            @click="toggleDetail(log.id, round)"
          >
            <span class="lt">{{ roundTime(log, round) }}</span>
            <NTag size="tiny" :bordered="false" class="tag-m">{{ log.client_model || log.model || '?' }}</NTag>
            <NTag v-if="displayRounds(log).length > 1" size="tiny" :bordered="false" class="tag-round">
              {{ round.final === true || roundIndex === displayRounds(log).length - 1 ? '最后一轮' : `中间第 ${round.round} 轮` }}
            </NTag>
            <NTag v-if="log.model_mapped" size="tiny" :bordered="false" class="tag-d">→ {{ log.upstream_model || '?' }}</NTag>
            <NTag v-if="log.is_first_turn && roundIndex === 0" size="tiny" :bordered="false" class="tag-f">首轮</NTag>
            <NTag v-if="log.stream" size="tiny" :bordered="false" class="tag-s">流式</NTag>
            <NTag v-if="round.tools?.length" size="tiny" :bordered="false" class="tag-t">{{ round.tools.length }} 次工具</NTag>
            <NTag size="tiny" :bordered="false" class="tag-d">{{ roundDuration(log, round) }}ms</NTag>
            <NTag v-if="totalInputLabel(log, round)" size="tiny" :bordered="false" class="tag-tok">{{ totalInputLabel(log, round) }}</NTag>
            <NTag
              v-if="cacheLabel(log, round)"
              size="tiny"
              :bordered="false"
              class="tag-cache"
              :title="cacheTitle(log, round)"
            >{{ cacheLabel(log, round) }}</NTag>
            <span v-if="roundIndex === 0" class="msg-count">{{ log.original_messages_count }}→{{ log.prepared_messages_count }}</span>
            <span class="arrow" :class="{ open: expIds.has(roundKey(log.id, round)) }">▶</span>
          </div>

          <div v-if="expIds.has(roundKey(log.id, round))" class="det open">
            <div class="dtabs">
              <div
                v-for="tab in TAB_NAMES"
                :key="tab"
                class="dtab"
                :class="{ active: aTabs[roundKey(log.id, round)] === tab }"
                :data-testid="`log-tab-${tab}-${log.id}-round-${round.round}`"
                @click="switchTab(log.id, tab, round)"
              >
                {{ TAB_LABELS[tab] }}
              </div>
            </div>
            <div class="dcont">
              <div v-if="loadingDet.has(log.id)" class="loading-soft">正在把这一轮的细节找回来…</div>
              <div
                v-else-if="detCache[log.id]"
                class="rendered-detail"
                :data-testid="`log-detail-${log.id}-round-${round.round}`"
                v-html="renderContent(detCache[log.id], aTabs[roundKey(log.id, round)] || 'response', round.round)"
              ></div>
              <div v-else class="loading-soft">点开后就能看到这一轮。</div>
            </div>
          </div>
        </div>

        <div v-if="roundIndex < displayRounds(log).length - 1" class="round-bridge">
          <span class="round-bridge-dot">⌁</span>
          <span>{{ round.tools?.length ? '工具已经做好，带着结果继续往下说' : '这一轮还没说完，继续往下走' }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.logs-page {
  max-width: 960px;
  margin: 0 auto;
}

.controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.controls label,
.count {
  font-size: 12px;
  color: #999;
}

.auto-label {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.count {
  margin-left: auto;
}

.empty-box {
  padding: 50px 0;
}

.log-card {
  background: var(--sy-paper, #fff);
  border: 1px solid var(--sy-hair-2);
  border-radius: 8px;
  margin-bottom: 6px;
  overflow: hidden;
}

.request-group {
  margin-bottom: 10px;
}

.request-group.has-rounds {
  padding: 8px;
  border: 1px solid #eee5e9;
  border-radius: 13px;
  background: linear-gradient(180deg, #fffafb 0%, #fff 100%);
}

.request-group-label {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 1px 5px 8px;
  color: #a28f99;
  font-size: 10px;
}

.log-card.intermediate {
  border-left: 3px solid #d7a5ba;
  background: #fffafb;
}

.log-card.error {
  border-left: 3px solid #e53e3e;
}

.log-card.ok {
  border-left: 3px solid #22c55e;
}

.log-card.streaming {
  border-left: 3px solid var(--sy-accent);
}

.log-card.pending {
  border-left: 3px solid #d97706;
}

.log-sum {
  padding: 8px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
  flex-wrap: wrap;
}

.log-sum :deep(.n-tag) {
  flex: 0 0 auto;
  white-space: nowrap;
  word-break: keep-all;
}

:deep(.tag-round) {
  color: #956d80;
  background: #f9eaf1;
}

.log-sum:hover {
  background: var(--sy-paper, #fafafa);
}

.lt {
  font-family: 'SF Mono', monospace;
  color: #999;
  font-size: 11px;
}

.msg-count {
  color: #bbb;
  font-size: 11px;
}

:deep(.tag-tok) {
  color: #6b7280;
  background: var(--sy-sys-surface);
}

:deep(.tag-cache) {
  color: #15803d;
  background: #ecfdf3;
}

.arrow {
  color: #bbb;
  font-size: 9px;
  margin-left: auto;
  transition: 0.2s;
}

.arrow.open {
  transform: rotate(90deg);
}

.det {
  border-top: 1px solid var(--sy-hair-2);
}

.dtabs {
  display: flex;
  gap: 2px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  -webkit-overflow-scrolling: touch;
  border-bottom: 1px solid var(--sy-hair-2);
  background: var(--sy-paper, #fafafa);
}

.dtab {
  flex: 0 0 auto;
  min-width: max-content;
  padding: 7px 12px;
  font-size: 11px;
  color: #999;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  word-break: keep-all;
  writing-mode: horizontal-tb;
}

.dtab.active {
  color: var(--sy-rose-d);
  border-bottom-color: var(--sy-accent);
}

.dcont {
  padding: 10px 14px;
  max-height: 600px;
  overflow-y: auto;
}

.rendered-detail {
  background: var(--sy-paper, #fafafa);
  border: 1px solid var(--sy-hair-2);
  border-radius: 6px;
  padding: 10px;
  font-size: 11px;
  font-family: system-ui, -apple-system, 'Segoe UI', 'Noto Sans SC', sans-serif;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: normal;
  color: var(--sy-ink);
}

.round-bridge {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 30px;
  color: #a48f9a;
  font-size: 10px;
}

.round-bridge::before,
.round-bridge::after {
  content: '';
  width: 42px;
  height: 1px;
  background: linear-gradient(90deg, transparent, #ead7e0);
}

.round-bridge::after {
  background: linear-gradient(90deg, #ead7e0, transparent);
}

.round-bridge-dot {
  color: #c294a9;
  font-size: 15px;
}

.loading-soft {
  padding: 14px;
  color: #9d9298;
  font-size: 11px;
}

@media (max-width: 680px) {
  .logs-page { padding: 0 2px; }
  .request-group.has-rounds { padding: 6px; }
  .log-sum { gap: 6px; padding: 9px 10px; }
  .msg-count { order: 20; }
  .arrow { order: 30; }
  .dtab { padding: 7px 10px; }
  .dcont { padding: 9px; }
  .rendered-detail { padding: 8px; }
  .round-bridge::before, .round-bridge::after { width: 18px; }
}
</style>

<style>
/* global detail styles — unscoped so innerHTML rendering works */
.mb {
  margin-bottom: 6px;
  border-radius: 6px;
  overflow: hidden;
}

.mr {
  padding: 3px 10px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.mr.system {
  background: var(--sy-rose-soft);
  color: var(--sy-rose-d);
}

.mr.user {
  background: #eff6ff;
  color: #2563eb;
}

.mr.assistant {
  background: #f0fdf4;
  color: #16a34a;
}

.mr.tool {
  background: #fffbeb;
  color: #d97706;
}

.mc {
  padding: 6px 10px;
  background: var(--sy-paper, #fafafa);
  font-size: 11px;
  font-family: 'SF Mono', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  border: 1px solid var(--sy-hair-2);
  border-top: 0;
  max-height: 300px;
  overflow-y: auto;
  color: var(--sy-ink);
}

.rev-meta {
  padding: 0 10px 6px;
  background: var(--sy-paper, #fafafa);
  border: 1px solid var(--sy-hair-2);
  border-top: 0;
  color: #6b7280;
  font-size: 10px;
}

.tc-block {
  background: var(--sy-paper, #fafafa);
  border: 1px solid var(--sy-hair-2);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
}

.tc-name {
  font-size: 11px;
  font-weight: 600;
  color: #0891b2;
  margin-bottom: 4px;
}

.tc-args {
  font-size: 11px;
  color: var(--sy-ink);
  font-family: 'SF Mono', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.island-hero { display:flex; align-items:center; gap:13px; padding:15px 16px; border-radius:12px; margin-bottom:10px; }
.island-calm { background:linear-gradient(135deg,#f7fbf8,#f3f8f5); border:1px solid #dcebe1; }
.island-changed { background:linear-gradient(135deg,#fff7fa,#faf2f6); border:1px solid #efdce5; }
.island-orb { width:38px; height:38px; display:grid; place-items:center; flex:0 0 auto; border-radius:50%; color:var(--sy-rose-d); background:rgba(255,255,255,.78); box-shadow:0 4px 14px rgba(91,68,82,.08); font-size:18px; }
.island-hero-title { color:#493e45; font-family:Georgia,'Noto Serif SC',serif; font-size:15px; font-weight:700; }
.island-hero-sub { margin-top:3px; color:#8d8188; font-size:11px; }
.soft-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; }
.soft-card { padding:11px 12px; border:1px solid #ece7ea; border-radius:10px; background:var(--sy-paper, #fff); }
.soft-label,.round-small-title { color:#aa929f; font-size:10px; font-weight:700; letter-spacing:.04em; }
.soft-value { margin-top:4px; color:#4f444b; font-size:12px; font-weight:650; }
.soft-note,.soft-footnote { margin-top:3px; color:#948990; font-size:10px; line-height:1.55; }
.island-section { margin-top:10px; padding:12px; border:1px solid #eee9ec; border-radius:11px; background:#fff; }
.island-section-title { margin-bottom:8px; color:#725e69; font-family:Georgia,'Noto Serif SC',serif; font-size:12px; font-weight:700; }
.island-content { max-height:380px; overflow-y:auto; padding:12px 13px; border-radius:8px; color:#51484d; background:#fcfaf8; box-shadow:inset 0 0 0 1px #f0ebe6; font-family:'Noto Serif SC',Georgia,serif; font-size:11px; line-height:1.75; white-space:pre-wrap; word-break:break-word; }
.island-lanes { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:10px; }
.island-lane { min-width:0; padding:12px; border:1px solid #eee7eb; border-radius:10px; background:var(--sy-paper, #fff); }
.island-lane-head { display:flex; justify-content:space-between; align-items:center; gap:10px; }
.island-lane-title { display:flex; align-items:center; gap:6px; color:#5e4d56; font-family:Georgia,'Noto Serif SC',serif; font-size:13px; font-weight:700; }
.island-lane-count { color:#9a8e94; font-size:9px; white-space:nowrap; }
.count-added { color:#2f8a58; }.count-updated { color:#9b6b9e; }.count-removed { color:#bc6268; }
.island-current-title,.island-change-title { margin:11px 0 6px; color:#a18e98; font-size:9px; font-weight:700; letter-spacing:.04em; }
.change-updated { color:#946c99; }.change-removed { color:#b86b70; }
.island-memory-list { display:grid; gap:6px; }
.island-memory-item { padding:8px 9px; border:1px solid #eee9eb; border-radius:8px; background:#fff; }
.memory-item-top { display:flex; justify-content:space-between; gap:6px; min-height:14px; }
.memory-item-label { color:#9a7e8c; font-size:9px; font-weight:700; }
.memory-change-label { font-size:9px; font-weight:700; }
.memory-item-text { color:#51474c; font-family:'Noto Serif SC',Georgia,serif; font-size:10px; line-height:1.6; word-break:break-word; }
.memory-added { border-color:#cfe8d7; background:#f4fbf6; }.memory-added .memory-change-label { color:#2e8b57; }
.memory-updated { border-color:#e4d4e7; background:#fbf6fc; }.memory-updated .memory-change-label { color:#94659a; }
.memory-before { border-color:#e6e0e3; background:#faf8f9; opacity:.86; }.memory-before .memory-change-label { color:#907f87; }
.memory-removed { border-color:#eed5d7; background:#fff7f7; opacity:.82; }.memory-removed .memory-change-label { color:#b7555d; }.memory-removed .memory-item-text { color:#9d7074; text-decoration:line-through; }
.memory-update-pair { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:6px; }
.memory-update-arrow { color:#b69aaa; font-size:12px; }
.cache-raw { display:flex; flex-wrap:wrap; gap:7px; }
.cache-raw span { padding:5px 9px; border-radius:999px; color:#49705a; background:#edf7f0; font-size:10px; }
.empty-soft,.muted { color:#a1999e; font-size:11px; line-height:1.65; }
.story-round { position:relative; padding:14px; border-radius:12px; margin-bottom:10px; overflow:hidden; }
.story-round::before { content:''; position:absolute; inset:0 auto 0 0; width:4px; }
.round-middle { background:linear-gradient(145deg,#fff8fb,var(--sy-paper, #fff)); border:1px solid #efdde6; }
.round-middle::before { background:#d9a8bd; }
.round-final { background:linear-gradient(145deg,#f7fcf8,#fff); border:1px solid #d8eadc; }
.round-final::before { background:#85b794; }
.story-round-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }
.story-round-kicker { color:#a88c9a; font-size:10px; font-weight:700; }
.story-round-title { margin-top:2px; color:#50444b; font-family:Georgia,'Noto Serif SC',serif; font-size:13px; font-weight:700; }
.story-round-time { color:#aaa0a5; font-family:'SF Mono',monospace; font-size:10px; }
.story-round-response { max-height:360px; overflow-y:auto; padding:11px 12px; border-radius:8px; color:#40383c; background:rgba(255,255,255,.75); font-size:11px; line-height:1.7; white-space:pre-wrap; word-break:break-word; }
.round-tool-list { margin-top:9px; padding:9px 10px; border-radius:8px; background:rgba(255,255,255,.62); }
.round-tool { display:flex; justify-content:space-between; align-items:baseline; gap:10px; padding-top:6px; color:#5f5058; font-size:10px; }
.round-tool-icon { color:#bc8ea4; margin-right:5px; }
.round-tool-hint { color:#9f9299; margin-left:7px; }
.round-tool-result { color:#558267; white-space:nowrap; }
.round-tool-result.failed { color:#b65f65; }
.story-round-foot { display:flex; flex-wrap:wrap; justify-content:space-between; gap:6px 12px; margin-top:9px; color:#a0979c; font-size:9px; }

/* tools tab: 工具名清单 + 调用记录 + 客户端工具 */
.tools-list {
  white-space: pre-wrap;
  word-break: break-all;
}

.tool-section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e0e0e0;
}

.tool-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--sy-rose-d);
  margin-bottom: 6px;
}

.tool-call-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 0;
  font-size: 11px;
  line-height: 1.5;
}

.tc-call-name {
  font-weight: 600;
  color: #0891b2;
  font-family: 'SF Mono', monospace;
}

.tc-call-hint {
  color: #4b5563;
}

.tc-cached {
  color: var(--sy-mute);
  font-size: 10px;
}

.tool-empty {
  font-size: 11px;
  color: var(--sy-mute);
}

.tool-round-group {
  margin-bottom: 4px;
}

.tool-round-group + .tool-round-group {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dotted #e0e0e0;
}

.tool-round-header {
  font-size: 10px;
  font-weight: 600;
  color: var(--sy-mute);
  margin-bottom: 4px;
}

.tool-call-item {
  padding: 4px 0;
}

.tool-call-item + .tool-call-item {
  border-top: 1px solid var(--sy-sys-surface);
}

.tool-detail-block {
  margin: 3px 0 3px 20px;
  padding: 4px 8px;
  font-size: 10px;
  font-family: 'SF Mono', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  color: #374151;
  background: #f9fafb;
  border-left: 2px solid #e5e7eb;
  border-radius: 0 4px 4px 0;
  max-height: 120px;
  overflow-y: auto;
}

.tool-detail-block.tool-ok {
  border-left-color: #22c55e;
}

.tool-detail-block.tool-fail {
  border-left-color: #ef4444;
  background: #fef2f2;
}

.tool-target {
  font-size: 10px;
  color: #7c3aed;
  font-weight: 500;
}

.tool-timing {
  font-size: 10px;
  color: var(--sy-mute);
  font-family: 'SF Mono', monospace;
}
</style>
