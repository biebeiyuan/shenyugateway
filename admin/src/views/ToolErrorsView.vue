<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { fetchToolErrors, type ToolError } from '@/api/toolErrors'

const errors = ref<ToolError[]>([])
const loading = ref(false)
const expandedIds = ref(new Set<string>())
const autoRefresh = ref(true)
const activeFilter = ref<'all' | 'actionable' | 'validation'>('all')
let timer: ReturnType<typeof setInterval> | null = null
const optimizationNote = '从这里开始看：已补兜底，星星反馈兼容 label/reason/good-bad-neutral；日历同日重复写入会先关旧 latest，再写新版本。'
const refreshMs = 15000

const visibleErrors = computed(() => {
  if (activeFilter.value === 'actionable') {
    return errors.value.filter((item) => ['exception', 'config'].includes(errorKind(item)))
  }
  if (activeFilter.value === 'validation') {
    return errors.value.filter((item) => errorKind(item) === 'validation')
  }
  return errors.value
})

const filterTabs = computed(() => [
  { key: 'all' as const, label: '全部', count: errors.value.length },
  {
    key: 'actionable' as const,
    label: '真报错',
    count: errors.value.filter((item) => ['exception', 'config'].includes(errorKind(item))).length,
  },
  {
    key: 'validation' as const,
    label: '调用被拒',
    count: errors.value.filter((item) => errorKind(item) === 'validation').length,
  },
])

onMounted(async () => {
  await loadErrors()
  if (autoRefresh.value) timer = setInterval(loadErrors, refreshMs)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function loadErrors() {
  loading.value = true
  try {
    const data = await fetchToolErrors(50)
    errors.value = data.errors || []
  } catch { /* silent */ }
  finally { loading.value = false }
}

function toggleAuto() {
  if (autoRefresh.value) {
    timer = setInterval(loadErrors, refreshMs)
  } else {
    if (timer) { clearInterval(timer); timer = null }
  }
}

function toggle(id: string) {
  if (expandedIds.value.has(id)) expandedIds.value.delete(id)
  else expandedIds.value.add(id)
}

function shortTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  const mm = (d.getMonth() + 1).toString().padStart(2, '0')
  const dd = d.getDate().toString().padStart(2, '0')
  const hh = d.getHours().toString().padStart(2, '0')
  const mi = d.getMinutes().toString().padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

function toolLabel(e: ToolError) {
  if (e.target_tool && e.target_tool !== e.tool_name) return `${e.target_tool} (via ${e.tool_name})`
  return e.tool_name
}

function errorKind(e: ToolError) {
  return e.error_kind || 'unknown'
}

function kindLabel(kind: string) {
  if (kind === 'exception') return '真异常'
  if (kind === 'config') return '配置缺失'
  if (kind === 'validation') return '调用被拒'
  return '未知'
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + '...' : s
}

function tryParseJson(s: string | null) {
  if (!s) return null
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}
</script>

<template>
  <div class="te-page" data-testid="page-tool-errors">
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">工具报错</h1>
        <span class="subtitle">Tool Errors</span>
      </div>
      <div class="header-right">
        <span class="error-count">{{ visibleErrors.length }} / {{ errors.length }} 条记录</span>
        <label class="auto-toggle">
          <input type="checkbox" v-model="autoRefresh" @change="toggleAuto" />
          <span>自动刷新</span>
        </label>
        <button class="btn-refresh" @click="loadErrors" :disabled="loading">刷新</button>
      </div>
    </header>

    <div class="filter-tabs">
      <button
        v-for="tab in filterTabs"
        :key="tab.key"
        class="filter-tab"
        :class="{ active: activeFilter === tab.key }"
        @click="activeFilter = tab.key"
      >
        <span>{{ tab.label }}</span>
        <span class="tab-count">{{ tab.count }}</span>
      </button>
    </div>

    <div v-if="!visibleErrors.length && !loading" class="empty-state">
      <span class="empty-icon">✓</span>
      <p>暂无工具报错</p>
    </div>

    <div v-else class="error-list">
      <template v-for="(e, idx) in visibleErrors" :key="e.id">
        <div
          class="error-row"
          :class="{ expanded: expandedIds.has(e.id) }"
          @click="toggle(e.id)"
        >
          <div class="error-summary">
            <span class="err-time">{{ shortTime(e.created_at) }}</span>
            <span class="err-kind" :class="errorKind(e)">{{ kindLabel(errorKind(e)) }}</span>
            <span class="err-source" :class="e.error_source">{{ e.error_source }}</span>
            <span class="err-tool">{{ toolLabel(e) }}</span>
            <span class="err-text">{{ truncate(e.error_text, 80) }}</span>
          </div>
          <div v-if="expandedIds.has(e.id)" class="error-detail" @click.stop>
            <div class="detail-section">
              <span class="detail-label">Session</span>
              <span class="detail-value">{{ e.session_tag || e.session_id }}</span>
            </div>
            <div
              class="detail-grid"
              :class="{ pair: errorKind(e) === 'validation' && e.args_json }"
            >
              <div class="detail-section" v-if="e.args_json">
                <span class="detail-label">Args</span>
                <pre class="detail-pre">{{ tryParseJson(e.args_json) }}</pre>
              </div>
              <div class="detail-section">
                <span class="detail-label">Error</span>
                <pre class="detail-pre">{{ e.error_text }}</pre>
              </div>
            </div>
          </div>
        </div>
        <section v-if="idx === 0" class="fix-note fix-note-inline">
          <span class="fix-label">调试起点</span>
          <span class="fix-text">{{ optimizationNote }}</span>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.te-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 16px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 24px;
  padding: 0 4px;
}
.page-title {
  font-size: 22px;
  font-weight: 600;
  color: #3d3535;
  letter-spacing: -0.5px;
}
.subtitle {
  font-size: 12px;
  color: #b0a8a0;
  margin-left: 10px;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.error-count {
  font-size: 12px;
  color: #c87a5a;
  font-weight: 500;
}

.filter-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: -10px 4px 16px;
  padding: 3px;
  width: fit-content;
  max-width: 100%;
  border: 1px solid #eee7df;
  border-radius: 8px;
  background: #fbfaf8;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #8d8278;
  font-size: 12px;
  cursor: pointer;
}

.filter-tab.active {
  background: #fff;
  color: #5c504a;
  box-shadow: 0 1px 4px #d6cbc030;
}

.tab-count {
  font-size: 10px;
  color: #b6aaa1;
  font-variant-numeric: tabular-nums;
}

.fix-note {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 4px;
  padding: 10px 12px;
  border: 1px solid #e7ded6;
  border-radius: 8px;
  background: #fff9f4;
  color: #6a5a54;
  font-size: 12px;
  line-height: 1.5;
}

.fix-label {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f0d8c6;
  color: #8b5e46;
  font-weight: 600;
  font-size: 10px;
  letter-spacing: 0.5px;
}

.fix-text {
  min-width: 0;
}

.fix-note-inline {
  margin-top: 8px;
  margin-bottom: 8px;
}
.auto-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #999;
  cursor: pointer;
}
.auto-toggle input { margin: 0; }
.btn-refresh {
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid #e8e4df;
  background: #fff;
  color: #999;
  cursor: pointer;
  transition: 0.15s;
}
.btn-refresh:hover { border-color: #c87a5a; color: #c87a5a; }

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #ccc;
}
.empty-icon {
  font-size: 32px;
  display: block;
  margin-bottom: 8px;
  color: #c4e6c4;
}
.empty-state p {
  font-size: 14px;
  color: #bbb;
}

.error-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.error-row {
  background: #fff;
  border: 1px solid #f0ece8;
  border-radius: 10px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all 0.15s;
}
.error-row:hover {
  border-color: #e0d8d0;
}
.error-row.expanded {
  border-color: #c87a5a40;
  background: #fffcfa;
}

.error-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.err-time {
  font-size: 11px;
  color: #bbb;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.err-source {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  font-weight: 500;
}
.err-source.execute {
  background: #fdf0f0;
  color: #c05050;
}
.err-source.result {
  background: #fef3e2;
  color: #c87a1a;
}
.err-kind {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  font-weight: 600;
}
.err-kind.exception {
  background: #fdf0f0;
  color: #c05050;
}
.err-kind.config {
  background: #f2f0ff;
  color: #7162bb;
}
.err-kind.validation {
  background: #fef3e2;
  color: #b97218;
}
.err-kind.unknown {
  background: #f0f0f0;
  color: #888;
}
.err-tool {
  font-size: 12px;
  color: #666;
  font-weight: 500;
  flex-shrink: 0;
}
.err-text {
  font-size: 12px;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.error-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f5f2ef;
}
.detail-section {
  margin-bottom: 10px;
}
.detail-section:last-child { margin-bottom: 0; }
.detail-grid {
  display: grid;
  gap: 10px;
}
.detail-grid.pair {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  align-items: start;
}
.detail-label {
  display: block;
  font-size: 10px;
  color: #bbb;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.detail-value {
  font-size: 12px;
  color: #666;
}
.detail-pre {
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  background: #faf8f5;
  padding: 10px 12px;
  border-radius: 8px;
  max-height: 300px;
  overflow-y: auto;
  color: #555;
  margin: 0;
}

@media (max-width: 680px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .header-right {
    width: 100%;
    justify-content: space-between;
  }
  .error-summary {
    flex-wrap: wrap;
  }
  .filter-tabs {
    width: 100%;
  }
  .filter-tab {
    flex: 1;
    justify-content: center;
  }
  .detail-grid.pair {
    grid-template-columns: 1fr;
  }
}
</style>
