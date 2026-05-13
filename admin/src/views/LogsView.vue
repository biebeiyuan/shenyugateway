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

const TAB_NAMES = ['system', 'messages', 'upstream', 'tools', 'response', 'meta', 'raw'] as const
const TAB_LABELS: Record<string, string> = {
  system: 'System', messages: 'Messages', upstream: 'Upstream',
  tools: 'Tools', response: 'Response', meta: 'Meta', raw: 'Raw JSON',
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

async function toggleDetail(id: string) {
  if (expIds.value.has(id)) {
    expIds.value.delete(id)
    delete detCache.value[id]
  } else {
    expIds.value.add(id)
    aTabs.value[id] = aTabs.value[id] || 'system'
    loadDetailTab(id, aTabs.value[id])
  }
}

async function loadDetailTab(id: string, tab: string) {
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
    loadDetailTab(id, tab)
  }
}

function collapseAll() {
  expIds.value.clear()
  detCache.value = {}
}

function renderContent(detail: LogDetail, tab: string): string {
  if (tab === 'system') {
    const full = detail.system_additions_full || detail.system_additions_preview || '(无)'
    return esc(full)
  }

  if (tab === 'messages') {
    const msgs = detail.prepared_messages || []
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
    const names = detail.tool_names || []
    if (!names.length) return '(无工具)'
    let html = names.map((n, i) => `${i + 1}. ${n}`).join('\n')
    html += `\n\n总计 ${names.length} 个工具`
    if (detail.has_internal_tools) html += '\n含内部工具'
    return esc(html)
  }

  if (tab === 'upstream') {
    const payload = detail.upstream_payload || {
      note: 'No upstream payload was captured for this log. New requests will include it.',
      prepared_messages: detail.prepared_messages || [],
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
    if (detail.error) {
      html += esc(detail.error)
    } else if (detail.response_preview) {
      html += esc(detail.response_preview)
    } else {
      html += '(流式请求无预览 / 无响应)'
    }
    return html
  }

  if (tab === 'meta') {
    return esc(JSON.stringify({
      id: detail.id,
      timestamp: detail.timestamp,
      model: detail.model,
      stream: detail.stream,
      session_tag: detail.session_tag,
      is_first_turn: detail.is_first_turn,
      original_messages_count: detail.original_messages_count,
      prepared_messages_count: detail.prepared_messages_count,
      tools_count: detail.tools_count,
      has_internal_tools: detail.has_internal_tools,
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
        <NTag size="tiny" :bordered="false" :class="log.status === 'error' ? 'tag-e' : 'tag-ok'">{{ log.status }}</NTag>
        <NTag size="tiny" :bordered="false" class="tag-d">{{ log.duration_ms }}ms</NTag>
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
          <pre v-else-if="detCache[log.id]" v-html="renderContent(detCache[log.id], aTabs[log.id] || 'system')"></pre>
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
  border-left: 3px solid #3b82f6;
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
  color: #4f46e5;
  border-bottom-color: #4f46e5;
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
  background: #eef2ff;
  color: #4f46e5;
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
</style>
