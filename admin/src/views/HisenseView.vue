<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCollapse,
  NCollapseItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  useMessage,
} from 'naive-ui'
import {
  createNotebookItem,
  deleteNotebookItem,
  fetchHisensePreview,
  fetchHisenseSessions,
  fetchNotebook,
  updateNotebookItem,
  type HisensePreview,
  type NotebookItem,
} from '@/api/hisense'
import { api } from '@/api/http'

const message = useMessage()

const preview = ref<HisensePreview | null>(null)
const previewLoading = ref(false)
const notebook = ref<NotebookItem[]>([])
const notebookLoading = ref(false)
const sessions = ref<unknown[]>([])
const sessionsLoading = ref(false)

const heartbeatLimit = ref(10)
const notebookLimit = ref(5)
const savingConfig = ref(false)

const nbTypeFilter = ref('')
const nbStatusFilter = ref('active')

const showModal = ref(false)
const editingItem = ref<NotebookItem | null>(null)
const formType = ref('note')
const formContent = ref('')
const formTags = ref('')
const formSaving = ref(false)
const showConfig = ref(false)

const typeOptions = [
  { label: '全部', value: '' },
  { label: 'note', value: 'note' },
  { label: 'task', value: 'task' },
  { label: 'thought', value: 'thought' },
  { label: 'observation', value: 'observation' },
  { label: 'question', value: 'question' },
]

const hasCalendar = computed(() => {
  if (!preview.value) return false
  const ctx = preview.value.package.calendar_context
  return Object.values(ctx).some((rows: any) => rows?.length > 0)
})
const heartbeatLines = computed(() => (preview.value?.package.heartbeat_digest || '').split('\n').filter(Boolean))
const hisenseHeartbeatLines = computed(() => (preview.value?.package.hisense_heartbeat_digest || '').split('\n').filter(Boolean))
const hasHeartbeat = computed(() => heartbeatLines.value.length > 0 || hisenseHeartbeatLines.value.length > 0)

onMounted(async () => {
  await Promise.all([loadPreview(), loadNotebook(), loadSessions()])
})

async function loadPreview() {
  previewLoading.value = true
  try {
    preview.value = await fetchHisensePreview()
    heartbeatLimit.value = preview.value.config.hisense_heartbeat_limit
    notebookLimit.value = preview.value.config.hisense_notebook_limit
  } catch { message.error('加载预览失败') }
  finally { previewLoading.value = false }
}

async function saveConfig() {
  savingConfig.value = true
  try {
    await api.post('/api/config', { hisense_heartbeat_limit: heartbeatLimit.value, hisense_notebook_limit: notebookLimit.value })
    message.success('已保存')
    await loadPreview()
  } catch { message.error('保存失败') }
  finally { savingConfig.value = false }
}

async function loadNotebook() {
  notebookLoading.value = true
  try {
    const params: Record<string, string | number> = { status: nbStatusFilter.value, limit: 50 }
    if (nbTypeFilter.value) params.type = nbTypeFilter.value
    const res = await fetchNotebook(params as any)
    notebook.value = res.data
  } catch { message.error('加载笔记本失败') }
  finally { notebookLoading.value = false }
}

async function loadSessions() {
  sessionsLoading.value = true
  try { sessions.value = (await fetchHisenseSessions(20)).sessions }
  catch { message.error('加载线程失败') }
  finally { sessionsLoading.value = false }
}

function openCreate() { editingItem.value = null; formType.value = 'note'; formContent.value = ''; formTags.value = ''; showModal.value = true }
function openEdit(item: NotebookItem) { editingItem.value = item; formType.value = item.type; formContent.value = item.content; formTags.value = (item.tags || []).join(', '); showModal.value = true }

async function saveItem() {
  if (!formContent.value.trim()) { message.warning('内容不能为空'); return }
  formSaving.value = true
  const tags = formTags.value.split(/[,，]/).map(t => t.trim()).filter(Boolean)
  try {
    if (editingItem.value) { await updateNotebookItem(editingItem.value.id, { type: formType.value, content: formContent.value, tags }); message.success('已更新') }
    else { await createNotebookItem({ type: formType.value, content: formContent.value, tags: tags.length ? tags : undefined }); message.success('已创建') }
    showModal.value = false; await loadNotebook()
  } catch { message.error('保存失败') }
  finally { formSaving.value = false }
}

async function markDone(item: NotebookItem) { await updateNotebookItem(item.id, { status: 'done' }); message.success('已完成'); await loadNotebook() }
async function archive(item: NotebookItem) { await updateNotebookItem(item.id, { status: 'archived' }); message.success('已归档'); await loadNotebook() }
async function togglePin(item: NotebookItem) { await updateNotebookItem(item.id, { pinned: !item.pinned }); message.success(item.pinned ? '已取消置顶' : '已置顶'); await loadNotebook() }
async function remove(item: NotebookItem) { await deleteNotebookItem(item.id); message.success('已删除'); await loadNotebook() }

function shortTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="hisense-page">
    <!-- Header -->
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">沈予的空间</h1>
        <span class="subtitle">Hisense · Private</span>
      </div>
      <div class="header-right">
        <span class="session-count" v-if="sessions.length">{{ sessions.length }} 次唤醒</span>
        <button class="config-toggle" @click="showConfig = !showConfig">
          {{ showConfig ? '收起调试' : '调试' }}
        </button>
      </div>
    </header>

    <!-- Main Grid -->
    <div class="grid">
      <!-- Heartbeat Card -->
      <section class="card card-heartbeat">
        <div class="card-header">
          <h2>心跳</h2>
          <span class="card-badge">最近 {{ heartbeatLimit }} 条</span>
        </div>
        <div class="card-body" v-if="hasHeartbeat">
          <div class="heartbeat-list" v-if="heartbeatLines.length">
            <h3 class="heartbeat-title">你之前写下的心跳</h3>
            <p v-for="(line, i) in heartbeatLines" :key="`normal-${i}`" class="heartbeat-line">{{ line }}</p>
          </div>
          <div class="heartbeat-list" v-if="hisenseHeartbeatLines.length">
            <h3 class="heartbeat-title">海信线程心跳</h3>
            <p v-for="(line, i) in hisenseHeartbeatLines" :key="`hisense-${i}`" class="heartbeat-line">
              {{ line }}
            </p>
          </div>
        </div>
        <div class="card-body empty" v-else>
          <span>暂无心跳</span>
        </div>
      </section>

      <!-- Notebook Card -->
      <section class="card card-notebook">
        <div class="card-header">
          <h2>笔记本</h2>
          <div class="card-actions">
            <select v-model="nbStatusFilter" class="mini-select" @change="loadNotebook()">
              <option value="active">active</option>
              <option value="done">done</option>
              <option value="archived">archived</option>
            </select>
            <button class="btn-add" @click="openCreate">+</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="notebookLoading" class="empty"><span>加载中...</span></div>
          <div v-else-if="!notebook.length" class="empty"><span>暂无条目</span></div>
          <div v-else class="nb-list">
            <div v-for="item in notebook" :key="item.id" class="nb-row" :class="{ pinned: item.pinned }">
              <div class="nb-row-top">
                <span class="nb-pin" v-if="item.pinned">PIN</span>
                <span class="nb-type" :class="item.type">{{ item.type }}</span>
                <span class="nb-content">{{ item.content }}</span>
              </div>
              <div class="nb-row-bottom">
                <span class="nb-tags" v-if="item.tags?.length">{{ item.tags.join(' · ') }}</span>
                <span class="nb-time">{{ shortTime(item.updated_at) }}</span>
                <div class="nb-ops">
                  <button @click="togglePin(item)">{{ item.pinned ? 'unpin' : 'pin' }}</button>
                  <button @click="openEdit(item)">edit</button>
                  <button v-if="item.status === 'active'" @click="markDone(item)">done</button>
                  <button @click="archive(item)">archive</button>
                  <NPopconfirm @positive-click="remove(item)">
                    <template #trigger><button class="danger">del</button></template>
                    确定删除？
                  </NPopconfirm>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Calendar Card -->
      <section class="card card-calendar">
        <div class="card-header">
          <h2>日历记忆</h2>
          <span class="card-badge">digest</span>
        </div>
        <div class="card-body" v-if="preview">
          <div v-for="(rows, key) in preview.package.calendar_context" :key="key">
            <template v-if="(rows as any[])?.length">
              <div v-for="(row, i) in (rows as any[])" :key="i" class="cal-row">
                <span class="cal-key">{{ (row as any).period_key }}</span>
                <span class="cal-digest">{{ (row as any).digest || (row as any).summary || '' }}</span>
              </div>
            </template>
          </div>
          <div v-if="!hasCalendar" class="empty"><span>暂无</span></div>
        </div>
      </section>

      <!-- Recap Card -->
      <section class="card card-recap">
        <div class="card-header">
          <h2>上次醒来</h2>
          <span class="card-badge">handoff</span>
        </div>
        <div class="card-body">
          <p class="recap-text" v-if="preview?.package.last_wake_recap">{{ preview.package.last_wake_recap }}</p>
          <div class="empty" v-else><span>无记录</span></div>
        </div>
      </section>

      <!-- Sessions Card -->
      <section class="card card-sessions">
        <div class="card-header">
          <h2>唤醒记录</h2>
          <button class="btn-refresh" @click="loadSessions" :disabled="sessionsLoading">刷新</button>
        </div>
        <div class="card-body">
          <div v-if="!sessions.length" class="empty"><span>暂无</span></div>
          <div v-else class="session-list">
            <div v-for="(s, i) in sessions.slice(0, 8)" :key="i" class="session-row">
              <span class="s-tag">{{ (s as any).session_tag }}</span>
              <span class="s-count">{{ (s as any).message_count || 0 }} 轮</span>
              <span class="s-time">{{ shortTime((s as any).last_active_at) }}</span>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Config Panel (collapsible) -->
    <section class="config-panel" v-if="showConfig">
      <div class="config-inner">
        <h3>注入控制</h3>
        <div class="config-fields">
          <label>
            <span>Heartbeat 注入数</span>
            <NInputNumber v-model:value="heartbeatLimit" :min="1" :max="30" size="small" style="width: 100px" />
          </label>
          <label>
            <span>Notebook 注入数</span>
            <NInputNumber v-model:value="notebookLimit" :min="1" :max="20" size="small" style="width: 100px" />
          </label>
          <NButton size="small" type="primary" :loading="savingConfig" @click="saveConfig">保存</NButton>
          <NButton size="small" :loading="previewLoading" @click="loadPreview">刷新预览</NButton>
        </div>
        <NCollapse style="margin-top: 16px">
          <NCollapseItem title="完整 Slow Layer 预览" name="full">
            <pre class="raw-preview">{{ preview?.rendered_slow_layer || '(空)' }}</pre>
          </NCollapseItem>
        </NCollapse>
      </div>
    </section>

    <!-- Modal -->
    <NModal v-model:show="showModal" preset="card" :title="editingItem ? '编辑' : '新建'" style="width: 460px; border-radius: 16px">
      <div class="form-field">
        <label>类型</label>
        <NSelect v-model:value="formType" :options="typeOptions.slice(1)" size="small" style="width: 140px" />
      </div>
      <div class="form-field">
        <label>内容</label>
        <NInput v-model:value="formContent" type="textarea" :rows="3" placeholder="写点什么..." />
      </div>
      <div class="form-field">
        <label>标签</label>
        <NInput v-model:value="formTags" size="small" placeholder="逗号分隔" />
      </div>
      <div style="margin-top: 16px; text-align: right">
        <NButton @click="showModal = false" style="margin-right: 8px">取消</NButton>
        <NButton type="primary" :loading="formSaving" @click="saveItem">保存</NButton>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.hisense-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 16px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 28px;
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
.session-count {
  font-size: 12px;
  color: #9b8ec4;
  font-weight: 500;
}
.config-toggle {
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 12px;
  border: 1px solid #e8e4df;
  background: #fff;
  color: #999;
  cursor: pointer;
  transition: all 0.2s;
}
.config-toggle:hover {
  border-color: #9b8ec4;
  color: #9b8ec4;
}

/* Grid */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* Cards */
.card {
  background: #fff;
  border: 1px solid #f0ece8;
  border-radius: 14px;
  overflow: hidden;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px 10px;
  border-bottom: 1px solid #f5f2ef;
}
.card-header h2 {
  font-size: 14px;
  font-weight: 600;
  color: #3d3535;
}
.card-badge {
  font-size: 10px;
  color: #9b8ec4;
  background: #f5f3fa;
  padding: 2px 8px;
  border-radius: 8px;
  letter-spacing: 0.5px;
}
.card-body {
  padding: 14px 18px 16px;
  font-size: 13px;
  line-height: 1.7;
  color: #555;
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.empty {
  color: #ccc;
  font-size: 12px;
  padding: 8px 0;
}

/* Heartbeat */
.card-heartbeat {
  grid-column: 1 / 2;
  grid-row: 1 / 3;
}
.heartbeat-list {
  max-height: 280px;
  overflow-y: auto;
}
.heartbeat-list + .heartbeat-list {
  margin-top: 14px;
}
.heartbeat-title {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: #3d3535;
}
.heartbeat-line {
  padding: 6px 0;
  border-bottom: 1px solid #faf8f5;
  font-size: 12.5px;
  color: #666;
  line-height: 1.6;
}
.heartbeat-line:last-child { border-bottom: none; }

/* Notebook */
.card-notebook {
  grid-column: 1 / -1;
}
.nb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.nb-row {
  padding: 10px 14px;
  border-radius: 10px;
  background: #faf9f7;
  transition: all 0.15s;
}
.nb-row.pinned {
  background: #f8f5fd;
  border-left: 3px solid #9b8ec4;
}
.nb-row-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.nb-pin {
  font-size: 9px;
  font-weight: 700;
  color: #9b8ec4;
  letter-spacing: 0.5px;
}
.nb-type {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #f0ece8;
  color: #999;
  flex-shrink: 0;
}
.nb-type.task { background: #fef3e2; color: #c87a1a; }
.nb-type.thought { background: #eef0fa; color: #6b6ea8; }
.nb-type.observation { background: #eef8f0; color: #4a8a5a; }
.nb-type.question { background: #fdf0f0; color: #a85a5a; }
.nb-content {
  font-size: 13px;
  color: #3d3535;
  flex: 1;
}
.nb-row-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 11px;
  color: #bbb;
}
.nb-tags { color: #9b8ec4; }
.nb-time { margin-left: auto; }
.nb-ops {
  display: flex;
  gap: 4px;
}
.nb-ops button {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #e8e4df;
  background: #fff;
  color: #999;
  cursor: pointer;
  transition: 0.15s;
}
.nb-ops button:hover { border-color: #9b8ec4; color: #9b8ec4; }
.nb-ops button.danger:hover { border-color: #e55; color: #e55; }

/* Calendar */
.card-calendar { grid-column: 2 / 3; grid-row: 1 / 2; }
.cal-row {
  padding: 4px 0;
  display: flex;
  gap: 8px;
}
.cal-key {
  font-size: 11px;
  color: #9b8ec4;
  font-weight: 500;
  flex-shrink: 0;
  min-width: 70px;
}
.cal-digest {
  font-size: 12.5px;
  color: #666;
  line-height: 1.5;
}

/* Recap */
.card-recap { grid-column: 2 / 3; grid-row: 2 / 3; }
.recap-text {
  font-size: 13px;
  color: #555;
  line-height: 1.7;
  font-style: italic;
}

/* Sessions */
.card-sessions { grid-column: 1 / -1; }
.session-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
}
.session-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}
.s-tag { color: #666; font-weight: 500; }
.s-count { color: #9b8ec4; }
.s-time { margin-left: auto; color: #ccc; }

/* Mini controls */
.mini-select {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid #e8e4df;
  background: #fff;
  color: #666;
  outline: none;
}
.btn-add {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 1px solid #e8e4df;
  background: #fff;
  font-size: 16px;
  color: #9b8ec4;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: 0.15s;
}
.btn-add:hover { background: #f5f3fa; border-color: #9b8ec4; }
.btn-refresh {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 8px;
  border: 1px solid #e8e4df;
  background: #fff;
  color: #999;
  cursor: pointer;
}

/* Config Panel */
.config-panel {
  margin-top: 24px;
  border: 1px solid #f0ece8;
  border-radius: 14px;
  background: #fdfcfb;
  padding: 20px;
}
.config-inner h3 {
  font-size: 13px;
  font-weight: 600;
  color: #3d3535;
  margin-bottom: 12px;
}
.config-fields {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.config-fields label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
}
.raw-preview {
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  background: #faf8f5;
  padding: 12px;
  border-radius: 8px;
  max-height: 400px;
  overflow-y: auto;
  color: #666;
}

/* Form */
.form-field {
  margin-bottom: 14px;
}
.form-field label {
  display: block;
  font-size: 11px;
  color: #999;
  margin-bottom: 4px;
  letter-spacing: 0.5px;
}

/* Mobile */
@media (max-width: 680px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .card-heartbeat {
    grid-column: 1;
    grid-row: auto;
  }
  .card-calendar { grid-column: 1; grid-row: auto; }
  .card-recap { grid-column: 1; grid-row: auto; }
  .card-notebook { grid-column: 1; }
  .card-sessions { grid-column: 1; }
  .session-list {
    grid-template-columns: 1fr;
  }
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .header-right {
    width: 100%;
    justify-content: space-between;
  }
  .config-fields {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
