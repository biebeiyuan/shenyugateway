<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NInput,
  NPopconfirm,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  createGatewayHeartbeat,
  dedupeGatewayMessages,
  deleteGatewaySession,
  exportGatewaySession,
  fetchGatewaySession,
  fetchGatewaySessions,
  pruneGatewayRuntime,
  type GatewayColdStartSnapshot,
  type GatewayContextSnapshot,
  type GatewayHeartbeat,
  type GatewayRawRequestWindow,
  type GatewaySession,
  type GatewaySessionDetail,
} from '@/api/sessions'

const message = useMessage()
const loading = ref(false)
const detailLoading = ref(false)
const pruning = ref(false)
const deduping = ref(false)
const exporting = ref(false)
const deletingTag = ref('')
const query = ref('')
const sessions = ref<GatewaySession[]>([])
const selectedTag = ref('')
const detail = ref<GatewaySessionDetail | null>(null)
const heartbeatDraft = ref('')
const savingHeartbeat = ref(false)
const heartbeatVisibleCount = ref(100)

const selectedSession = computed(() => detail.value?.session || sessions.value.find((item) => item.session_tag === selectedTag.value))
const heartbeats = computed(() => detail.value?.heartbeats || [])
const visibleHeartbeats = computed(() => heartbeats.value.slice(0, heartbeatVisibleCount.value))
const hiddenHeartbeatCount = computed(() => Math.max(heartbeats.value.length - visibleHeartbeats.value.length, 0))

onMounted(loadSessions)

async function loadSessions() {
  loading.value = true
  try {
    const data = await fetchGatewaySessions({ limit: 200, q: query.value.trim() })
    sessions.value = data.sessions
    if (!selectedTag.value && data.sessions.length) {
      await selectSession(data.sessions[0].session_tag)
    } else if (selectedTag.value && !data.sessions.some((item) => item.session_tag === selectedTag.value)) {
      selectedTag.value = ''
      detail.value = null
    } else if (selectedTag.value) {
      await selectSession(selectedTag.value)
    }
  } catch (error) {
    message.error(errorText(error, '加载线程列表失败'))
  } finally {
    loading.value = false
  }
}

async function selectSession(sessionTag: string) {
  selectedTag.value = sessionTag
  await loadSessionDetail(sessionTag)
}

async function loadSessionDetail(sessionTag: string) {
  detailLoading.value = true
  heartbeatVisibleCount.value = 100
  try {
    detail.value = await fetchGatewaySession(sessionTag)
  } catch (error) {
    detail.value = null
    message.error(errorText(error, '加载线程详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function deleteSession(sessionTag: string) {
  deletingTag.value = sessionTag
  try {
    await deleteGatewaySession(sessionTag)
    message.success(`已删除线程：${sessionTag}`)
    if (selectedTag.value === sessionTag) {
      selectedTag.value = ''
      detail.value = null
    }
    await loadSessions()
  } catch (error) {
    message.error(errorText(error, '删除失败'))
  } finally {
    deletingTag.value = ''
  }
}

async function dedupeMessages() {
  deduping.value = true
  try {
    const result = await dedupeGatewayMessages()
    const deleted = result?.deleted || {}
    message.success(`已去重：消息 ${deleted.gateway_messages || 0} 条，原始窗口 ${deleted.raw_request_windows || 0} 个`)
    await loadSessions()
  } catch (error) {
    message.error(errorText(error, '去重失败'))
  } finally {
    deduping.value = false
  }
}

async function pruneRuntime() {
  pruning.value = true
  try {
    const result = await pruneGatewayRuntime()
    const deleted = result?.deleted || {}
    message.success(`已清理：消息 ${deleted.gateway_messages || 0}，快照 ${deleted.request_context_snapshots || 0}，原始窗口 ${deleted.raw_request_windows || 0}`)
    await loadSessions()
  } catch (error) {
    message.error(errorText(error, '清理失败'))
  } finally {
    pruning.value = false
  }
}

async function saveHeartbeat() {
  if (!selectedTag.value) return
  savingHeartbeat.value = true
  try {
    await createGatewayHeartbeat(selectedTag.value, heartbeatDraft.value)
    heartbeatDraft.value = ''
    message.success('Heartbeat 已写入')
    await loadSessionDetail(selectedTag.value)
  } catch (error) {
    message.error(errorText(error, 'Heartbeat 写入失败'))
  } finally {
    savingHeartbeat.value = false
  }
}

async function exportSession(sessionTag: string) {
  exporting.value = true
  try {
    const bundle = await exportGatewaySession(sessionTag)
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    const safeTag = sessionTag.replace(/[^\w.-]+/g, '_') || 'session'
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `shenyu-session-${safeTag}-${stamp}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    message.success(`已导出线程：${sessionTag}`)
  } catch (error) {
    message.error(errorText(error, '导出失败'))
  } finally {
    exporting.value = false
  }
}

function errorText(error: unknown, fallback: string) {
  const maybe = error as { response?: { data?: { detail?: string } }; message?: string }
  return maybe?.response?.data?.detail || maybe?.message || fallback
}

function formatTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function textValue(value: unknown) {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'text' in item) return String((item as { text?: unknown }).text || '')
        return ''
      })
      .filter(Boolean)
      .join('\n')
  }
  if (value == null) return ''
  return String(value)
}

function shortText(value: unknown, limit = 120) {
  const text = textValue(value).trim()
  if (!text) return '(空)'
  return text.length > limit ? `${text.slice(0, limit - 1).trim()}...` : text
}

function roleLabel(role: string) {
  if (role === 'user') return '圆圆'
  if (role === 'assistant') return '沈予'
  if (role === 'tool') return '工具'
  if (role === 'system') return '系统'
  return role || '未知'
}

function roleType(role: string) {
  if (role === 'user') return 'info'
  if (role === 'assistant') return 'success'
  if (role === 'tool') return 'warning'
  return 'default'
}

function heartbeatState(item: GatewayHeartbeat) {
  return item.injected_at ? `已注入 ${formatTime(item.injected_at)}` : '待注入'
}

function snapshotTitle(item: GatewayContextSnapshot) {
  return `${formatTime(item.created_at)} / ${item.message_count} 条 / 最新圆圆：${shortText(item.latest_user_text, 80)}`
}

function rawWindowTitle(item: GatewayRawRequestWindow) {
  return `${formatTime(item.created_at)} / ${item.message_count} 条 / 最新圆圆：${shortText(item.latest_user_text, 80)}`
}

function coldTitle(item: GatewayColdStartSnapshot) {
  return `${formatTime(item.created_at)} / ${item.reason} / 已注入 ${item.injected_count} 次 / ${item.active === false ? '已停用' : '补窗中'}`
}

function showMoreHeartbeats() {
  heartbeatVisibleCount.value += 100
}
</script>

<template>
  <main class="sessions-page">
    <NSpace vertical size="medium">
      <div class="toolbar">
        <NInput
          v-model:value="query"
          placeholder="搜索线程标识或客户端名称"
          clearable
          class="search-input"
          @keyup.enter="loadSessions"
        />
        <NButton type="primary" :loading="loading" @click="loadSessions">搜索</NButton>
        <NButton :loading="loading" @click="loadSessions">刷新</NButton>
        <NButton :loading="deduping" @click="dedupeMessages">一键清除重复消息</NButton>
        <NButton :loading="pruning" @click="pruneRuntime">按保留策略清理</NButton>
      </div>

      <section class="thread-strip">
        <button
          v-for="item in sessions"
          :key="item.session_tag"
          class="thread-chip"
          :class="{ active: selectedTag === item.session_tag }"
          @click="selectSession(item.session_tag)"
        >
          <strong>{{ item.session_tag }}</strong>
          <span>原始 {{ item.raw_request_window_count || 0 }} / 快照 {{ item.context_snapshot_count || 0 }} / hb {{ item.heartbeat_count || 0 }}</span>
          <em>{{ shortText(item.latest_user_text, 90) }}</em>
        </button>
        <NEmpty v-if="!sessions.length && !loading" description="暂无线程" />
      </section>

      <NCard title="线程详情" size="small" :loading="detailLoading">
        <template v-if="selectedSession && detail">
          <NDescriptions :column="2" size="small" label-placement="left" bordered>
            <NDescriptionsItem label="线程标识">{{ selectedSession.session_tag }}</NDescriptionsItem>
            <NDescriptionsItem label="客户端">{{ selectedSession.client_name || 'unknown' }}</NDescriptionsItem>
            <NDescriptionsItem label="开始时间">{{ formatTime(selectedSession.started_at) }}</NDescriptionsItem>
            <NDescriptionsItem label="最后活跃">{{ formatTime(selectedSession.last_active_at) }}</NDescriptionsItem>
            <NDescriptionsItem label="原始请求窗口">{{ detail.stats.raw_request_windows || 0 }}</NDescriptionsItem>
            <NDescriptionsItem label="缓存层">
              {{ detail.stats.heartbeats }} heartbeat /
              {{ detail.stats.context_snapshots || 0 }} snapshots / {{ detail.stats.raw_request_windows || 0 }} raw /
              {{ detail.stats.cold_start_snapshots }} cold start
            </NDescriptionsItem>
            <NDescriptionsItem label="最新圆圆消息" :span="2">
              {{ shortText(selectedSession.latest_user_text, 220) }}
            </NDescriptionsItem>
          </NDescriptions>

          <NTabs type="line" animated class="detail-tabs">
            <NTabPane name="raw-windows" tab="消息">
              <div v-if="detail.raw_request_windows?.length" class="stack">
                <section v-for="window in detail.raw_request_windows" :key="window.id" class="block">
                  <h3>{{ rawWindowTitle(window) }}</h3>
                  <div class="mini-list">
                    <div v-for="(msg, index) in window.messages" :key="index" class="mini-row">
                      <NTag size="small" :type="roleType(String(msg.role || ''))">{{ roleLabel(String(msg.role || '')) }}</NTag>
                      <span>{{ shortText(msg.content, 260) }}</span>
                    </div>
                  </div>
                </section>
              </div>
              <NEmpty v-else description="暂无原始请求窗口" />
            </NTabPane>

            <NTabPane name="snapshots" tab="上下文快照">
              <div v-if="detail.context_snapshots.length" class="stack">
                <section v-for="snapshot in detail.context_snapshots" :key="snapshot.id" class="block">
                  <h3>{{ snapshotTitle(snapshot) }}</h3>
                  <div class="mini-list">
                    <div v-for="(msg, index) in snapshot.messages.slice(-8)" :key="index" class="mini-row">
                      <NTag size="small" :type="roleType(String(msg.role || ''))">{{ roleLabel(String(msg.role || '')) }}</NTag>
                      <span>{{ shortText(msg.content, 240) }}</span>
                    </div>
                  </div>
                </section>
              </div>
              <NEmpty v-else description="暂无上下文快照" />
            </NTabPane>

            <NTabPane name="cold-start" tab="冷启动">
              <div v-if="detail.cold_start_snapshots.length" class="stack">
                <section v-for="snapshot in detail.cold_start_snapshots" :key="snapshot.id" class="block">
                  <h3>{{ coldTitle(snapshot) }}</h3>
                  <div class="meta-line">
                    来源线程：{{ snapshot.source_session_tags.join(', ') || '-' }} / 来源消息：{{ snapshot.source_message_count }}
                  </div>
                  <div v-for="source in snapshot.sources" :key="`${snapshot.id}-${source.session_tag}-${source.snapshot_at}`" class="source-box">
                    <strong>{{ source.session_tag || 'unknown' }}</strong>
                    <span>{{ source.client_name || 'unknown' }} / {{ formatTime(source.snapshot_at) }}</span>
                    <div class="mini-list">
                      <div v-for="(msg, index) in (source.messages || []).slice(-6)" :key="index" class="mini-row">
                        <NTag size="small" :type="roleType(String(msg.role || ''))">{{ roleLabel(String(msg.role || '')) }}</NTag>
                        <span>{{ shortText(msg.content, 220) }}</span>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
              <NEmpty v-else description="暂无冷启动快照" />
            </NTabPane>

            <NTabPane name="heartbeats" tab="Heartbeat">
              <div class="heartbeat-editor">
                <NInput
                  v-model:value="heartbeatDraft"
                  type="textarea"
                  placeholder="写给我自己的 heartbeat。只写正文，不需要标签。"
                  :autosize="{ minRows: 4, maxRows: 8 }"
                />
                <div class="heartbeat-actions">
                  <NButton type="primary" :loading="savingHeartbeat" @click="saveHeartbeat">写入 Heartbeat</NButton>
                </div>
              </div>
              <div v-if="heartbeats.length" class="chat-list">
                <div v-for="item in visibleHeartbeats" :key="item.id" class="chat-row heartbeat-row">
                  <div class="chat-head">
                    <NTag size="small" type="warning">Heartbeat</NTag>
                    <span>{{ formatTime(item.created_at) }}</span>
                    <span>{{ heartbeatState(item) }}</span>
                  </div>
                  <div class="chat-body">{{ item.content }}</div>
                </div>
                <div v-if="hiddenHeartbeatCount" class="load-more-row">
                  <NButton secondary @click="showMoreHeartbeats">继续显示 {{ Math.min(hiddenHeartbeatCount, 100) }} 条 / 剩余 {{ hiddenHeartbeatCount }} 条</NButton>
                </div>
              </div>
              <NEmpty v-else description="暂无 heartbeat" />
            </NTabPane>
          </NTabs>

          <div class="danger-zone">
            <NButton :loading="exporting" @click="exportSession(selectedSession.session_tag)">
              导出此线程 JSON
            </NButton>
            <NPopconfirm positive-text="删除" negative-text="取消" @positive-click="deleteSession(selectedSession.session_tag)">
              <template #trigger>
                <NButton type="error" :loading="deletingTag === selectedSession.session_tag">
                  删除此线程
                </NButton>
              </template>
              删除 {{ selectedSession.session_tag }} 及其所有相关本地 SQLite 数据。
            </NPopconfirm>
          </div>
        </template>
        <NEmpty v-else description="请选择一个线程" />
      </NCard>
    </NSpace>
  </main>
</template>

<style scoped>
.sessions-page {
  margin: 0 auto;
  max-width: 1120px;
}

.toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.search-input {
  max-width: 340px;
  min-width: 240px;
}

.thread-strip {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}

.thread-chip {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 92px;
  padding: 10px 12px;
  text-align: left;
}

.thread-chip.active {
  border-color: #c094a8;
  box-shadow: inset 3px 0 0 #c094a8;
}

.thread-chip strong {
  color: #333;
  font-size: 14px;
  word-break: break-all;
}

.thread-chip span,
.thread-chip em,
.meta-line {
  color: #888;
  font-size: 12px;
}

.thread-chip em {
  font-style: normal;
  line-height: 1.35;
}

.detail-tabs {
  margin-top: 16px;
}

.heartbeat-editor {
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px;
}

.heartbeat-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chat-list,
.stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-row {
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 10px 12px;
}

.chat-row.user {
  background: #f7fbff;
}

.chat-row.assistant {
  background: #f8fff9;
}

.chat-row.tool,
.heartbeat-row {
  background: #fffaf0;
}

.chat-head {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}

.chat-head span {
  color: #999;
  font-size: 12px;
}

.chat-body {
  color: #1f1f1f;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.load-more-row {
  display: flex;
  justify-content: center;
  padding: 4px 0;
}

.block {
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 10px 12px;
}

.block h3 {
  color: #333;
  font-size: 13px;
  margin: 0 0 8px;
}

.mini-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mini-row {
  align-items: flex-start;
  display: grid;
  gap: 8px;
  grid-template-columns: 76px 1fr;
  line-height: 1.45;
}

.mini-row span {
  white-space: pre-wrap;
  word-break: break-word;
}

.source-box {
  background: #fff;
  border: 1px solid #ededed;
  border-radius: 6px;
  margin-top: 8px;
  padding: 8px;
}

.source-box strong {
  display: block;
  font-size: 13px;
}

.source-box > span {
  color: #999;
  display: block;
  font-size: 12px;
  margin-bottom: 6px;
}

.danger-zone {
  border-top: 1px solid #e8e8e8;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
  padding-top: 14px;
}

@media (max-width: 680px) {
  .sessions-page {
    max-width: none;
  }

  .search-input {
    max-width: none;
    min-width: 100%;
  }

  .thread-strip {
    grid-template-columns: 1fr;
  }
}
</style>
