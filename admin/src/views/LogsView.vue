<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { NButton, NEmpty, NTag, useMessage } from 'naive-ui'
import { fetchLogs, fetchLogDetail, type LogEntry, type LogDetail } from '@/api/logs'

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
  shenyu_conflict_list: '看矛盾书书架',
  shenyu_conflict_read: '翻开一本矛盾书',
  shenyu_conflict_annotate: '在矛盾书里批注',
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
  room_conflict_shelf: '翻矛盾书架',
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

const TAB_NAMES = ['overview', 'rounds', 'tools', 'messages', 'system', 'response', 'upstream', 'meta', 'raw'] as const
const TAB_LABELS: Record<string, string> = {
  overview: '概览', rounds: '上游轮次', tools: '工具执行', messages: 'Messages',
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
  if (status === 'error') return 'error'
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

// 从 usage 里取总 token 数，兼容 OpenAI / Anthropic 两种字段
function totalTokens(log: LogEntry): number | null {
  const u = log.usage
  if (!u || typeof u !== 'object') return null
  const total = u.total_tokens
  if (typeof total === 'number' && total > 0) return total
  const inTok = u.prompt_tokens ?? u.input_tokens
  const outTok = u.completion_tokens ?? u.output_tokens
  const sum = (typeof inTok === 'number' ? inTok : 0) + (typeof outTok === 'number' ? outTok : 0)
  return sum > 0 ? sum : null
}

function tokenLabel(log: LogEntry): string {
  const t = totalTokens(log)
  return t === null ? '' : `${fmtNum(t)} tok`
}

function cacheLabel(log: LogEntry): string {
  const cache = log.cache_usage
  if (!cache?.hit) return ''
  const read = Number(cache.cache_read_input_tokens) || 0
  return read > 0 ? `⚡ ${fmtNum(read)} cached` : '⚡ cached'
}

function cacheTitle(log: LogEntry): string {
  const cache = log.cache_usage
  if (!cache?.hit) return ''
  const read = Number(cache.cache_read_input_tokens) || 0
  const write = Number(cache.cache_creation_input_tokens) || 0
  return `供应商上报缓存读取 ${read.toLocaleString()} tokens · 写入 ${write.toLocaleString()} tokens。这里只保留原始数值，不推算费用。`
}

async function toggleDetail(id: string) {
  if (expIds.value.has(id)) {
    expIds.value.delete(id)
    delete detCache.value[id]
  } else {
    expIds.value.add(id)
    aTabs.value[id] = aTabs.value[id] || 'overview'
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

function switchTab(id: string, tab: string) {
  aTabs.value[id] = tab
  if (!detCache.value[id]) {
    loadDetailTab(id)
  }
}

function collapseAll() {
  expIds.value.clear()
  detCache.value = {}
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
    empty_transition: '内容从有到无，或从无到有',
    forced: '这次被明确要求重新整理',
    proposal_applied: '采用了本次召回结果',
  }
  return labels[key] || key || '没有额外原因'
}

function islandRenderedText(detail: LogDetail): string {
  return String(detail.memory_island_content?.rendered_text || '').trim()
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
    ? '实际送给模型的记忆内容有变化，下面可以直接看到。'
    : '这次沿用了上一轮的小岛，没有重新搬动。'

  let html = `<div class="island-hero ${islandTone}"><div class="island-orb">${changed ? '✦' : '◌'}</div><div><div class="island-hero-title">${islandTitle}</div><div class="island-hero-sub">${islandSubtitle}</div></div></div>`
  html += '<div class="soft-grid">'
  html += `<div class="soft-card"><div class="soft-label">星星</div><div class="soft-value">${decisionText(star.decision)}</div><div class="soft-note">${reasonText(star.reason)}${typeof star.overlap === 'number' ? ` · 重合 ${(star.overlap * 100).toFixed(0)}%` : ''}</div></div>`
  html += `<div class="soft-card"><div class="soft-label">Mem</div><div class="soft-value">${decisionText(mem.decision)}</div><div class="soft-note">${reasonText(mem.reason)}${typeof mem.overlap === 'number' ? ` · 重合 ${(mem.overlap * 100).toFixed(0)}%` : ''}</div></div>`
  html += `<div class="soft-card"><div class="soft-label">这座小岛</div><div class="soft-value">${content?.star_count ?? star.chosen_count ?? 0} 颗星 · ${content?.mem_count ?? mem.chosen_count ?? 0} 条 Mem</div><div class="soft-note">${esc(content?.version || detail.memory_island_version || '版本未记录')}</div></div>`
  html += '</div>'

  const rendered = islandRenderedText(detail)
  html += '<div class="island-section"><div class="island-section-title">这次真正送过去的小岛</div>'
  html += rendered
    ? `<div class="island-content">${esc(rendered)}</div>`
    : '<div class="empty-soft">这条旧日志没有单独保存小岛正文，可以去 System 里看完整上下文。</div>'
  html += '</div>'

  html += '<div class="island-section"><div class="island-section-title">缓存留下的原始回声</div>'
  if (!detail.prompt_cache?.enabled) {
    html += '<div class="empty-soft">这次没有启用 prompt cache。</div>'
  } else if (cache?.hit) {
    html += `<div class="cache-raw"><span>读取 ${Number(cache.cache_read_input_tokens || 0).toLocaleString()}</span><span>写入 ${Number(cache.cache_creation_input_tokens || 0).toLocaleString()}</span><span>${cache.rounds || 1} 轮</span></div>`
    html += '<div class="soft-footnote">这些是供应商原样返回的 token 数。它们可以帮助对照，但这里不再猜测缓存比例或实际账单。</div>'
  } else {
    html += '<div class="empty-soft">供应商没有报告缓存命中。这不一定等于没有任何内部缓存，只代表这次 API usage 没有给出 cached tokens。</div>'
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

function renderRounds(detail: LogDetail): string {
  const rounds = Array.isArray(detail.internal_tool_rounds) ? detail.internal_tool_rounds : []
  if (!rounds.length) return '<div class="empty-soft">这是一条普通的单轮回复，没有额外的工具往返。最终内容可以直接去 Response 看。</div>'
  return rounds.map((round, index) => {
    const isFinal = round.final === true || index === rounds.length - 1
    const usage = round.usage || {}
    const cached = usageCacheRead(usage)
    const response = String(round.response_full || round.response_preview || '').trim()
    const tone = isFinal ? 'round-final' : 'round-middle'
    const label = isFinal ? '最后一轮' : `中间第 ${round.round} 轮`
    const cacheText = cached > 0 ? `供应商报了 ${cached.toLocaleString()} cached` : '没有 cached 数值'
    return `<div class="story-round ${tone}"><div class="story-round-head"><div><span class="story-round-kicker">${label}</span><div class="story-round-title">${finishText(round.finish_reason, isFinal)}</div></div><div class="story-round-time">${typeof round.upstream_duration_ms === 'number' ? `${(round.upstream_duration_ms / 1000).toFixed(1)}s` : ''}</div></div><div class="story-round-response">${response ? esc(response) : '<span class="muted">这条旧日志没有保存这一轮的正文。</span>'}</div>${renderRoundTools(round)}<div class="story-round-foot"><span>${cacheText}</span><span>输入 ${usageInput(usage).toLocaleString()} · 输出 ${usageOutput(usage).toLocaleString()}</span></div></div>`
  }).join('')
}

function renderContent(detail: LogDetail, tab: string): string {
  if (tab === 'overview') return renderOverview(detail)
  if (tab === 'rounds') return renderRounds(detail)
  if (tab === 'system') {
    const full = detail.system_additions_full || detail.system_additions_preview || '(无)'
    return esc(full)
  }

  if (tab === 'messages') {
    const msgs = detail.prepared_messages || []
    const previews = detail.prepared_messages_preview || []
    if (!msgs.length && previews.length) {
      return previews.map((m: any) => {
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
    const payload = detail.upstream_payload || detail.upstream_payload_summary || {
      note: 'Full upstream payload is not retained. Set GATEWAY_LOG_FULL_PAYLOADS=true to keep full debug payloads in memory.',
    }
    return esc(JSON.stringify(payload, null, 2))
  }

  if (tab === 'response') {
    let parts: string[] = []
    parts.push(`状态: ${detail.status}`)
    parts.push(`耗时: ${detail.duration_ms}ms`)
    parts.push(`模型: ${detail.model}`)
    parts.push(`上游: ${detail.upstream_url}`)
    if (detail.stream) parts.push('流式')
    let html = parts.join(' · ') + '\n\n'
    const responseText = detail.response_full ?? detail.response_preview
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
      upstream_url: detail.upstream_url,
      status: detail.status,
      duration_ms: detail.duration_ms,
      error: detail.error,
    }, null, 2))
  }

  if (tab === 'raw') {
    return esc(JSON.stringify(detail, null, 2))
  }

  return ''
}
</script>

<template>
  <div class="logs-page">
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

    <div v-for="log in logs" :key="log.id" class="log-card" :class="clsName(log.status)">
      <div class="log-sum" @click="toggleDetail(log.id)">
        <span class="lt">{{ timeStr(log.timestamp) }}</span>
        <NTag size="tiny" :bordered="false" class="tag-m">{{ log.client_model || log.model || '?' }}</NTag>
        <NTag v-if="log.model_mapped" size="tiny" :bordered="false" class="tag-d">→ {{ log.upstream_model || '?' }}</NTag>
        <NTag v-if="log.is_first_turn" size="tiny" :bordered="false" class="tag-f">首轮</NTag>
        <NTag v-if="log.stream" size="tiny" :bordered="false" class="tag-s">流式</NTag>
        <NTag v-if="log.tools_count" size="tiny" :bordered="false" class="tag-t">{{ log.tools_count }} tools</NTag>
        <NTag size="tiny" :bordered="false" class="tag-d">{{ log.duration_ms }}ms</NTag>
        <NTag v-if="tokenLabel(log)" size="tiny" :bordered="false" class="tag-tok">{{ tokenLabel(log) }}</NTag>
        <NTag
          v-if="cacheLabel(log)"
          size="tiny"
          :bordered="false"
          class="tag-cache"
          :title="cacheTitle(log)"
        >{{ cacheLabel(log) }}</NTag>
        <span class="msg-count">{{ log.original_messages_count }}→{{ log.prepared_messages_count }}</span>
        <span class="arrow" :class="{ open: expIds.has(log.id) }">▶</span>
      </div>

      <div v-if="expIds.has(log.id)" class="det open">
        <div class="dtabs">
          <div
            v-for="tab in TAB_NAMES"
            :key="tab"
            class="dtab"
            :class="{ active: aTabs[log.id] === tab }"
            @click="switchTab(log.id, tab)"
          >
            {{ TAB_LABELS[tab] }}
          </div>
        </div>
        <div class="dcont">
          <div v-if="loadingDet.has(log.id)" style="color:#484f58;font-size:11px">加载中...</div>
          <div v-else-if="detCache[log.id]" class="rendered-detail" v-html="renderContent(detCache[log.id], aTabs[log.id] || 'overview')"></div>
          <div v-else style="color:#484f58;font-size:11px">点击标签加载</div>
        </div>
      </div>
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
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  margin-bottom: 6px;
  overflow: hidden;
}

.log-card.error {
  border-left: 3px solid #e53e3e;
}

.log-card.ok {
  border-left: 3px solid #22c55e;
}

.log-card.streaming {
  border-left: 3px solid #c094a8;
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

.log-sum:hover {
  background: #fafafa;
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
  background: #f3f4f6;
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
  border-top: 1px solid #e8e8e8;
}

.dtabs {
  display: flex;
  border-bottom: 1px solid #e8e8e8;
  background: #fafafa;
}

.dtab {
  padding: 6px 14px;
  font-size: 11px;
  color: #999;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}

.dtab.active {
  color: #8b7082;
  border-bottom-color: #c094a8;
}

.dcont {
  padding: 10px 14px;
  max-height: 600px;
  overflow-y: auto;
}

.rendered-detail {
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 10px;
  font-size: 11px;
  font-family: 'SF Mono', monospace;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: #1f1f1f;
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
  background: #faf0ee;
  color: #8b7082;
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
  background: #fafafa;
  font-size: 11px;
  font-family: 'SF Mono', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  border: 1px solid #e8e8e8;
  border-top: 0;
  max-height: 300px;
  overflow-y: auto;
  color: #1f1f1f;
}

.rev-meta {
  padding: 0 10px 6px;
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-top: 0;
  color: #6b7280;
  font-size: 10px;
}

.tc-block {
  background: #fafafa;
  border: 1px solid #e8e8e8;
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
  color: #1f1f1f;
  font-family: 'SF Mono', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.island-hero { display:flex; align-items:center; gap:13px; padding:15px 16px; border-radius:12px; margin-bottom:10px; }
.island-calm { background:linear-gradient(135deg,#f7fbf8,#f3f8f5); border:1px solid #dcebe1; }
.island-changed { background:linear-gradient(135deg,#fff7fa,#faf2f6); border:1px solid #efdce5; }
.island-orb { width:38px; height:38px; display:grid; place-items:center; flex:0 0 auto; border-radius:50%; color:#8b7082; background:rgba(255,255,255,.78); box-shadow:0 4px 14px rgba(91,68,82,.08); font-size:18px; }
.island-hero-title { color:#493e45; font-family:Georgia,'Noto Serif SC',serif; font-size:15px; font-weight:700; }
.island-hero-sub { margin-top:3px; color:#8d8188; font-size:11px; }
.soft-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; }
.soft-card { padding:11px 12px; border:1px solid #ece7ea; border-radius:10px; background:#fffdfd; }
.soft-label,.round-small-title { color:#aa929f; font-size:10px; font-weight:700; letter-spacing:.04em; }
.soft-value { margin-top:4px; color:#4f444b; font-size:12px; font-weight:650; }
.soft-note,.soft-footnote { margin-top:3px; color:#948990; font-size:10px; line-height:1.55; }
.island-section { margin-top:10px; padding:12px; border:1px solid #eee9ec; border-radius:11px; background:#fff; }
.island-section-title { margin-bottom:8px; color:#725e69; font-family:Georgia,'Noto Serif SC',serif; font-size:12px; font-weight:700; }
.island-content { max-height:380px; overflow-y:auto; padding:12px 13px; border-radius:8px; color:#51484d; background:#fcfaf8; box-shadow:inset 0 0 0 1px #f0ebe6; font-family:'Noto Serif SC',Georgia,serif; font-size:11px; line-height:1.75; white-space:pre-wrap; word-break:break-word; }
.cache-raw { display:flex; flex-wrap:wrap; gap:7px; }
.cache-raw span { padding:5px 9px; border-radius:999px; color:#49705a; background:#edf7f0; font-size:10px; }
.empty-soft,.muted { color:#a1999e; font-size:11px; line-height:1.65; }
.story-round { position:relative; padding:14px; border-radius:12px; margin-bottom:10px; overflow:hidden; }
.story-round::before { content:''; position:absolute; inset:0 auto 0 0; width:4px; }
.round-middle { background:linear-gradient(145deg,#fff8fb,#fffdfd); border:1px solid #efdde6; }
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
  color: #8b7082;
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
  color: #9ca3af;
  font-size: 10px;
}

.tool-empty {
  font-size: 11px;
  color: #9ca3af;
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
  color: #9ca3af;
  margin-bottom: 4px;
}

.tool-call-item {
  padding: 4px 0;
}

.tool-call-item + .tool-call-item {
  border-top: 1px solid #f3f4f6;
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
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
}
</style>
