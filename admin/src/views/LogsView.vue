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

const TAB_NAMES = ['overview', 'rounds', 'tools', 'messages', 'response', 'system', 'upstream', 'meta', 'raw'] as const
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

function cacheRate(log: LogEntry): number | null {
  const c = log.cache_usage
  const u = log.usage
  if (!c?.hit || !u || typeof u !== 'object') return null

  const read = Number(c.cache_read_input_tokens) || 0
  const write = Number(c.cache_creation_input_tokens) || 0
  const aggregatePrompt = Number(c.reported_input_tokens)
  const hasAggregatePrompt = Number.isFinite(aggregatePrompt) && aggregatePrompt >= 0
  const prompt = hasAggregatePrompt
    ? aggregatePrompt
    : Number(u.prompt_tokens ?? u.input_tokens) || 0
  if (read <= 0) return null

  // 旧版多轮日志只累计了 cache read，却只保留最后一轮 usage，二者不能混算。
  if ((c.rounds || 0) > 1 && !hasAggregatePrompt) return null

  // Anthropic 的 input_tokens 不含 cache read/write；OpenAI 的 prompt_tokens
  // 通常已经包含 cached_tokens。按上游协议区分，避免比例超过 100%。
  const protocol = String(log.prompt_cache?.protocol || '').toLowerCase()
  const totalInput = protocol === 'anthropic'
    ? read + write + prompt
    : (prompt >= read ? prompt : read + write + prompt)
  if (totalInput <= 0) return null
  return Math.min(1, read / totalInput)
}

function fmtRate(rate: number): string {
  const percent = rate * 100
  return percent >= 99.95 ? '100%' : `${percent.toFixed(1)}%`
}

// 命中缓存时返回紧凑的 "⚡ 1.2k · 98.5%"，否则空串
function cacheLabel(log: LogEntry): string {
  const c = log.cache_usage
  if (!c || !c.hit) return ''
  const read = c.cache_read_input_tokens || 0
  if (read <= 0) return '⚡'
  const rate = cacheRate(log)
  return rate === null ? `⚡ ${fmtNum(read)}` : `⚡ ${fmtNum(read)} · ${fmtRate(rate)}`
}

function cacheTitle(log: LogEntry): string {
  const c = log.cache_usage
  if (!c?.hit) return ''
  const read = c.cache_read_input_tokens || 0
  const rate = cacheRate(log)
  const parts = [`命中缓存 ${read.toLocaleString()} tokens`]
  if (rate !== null) parts.push(`缓存覆盖率 ${fmtRate(rate)}（按上游上报的输入 token 计算）`)
  return parts.join(' · ')
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

function roundCacheRate(detail: LogDetail, usage: Record<string, any> | null | undefined): number | null {
  const read = usageCacheRead(usage)
  if (read <= 0) return null
  const input = usageInput(usage)
  const protocol = String(detail.prompt_cache?.protocol || '').toLowerCase()
  const total = protocol === 'anthropic' ? read + input : Math.max(read, input)
  return total > 0 ? read / total : null
}

function messageText(message: any): string {
  if (typeof message?.content === 'string') return message.content
  if (Array.isArray(message?.content)) {
    return message.content.map((block: any) => typeof block === 'string' ? block : block?.text || '').join('\n')
  }
  return ''
}

function suspiciousMarkers(detail: LogDetail): Array<{ index: number; role: string; marker: string }> {
  const messages = detail.prepared_messages || []
  const patterns = [
    /(?:end)?_of_conversation_from_api|end_of_conversation/gi,
  ]
  const found: Array<{ index: number; role: string; marker: string }> = []
  messages.forEach((message: any, index: number) => {
    const text = messageText(message)
    for (const pattern of patterns) {
      pattern.lastIndex = 0
      const match = pattern.exec(text)
      if (match && !found.some((item) => item.index === index && item.marker === match[0])) {
        found.push({ index, role: message.role || '?', marker: match[0] })
      }
    }
  })
  return found
}

function renderOverview(detail: LogDetail): string {
  const window = detail.client_message_window || {}
  const cache = detail.cache_usage
  const markers = suspiciousMarkers(detail)
  const rounds = Array.isArray(detail.internal_tool_rounds) ? detail.internal_tool_rounds : []
  const executed = rounds.reduce((sum, round) => sum + (round.tools?.length || 0), 0)
  const requested = rounds.reduce((sum, round) => sum + (round.gateway_tool_calls?.length || 0), 0)
  const cards = [
    ['请求结果', `${detail.status}${detail.finish_reason ? ` · ${detail.finish_reason}` : ''}`, detail.error ? 'bad' : 'good'],
    ['消息窗口', `${detail.original_messages_count} → ${detail.prepared_messages_count}`, detail.original_messages_count > detail.prepared_messages_count ? 'warn' : ''],
    ['上游轮次', `${rounds.length || Number(detail.internal_tool_rounds || 0) || 1} 轮`, ''],
    ['工具链路', `提供 ${detail.tools_count || 0} · 请求 ${requested} · 执行 ${executed}`, requested > executed ? 'warn' : 'good'],
  ]
  let html = `<div class="diag-grid">${cards.map(([label, value, tone]) => `<div class="diag-card ${tone}"><div class="diag-label">${esc(label)}</div><div class="diag-value">${esc(value)}</div></div>`).join('')}</div>`

  html += '<div class="diag-section"><div class="diag-title">裁剪与上下文</div><div class="diag-lines">'
  html += `<div>原始客户端消息：${detail.original_messages_count}；发送上游：${detail.prepared_messages_count}</div>`
  html += `<div>近期非 system 保留：${window.client_non_system_retained ?? '未知'} / ${window.client_non_system_original ?? '未知'}；人类轮次：${window.human_turn_groups_retained ?? '未知'}</div>`
  html += `<div>事件：${esc(window.event_class || '未知')}；公共前缀：${window.common_prefix_messages ?? '未知'}；工具保护轮次：${window.raw_tool_protection_turns ?? 0}</div>`
  html += `<div>Epoch：${esc(window.context_epoch_id || '未知')}；重置：${window.context_epoch_reset ? `是（${esc(window.context_epoch_reset_reason || '未注明')}）` : '否'}</div>`
  html += '</div></div>'

  html += '<div class="diag-section"><div class="diag-title">缓存诊断</div><div class="diag-lines">'
  if (!detail.prompt_cache?.enabled) {
    html += '<div class="diag-warn">本次未启用 prompt cache。</div>'
  } else if (cache?.hit) {
    const rate = cacheRate(detail)
    html += `<div>协议：${esc(detail.prompt_cache.protocol || '未知')}；TTL：${esc(detail.prompt_cache.ttl || '未知')}</div>`
    html += `<div>上游报告读取：${Number(cache.cache_read_input_tokens || 0).toLocaleString()}；写入：${Number(cache.cache_creation_input_tokens || 0).toLocaleString()}；轮次：${cache.rounds || 1}</div>`
    html += `<div>${rate === null ? '多轮旧日志口径不完整，不展示覆盖率。' : `上游报告覆盖率：${fmtRate(rate)}`}</div>`
  } else {
    html += `<div class="diag-warn">本次未命中缓存；上游报告输入 ${usageInput(detail.usage).toLocaleString()} tokens。</div>`
  }
  html += '</div></div>'

  html += '<div class="diag-section"><div class="diag-title">异常检查</div>'
  if (markers.length) {
    html += `<div class="diag-alert">发现疑似会话控制标记：${markers.map((item) => `messages[${item.index}] ${item.role}: ${item.marker}`).join('；')}。该标记已存在于发送上游的历史消息中，请对比上一请求 response_full 判断来自模型输出还是客户端追加。</div>`
  } else {
    html += '<div class="diag-ok">未在保留消息中发现已知会话结束标记。</div>'
  }
  if (detail.error) html += `<div class="diag-alert">失败信息：${esc(detail.error)}</div>`
  html += '</div>'
  return html
}

function renderRounds(detail: LogDetail): string {
  const rounds = Array.isArray(detail.internal_tool_rounds) ? detail.internal_tool_rounds : []
  if (!rounds.length) return '<div class="tool-empty">该日志没有保留逐轮详情；普通单轮请求请查看 Upstream 与 Response。</div>'
  return rounds.map((round) => {
    const usage = round.usage || {}
    const read = usageCacheRead(usage)
    const rate = roundCacheRate(detail, usage)
    const calls = Number(round.tool_calls_count || 0)
    const executed = round.tools?.length || 0
    const status = round.finish_reason || (calls ? 'tool_calls' : '未知')
    return `<div class="round-card"><div class="round-head"><span>第 ${round.round} 轮</span><span>${round.messages_count} messages</span><span>${round.stream ? '流式' : '非流式'}</span><span>结束：${esc(status)}</span></div><div class="round-metrics"><div>输入 ${usageInput(usage).toLocaleString()}</div><div>输出 ${usageOutput(usage).toLocaleString()}</div><div>缓存读取 ${read.toLocaleString()}</div><div>${rate === null ? '缓存未命中/未知' : `覆盖 ${fmtRate(rate)}`}</div><div>模型工具请求 ${calls}</div><div>网关实际执行 ${executed}</div></div>${round.gateway_tool_calls?.length ? `<div class="round-calls">${round.gateway_tool_calls.map((call) => `🔧 ${esc(call.name || 'unknown')} ${esc(call.arguments_preview || '')}`).join('\n')}</div>` : ''}</div>`
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
          <pre v-else-if="detCache[log.id]" v-html="renderContent(detCache[log.id], aTabs[log.id] || 'overview')"></pre>
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

.dcont pre {
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

.diag-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.diag-card {
  padding: 9px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #fff;
}

.diag-card.good { border-left: 3px solid #22c55e; }
.diag-card.warn { border-left: 3px solid #f59e0b; }
.diag-card.bad { border-left: 3px solid #ef4444; }

.diag-label {
  color: #9ca3af;
  font-size: 10px;
  margin-bottom: 3px;
}

.diag-value {
  color: #1f2937;
  font-size: 12px;
  font-weight: 600;
}

.diag-section {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #fff;
}

.diag-title {
  color: #8b7082;
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 6px;
}

.diag-lines > div {
  padding: 2px 0;
  color: #4b5563;
}

.diag-alert,
.diag-warn,
.diag-ok {
  padding: 7px 9px;
  border-radius: 6px;
  white-space: pre-wrap;
}

.diag-alert {
  color: #991b1b;
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.diag-warn {
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.diag-ok {
  color: #166534;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.round-card {
  padding: 10px;
  margin-bottom: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #fff;
}

.round-head,
.round-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}

.round-head {
  color: #374151;
  font-weight: 600;
  margin-bottom: 7px;
}

.round-metrics {
  color: #6b7280;
}

.round-calls {
  margin-top: 8px;
  padding: 7px 9px;
  border-radius: 6px;
  color: #155e75;
  background: #ecfeff;
  white-space: pre-wrap;
}

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
