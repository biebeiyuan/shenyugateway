<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NEmpty,
  NInput,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  createDrawerNote,
  fetchDrawerNotes,
  fetchPins,
  fetchRoomPreview,
  fetchRoomTraces,
  fetchScribbles,
  type DrawerNote,
  type RoomPin,
  type RoomScribble,
  type RoomTool,
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

const TOOL_LABELS: Record<string, string> = {
  room_drawer_notes: '纸条抽屉',
  room_wooden_box: '木盒子',
  room_star_map: '星图墙',
  room_notebook: '笔记本',
  room_scribble: '窗台本子',
  room_wall_pins: '墙上便签',
  room_conflict_shelf: '矛盾书架',
  room_sit_by_window: '窗边椅子',
  room_octopus_pillow: '章鱼抱枕',
  room_locked_drawer: '上锁抽屉',
}

interface RoomPreview {
  charge: number
  mode: string
  layers: Record<string, string>
  room_tools?: RoomTool[]
}

const message = useMessage()

const loading = ref(false)
const previewLoading = ref(false)
const tracesLoading = ref(false)
const notesLoading = ref(false)
const noteSending = ref(false)

const preview = ref<RoomPreview | null>(null)
const traces = ref<RoomTrace[]>([])
const notes = ref<DrawerNote[]>([])
const scribbles = ref<RoomScribble[]>([])
const pins = ref<RoomPin[]>([])
const notesUnread = ref(0)
const noteDraft = ref('')

const visibleTools = computed(() => preview.value?.room_tools || [])
const recentNotes = computed(() => notes.value.slice(0, 5))
const recentTraces = computed(() => traces.value.slice(0, 10))
const recentScribbles = computed(() => scribbles.value.slice(0, 5))
const activePins = computed(() => pins.value.filter((pin) => !pin.done).slice(0, 6))
const visibleToolNames = computed(() => visibleTools.value.map((tool) => tool.function?.name || '').filter(Boolean))

onMounted(() => {
  loadRoom()
})

async function loadRoom() {
  loading.value = true
  await Promise.allSettled([
    loadPreview(),
    loadTraces(),
    loadNotes(),
    loadScribbles(),
    loadPins(),
  ])
  loading.value = false
}

async function loadPreview() {
  previewLoading.value = true
  try {
    preview.value = await fetchRoomPreview()
  } catch {
    preview.value = null
  } finally {
    previewLoading.value = false
  }
}

async function loadTraces() {
  tracesLoading.value = true
  try {
    const data = await fetchRoomTraces(50)
    traces.value = data.traces
  } catch {
    traces.value = []
  } finally {
    tracesLoading.value = false
  }
}

async function loadNotes() {
  notesLoading.value = true
  try {
    const data = await fetchDrawerNotes(30)
    notes.value = data.notes
    notesUnread.value = data.unread
  } catch {
    notes.value = []
    notesUnread.value = 0
  } finally {
    notesLoading.value = false
  }
}

async function loadScribbles() {
  try {
    const data = await fetchScribbles(20)
    scribbles.value = data.scribbles
  } catch {
    // The side panels are auxiliary; keep the room usable if these fail.
  }
}

async function loadPins() {
  try {
    const data = await fetchPins(false)
    pins.value = data.pins
  } catch {
    // The side panels are auxiliary; keep the room usable if these fail.
  }
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

async function refreshEverything() {
  await loadRoom()
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

function toolLabel(name: string) {
  return TOOL_LABELS[name] || name.replace(/^room_/, '')
}

function chargePercent(c?: number) {
  return Math.round(Math.max(0, Math.min(1, c || 0)) * 100)
}

function chargeLabel(c?: number) {
  const percent = chargePercent(c)
  if (percent < 30) return '安静'
  if (percent < 70) return '有光'
  return '很亮'
}
</script>

<template>
  <div class="room-page">
    <header class="room-header">
      <div>
        <div class="eyebrow">Shenyu Room</div>
        <h1 class="page-title">房间</h1>
      </div>
      <div class="header-actions">
        <NTag size="small" :bordered="false" class="state-tag">
          {{ chargeLabel(preview?.charge) }} · {{ chargePercent(preview?.charge) }}%
        </NTag>
        <NButton size="small" quaternary :loading="loading" @click="refreshEverything">刷新</NButton>
      </div>
    </header>

    <NSpin :show="loading">
      <section class="room-hero">
        <div class="window-panel">
          <div class="panel-topline">
            <div>
              <span class="panel-kicker">窗外</span>
              <h2>今天房间里看见的东西</h2>
            </div>
            <NButton size="small" quaternary :loading="previewLoading" @click="loadPreview">换一阵风</NButton>
          </div>

          <div class="charge-row">
            <span>charge</span>
            <div class="charge-track">
              <div class="charge-fill" :style="{ width: chargePercent(preview?.charge) + '%' }" />
            </div>
            <strong>{{ chargePercent(preview?.charge) }}%</strong>
          </div>

          <p v-if="preview?.layers?.slow" class="scene-text">{{ preview.layers.slow }}</p>
          <NEmpty v-else description="窗还没打开" class="soft-empty" />

          <div class="visible-tools">
            <span class="object-label">可见物件</span>
            <div v-if="visibleToolNames.length" class="object-chips">
              <NTag
                v-for="name in visibleToolNames"
                :key="name"
                size="small"
                :bordered="false"
                class="object-chip"
              >
                {{ toolLabel(name) }}
              </NTag>
            </div>
            <span v-else class="muted">还没有物件清单</span>
          </div>
        </div>

        <aside class="drawer-panel">
          <div class="panel-topline compact">
            <div>
              <span class="panel-kicker">中层抽屉</span>
              <h2>纸条</h2>
            </div>
            <NTag v-if="notesUnread" size="small" :bordered="false" type="warning">{{ notesUnread }} 未读</NTag>
          </div>

          <div class="note-compose">
            <NInput
              v-model:value="noteDraft"
              type="textarea"
              placeholder="写一张纸条塞进抽屉..."
              :autosize="{ minRows: 3, maxRows: 6 }"
              :disabled="noteSending"
            />
            <NButton
              size="small"
              type="primary"
              @click="sendNote"
              :loading="noteSending"
              :disabled="!noteDraft.trim()"
            >
              塞进去
            </NButton>
          </div>

          <NSpin :show="notesLoading">
            <div v-if="recentNotes.length" class="paper-stack">
              <article v-for="note in recentNotes" :key="note.id" class="paper-note" :class="{ unread: !note.read_at }">
                <p>{{ note.content }}</p>
                <span>{{ relativeTime(note.created_at) }}</span>
              </article>
            </div>
            <NEmpty v-else description="抽屉里还没有纸条" class="soft-empty" />
          </NSpin>
        </aside>
      </section>

      <section class="room-grid">
        <section class="room-section traces-section">
          <div class="section-head">
            <div>
              <span class="panel-kicker">最近</span>
              <h2>足迹</h2>
            </div>
            <NButton size="small" quaternary :loading="tracesLoading" @click="loadTraces">刷新</NButton>
          </div>

          <NSpin :show="tracesLoading">
            <div v-if="recentTraces.length" class="trace-list">
              <div v-for="trace in recentTraces" :key="trace.id" class="trace-item">
                <div class="trace-dot" />
                <div class="trace-body">
                  <div class="trace-line">
                    <span>{{ traceLabel(trace.action) }}</span>
                    <NTag v-if="trace.detail?.tag" size="tiny" :bordered="false">{{ trace.detail.tag }}</NTag>
                  </div>
                  <p v-if="trace.scribble">{{ trace.scribble }}</p>
                  <time>{{ relativeTime(trace.created_at) }}</time>
                </div>
              </div>
            </div>
            <NEmpty v-else description="还没有足迹" class="soft-empty" />
          </NSpin>
        </section>

        <section class="room-section hand-section">
          <div class="section-head">
            <div>
              <span class="panel-kicker">手边</span>
              <h2>窗台本子和便签</h2>
            </div>
          </div>

          <div class="side-columns">
            <div class="mini-panel">
              <h3>窗台本子</h3>
              <div v-if="recentScribbles.length" class="mini-list">
                <article v-for="item in recentScribbles" :key="item.id">
                  <p>{{ item.content }}</p>
                  <span>{{ relativeTime(item.created_at) }}</span>
                </article>
              </div>
              <NEmpty v-else description="还没写过" class="soft-empty small" />
            </div>

            <div class="mini-panel">
              <h3>墙上便签</h3>
              <div v-if="activePins.length" class="mini-list">
                <article v-for="pin in activePins" :key="pin.id">
                  <p>{{ pin.content }}</p>
                  <span>{{ relativeTime(pin.created_at) }}</span>
                </article>
              </div>
              <NEmpty v-else description="没有未完成便签" class="soft-empty small" />
            </div>
          </div>
        </section>
      </section>

      <details v-if="preview?.layers?.tool_policy || preview?.layers?.stable" class="debug-drawer">
        <summary>房间原始提示</summary>
        <pre v-if="preview?.layers?.tool_policy">{{ preview.layers.tool_policy }}</pre>
        <pre v-if="preview?.layers?.stable">{{ preview.layers.stable }}</pre>
      </details>
    </NSpin>
  </div>
</template>

<style scoped>
.room-page {
  --room-paper: #fffdf8;
  --room-ink: #302b28;
  --room-muted: #8f817a;
  --room-line: #e7dad1;
  --room-sea: #466c7a;
  --room-moss: #5f765b;
  --room-rose: #b77a8c;
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 18px 40px;
  color: var(--room-ink);
}

.room-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.eyebrow,
.panel-kicker,
.object-label {
  display: block;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 11px;
  color: var(--room-sea);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-title {
  margin-top: 4px;
  font-size: 28px;
  font-weight: 600;
  color: var(--room-ink);
  letter-spacing: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.state-tag {
  color: var(--room-sea) !important;
}

.room-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 0.85fr);
  gap: 16px;
  align-items: stretch;
}

.window-panel,
.drawer-panel,
.room-section,
.mini-panel,
.debug-drawer {
  border: 1px solid var(--room-line);
  background: var(--room-paper);
  border-radius: 8px;
}

.window-panel,
.drawer-panel,
.room-section {
  padding: 18px;
}

.drawer-panel {
  background: #f7fbfb;
}

.panel-topline,
.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-topline.compact {
  align-items: center;
}

h2 {
  margin-top: 3px;
  font-size: 18px;
  font-weight: 600;
  color: var(--room-ink);
  letter-spacing: 0;
}

.charge-row {
  display: grid;
  grid-template-columns: auto minmax(120px, 1fr) auto;
  gap: 10px;
  align-items: center;
  margin: 10px 0 18px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 12px;
  color: var(--room-muted);
}

.charge-track {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #e7e4dc;
}

.charge-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--room-sea);
  transition: width 0.35s ease;
}

.scene-text {
  min-height: 132px;
  max-width: 720px;
  margin: 0 0 18px;
  white-space: pre-wrap;
  font-size: 16px;
  line-height: 1.9;
  color: var(--room-ink);
}

.visible-tools {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 10px 12px;
  align-items: start;
  padding-top: 14px;
  border-top: 1px solid var(--room-line);
}

.object-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.object-chip {
  background: #eef5f4 !important;
  color: var(--room-sea) !important;
}

.muted {
  font-size: 13px;
  color: var(--room-muted);
}

.note-compose {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
}

.note-compose :deep(.n-button) {
  justify-self: start;
}

.paper-stack,
.mini-list {
  display: grid;
  gap: 9px;
}

.paper-note,
.mini-list article {
  padding: 11px 12px;
  border: 1px solid #e6ddd6;
  border-radius: 7px;
  background: #fff;
}

.paper-note.unread {
  border-color: var(--room-rose);
  background: #fff8f8;
}

.paper-note p,
.mini-list p {
  margin: 0;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  color: var(--room-ink);
}

.paper-note span,
.mini-list span,
.trace-body time {
  display: inline-block;
  margin-top: 7px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 11px;
  color: var(--room-muted);
}

.room-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr);
  gap: 16px;
  margin-top: 16px;
}

.trace-list {
  position: relative;
  display: grid;
  gap: 0;
  padding-left: 16px;
}

.trace-list::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 8px;
  bottom: 8px;
  width: 1px;
  background: var(--room-line);
}

.trace-item {
  position: relative;
  padding: 7px 0 12px;
}

.trace-dot {
  position: absolute;
  left: -15px;
  top: 14px;
  width: 8px;
  height: 8px;
  border: 2px solid var(--room-paper);
  border-radius: 50%;
  background: var(--room-moss);
}

.trace-body {
  min-width: 0;
}

.trace-line {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  font-size: 14px;
  color: var(--room-ink);
}

.trace-body p {
  margin: 5px 0 0;
  white-space: pre-wrap;
  color: var(--room-muted);
  font-size: 13px;
  line-height: 1.55;
}

.side-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.mini-panel {
  padding: 14px;
  background: #fff;
}

.mini-panel h3 {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--room-sea);
}

.soft-empty {
  padding: 18px 0;
}

.soft-empty.small {
  padding: 10px 0;
}

.debug-drawer {
  margin-top: 16px;
  padding: 12px 14px;
  background: #fff;
}

.debug-drawer summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--room-muted);
  user-select: none;
}

.debug-drawer pre {
  margin-top: 10px;
  padding: 10px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid var(--room-line);
  border-radius: 6px;
  background: #fbfaf7;
  color: #665d58;
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 860px) {
  .room-page {
    padding: 22px 12px 32px;
  }

  .room-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }

  .room-hero,
  .room-grid,
  .side-columns {
    grid-template-columns: 1fr;
  }

  .visible-tools {
    grid-template-columns: 1fr;
  }
}
</style>
