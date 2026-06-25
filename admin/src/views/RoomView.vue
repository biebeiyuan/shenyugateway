<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NButton,
  NEmpty,
  NInput,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  createDrawerNote,
  fetchDrawerNotes,
  fetchRoomPreview,
  fetchRoomTraces,
  type DrawerNote,
  type RoomTrace,
} from '@/api/room'

const TRACE_LABELS: Record<string, string> = {
  sit: '坐了一会儿',
  read_box: '翻了心跳',
  wooden_box: '翻了心跳',
  star_map: '看了星图',
  notebook: '翻了笔记本',
  scribble: '写了点什么',
  wall_pins: '看了便签',
  conflict_shelf: '翻了矛盾之书',
  pillow: '抱了章鱼',
  octopus_pillow: '抱了章鱼',
  locked_drawer: '开了抽屉',
  drawer_notes: '看了纸条',
  window: '看了窗外',
}

const message = useMessage()

const tab = ref('traces')
const traces = ref<RoomTrace[]>([])
const tracesLoading = ref(false)

const preview = ref<{ charge: number; layers: Record<string, string> } | null>(null)
const previewLoading = ref(false)

const notes = ref<DrawerNote[]>([])
const notesLoading = ref(false)
const notesUnread = ref(0)
const noteDraft = ref('')
const noteSending = ref(false)

onMounted(() => loadTraces())

async function loadTraces() {
  tracesLoading.value = true
  try {
    const data = await fetchRoomTraces(50)
    traces.value = data.traces
  } catch { /* silent */ }
  finally { tracesLoading.value = false }
}

async function loadPreview() {
  previewLoading.value = true
  try {
    preview.value = await fetchRoomPreview()
  } catch { /* silent */ }
  finally { previewLoading.value = false }
}

async function loadNotes() {
  notesLoading.value = true
  try {
    const data = await fetchDrawerNotes(30)
    notes.value = data.notes
    notesUnread.value = data.unread
  } catch { /* silent */ }
  finally { notesLoading.value = false }
}

function onTabChange(name: string) {
  tab.value = name
  if (name === 'traces' && !traces.value.length) loadTraces()
  if (name === 'preview') loadPreview()
  if (name === 'notes' && !notes.value.length) loadNotes()
}

async function sendNote() {
  const content = noteDraft.value.trim()
  if (!content) return
  noteSending.value = true
  try {
    await createDrawerNote(content)
    noteDraft.value = ''
    message.success('纸条塞进去了')
    await loadNotes()
  } catch {
    message.error('发送失败')
  } finally {
    noteSending.value = false
  }
}

function relativeTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  const now = Date.now()
  const diff = now - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return shortDate(iso)
}

function shortDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  const mm = (d.getMonth() + 1).toString().padStart(2, '0')
  const dd = d.getDate().toString().padStart(2, '0')
  const hh = d.getHours().toString().padStart(2, '0')
  const mi = d.getMinutes().toString().padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

function traceLabel(action: string) {
  return TRACE_LABELS[action] || action
}

function chargePercent(c: number) {
  return Math.round(c * 100)
}
</script>

<template>
  <div class="room-page">
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">房间</h1>
        <span class="subtitle">Room</span>
      </div>
    </header>

    <NTabs :value="tab" @update:value="onTabChange" type="line" animated>
      <NTabPane name="traces" tab="足迹">
        <div class="tab-toolbar">
          <NButton size="small" @click="loadTraces" :loading="tracesLoading" quaternary>刷新</NButton>
        </div>
        <NSpin :show="tracesLoading">
          <NEmpty v-if="!traces.length && !tracesLoading" description="还没有足迹" />
          <div v-else class="trace-list">
            <div v-for="t in traces" :key="t.id" class="trace-item">
              <div class="trace-dot" />
              <div class="trace-body">
                <span class="trace-action">{{ traceLabel(t.action) }}</span>
                <NTag v-if="t.detail?.tag" size="tiny" :bordered="false" type="default" class="trace-tag">
                  {{ t.detail.tag }}
                </NTag>
                <p v-if="t.scribble" class="trace-scribble">{{ t.scribble }}</p>
                <span class="trace-time">{{ relativeTime(t.created_at) }}</span>
              </div>
            </div>
          </div>
        </NSpin>
      </NTabPane>

      <NTabPane name="preview" tab="窗外">
        <div class="tab-toolbar">
          <NButton size="small" @click="loadPreview" :loading="previewLoading" quaternary>换一个</NButton>
        </div>
        <NSpin :show="previewLoading">
          <div v-if="preview" class="preview-card">
            <div class="charge-bar">
              <div class="charge-label">charge</div>
              <div class="charge-track">
                <div class="charge-fill" :style="{ width: chargePercent(preview.charge) + '%' }" />
              </div>
              <div class="charge-value">{{ chargePercent(preview.charge) }}%</div>
            </div>
            <div class="scene-text" v-if="preview.layers?.slow">
              {{ preview.layers.slow }}
            </div>
            <details v-if="preview.layers?.tool_policy" class="layer-details">
              <summary>空间布局</summary>
              <pre class="layer-pre">{{ preview.layers.tool_policy }}</pre>
            </details>
            <details v-if="preview.layers?.stable" class="layer-details">
              <summary>房间设定</summary>
              <pre class="layer-pre">{{ preview.layers.stable }}</pre>
            </details>
          </div>
          <NEmpty v-else-if="!previewLoading" description="点击「换一个」加载场景" />
        </NSpin>
      </NTabPane>

      <NTabPane name="notes" tab="纸条">
        <div class="note-compose">
          <NInput
            v-model:value="noteDraft"
            type="textarea"
            placeholder="写一张纸条塞进抽屉..."
            :autosize="{ minRows: 2, maxRows: 5 }"
            :disabled="noteSending"
          />
          <NButton
            size="small"
            type="primary"
            @click="sendNote"
            :loading="noteSending"
            :disabled="!noteDraft.trim()"
            class="send-btn"
          >
            塞进去
          </NButton>
        </div>
        <div class="tab-toolbar">
          <span v-if="notesUnread" class="unread-count">{{ notesUnread }} 未读</span>
          <NButton size="small" @click="loadNotes" :loading="notesLoading" quaternary>刷新</NButton>
        </div>
        <NSpin :show="notesLoading">
          <NEmpty v-if="!notes.length && !notesLoading" description="还没有纸条" />
          <div v-else class="note-list">
            <div v-for="n in notes" :key="n.id" class="note-item" :class="{ unread: !n.read_at }">
              <div class="note-content">{{ n.content }}</div>
              <div class="note-meta">
                <span class="note-time">{{ relativeTime(n.created_at) }}</span>
                <NTag v-if="n.read_at" size="tiny" :bordered="false" type="success">已读</NTag>
                <NTag v-else size="tiny" :bordered="false" type="warning">未读</NTag>
              </div>
            </div>
          </div>
        </NSpin>
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.room-page {
  max-width: 520px;
  margin: 0 auto;
  padding: 24px 16px;
  font-family: 'Georgia', 'Noto Serif SC', serif;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 20px;
  padding: 0 4px;
}

.page-title {
  font-size: 22px;
  font-weight: 600;
  color: #4a3535;
  letter-spacing: -0.5px;
}

.subtitle {
  font-size: 12px;
  color: #b8a8a3;
  margin-left: 10px;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-bottom: 12px;
}

/* ── Traces ── */
.trace-list {
  position: relative;
  padding-left: 20px;
}

.trace-list::before {
  content: '';
  position: absolute;
  left: 6px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: #f0e0dc;
}

.trace-item {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 8px 0;
}

.trace-dot {
  position: absolute;
  left: -17px;
  top: 14px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c094a8;
  flex-shrink: 0;
}

.trace-body {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.trace-action {
  font-size: 14px;
  color: #4a3535;
}

.trace-tag {
  font-size: 10px;
}

.trace-scribble {
  width: 100%;
  margin: 4px 0 0;
  font-size: 13px;
  color: #8b7082;
  font-style: italic;
  line-height: 1.5;
}

.trace-time {
  font-size: 11px;
  color: #c4b0ab;
}

/* ── Preview ── */
.preview-card {
  padding: 16px;
  border: 1px solid #f0e0dc;
  border-radius: 12px;
  background: #fdf6f4;
}

.charge-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.charge-label {
  font-size: 11px;
  color: #b8a8a3;
  letter-spacing: 1px;
  text-transform: uppercase;
  flex-shrink: 0;
}

.charge-track {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: #f0e0dc;
  overflow: hidden;
}

.charge-fill {
  height: 100%;
  border-radius: 2px;
  background: #c094a8;
  transition: width 0.4s ease;
}

.charge-value {
  font-size: 12px;
  color: #8b7082;
  font-weight: 500;
  min-width: 32px;
  text-align: right;
}

.scene-text {
  font-size: 14px;
  line-height: 1.8;
  color: #4a3535;
  white-space: pre-wrap;
  margin-bottom: 12px;
}

.layer-details {
  margin-top: 8px;
  border-top: 1px solid #f0e0dc;
  padding-top: 8px;
}

.layer-details summary {
  font-size: 12px;
  color: #b8a8a3;
  cursor: pointer;
  user-select: none;
}

.layer-pre {
  font-size: 12px;
  color: #6a5a54;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.6;
  margin-top: 8px;
  padding: 8px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #f0e0dc;
}

/* ── Notes ── */
.note-compose {
  margin-bottom: 16px;
}

.send-btn {
  margin-top: 8px;
}

.unread-count {
  font-size: 12px;
  color: #c094a8;
  font-weight: 500;
}

.note-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.note-item {
  padding: 12px 14px;
  border: 1px solid #f0e0dc;
  border-radius: 10px;
  background: #fff;
  transition: border-color 0.2s;
}

.note-item.unread {
  border-color: #c094a8;
  background: #fdf6f4;
}

.note-content {
  font-size: 14px;
  color: #4a3535;
  line-height: 1.6;
  white-space: pre-wrap;
}

.note-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.note-time {
  font-size: 11px;
  color: #c4b0ab;
}
</style>
