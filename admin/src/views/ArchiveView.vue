<script setup lang="ts">
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { NButton, NCheckbox, NInput, NModal, NPopconfirm, NSelect, NSpin, useMessage } from 'naive-ui'
import {
  createConflictBook,
  fetchArchiveDays,
  fetchArchiveMessages,
  fetchArchiveThreads,
  softDeleteArchiveMessage,
  type ArchiveDay,
  type ArchiveMessage,
  type ArchiveThread,
} from '@/api/archive'

const message = useMessage()

const threads = ref<ArchiveThread[]>([])
const thread = ref('')
const month = ref(localDateStr().slice(0, 7))
const days = ref<ArchiveDay[]>([])
const selectedDate = ref('')
const messages = ref<ArchiveMessage[]>([])
const loading = ref(false)
const calendarOpen = ref(false)
const msgListRef = ref<HTMLElement>()

const selecting = ref(false)
const selectedIds = ref<Set<string>>(new Set())

const showClipModal = ref(false)
const clipTitle = ref('')
const clipNotes = ref('')
const clipSaving = ref(false)

const threadOptions = computed(() =>
  threads.value.map((t) => ({
    label: t.thread === 'main' ? '主聊天' : t.thread === 'hisense' ? '海信' : t.thread,
    value: t.thread,
  })),
)

const threadLabel = (key: string) => (key === 'main' ? '主聊天' : key === 'hisense' ? '海信' : key)

function toLocalHHMM(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function toLocalDateTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function localDateStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const selectedMessages = computed(() =>
  messages.value.filter((m) => selectedIds.value.has(m.id)),
)

const daySet = computed(() => {
  const map = new Map<string, number>()
  for (const d of days.value) map.set(d.date, d.count)
  return map
})

const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日']

const calendarCells = computed(() => {
  const [y, m] = month.value.split('-').map(Number)
  const firstDay = new Date(y, m - 1, 1)
  let startWeekday = firstDay.getDay() - 1
  if (startWeekday < 0) startWeekday = 6
  const daysInMonth = new Date(y, m, 0).getDate()
  const cells: Array<{ day: number; date: string; count: number } | null> = []
  for (let i = 0; i < startWeekday; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${month.value}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, date: dateStr, count: daySet.value.get(dateStr) || 0 })
  }
  return cells
})

const monthLabel = computed(() => {
  const [y, m] = month.value.split('-').map(Number)
  const monthNames = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']
  return `${monthNames[m - 1]} ${y}`
})

const selectedDateLabel = computed(() => {
  if (!selectedDate.value) return ''
  const [, m, d] = selectedDate.value.split('-')
  return `${parseInt(m)}月${parseInt(d)}日`
})

const totalThisMonth = computed(() => days.value.reduce((sum, d) => sum + d.count, 0))

onMounted(async () => {
  try {
    threads.value = await fetchArchiveThreads()
    if (threads.value.length) {
      const sorted = [...threads.value].sort((a, b) => b.count - a.count)
      thread.value = sorted[0].thread
    }
  } catch {
    message.error('加载线程列表失败')
  }
  await loadDays()
})

watch([thread, month], loadDays)

async function loadDays() {
  if (!thread.value) return
  try {
    days.value = await fetchArchiveDays(thread.value, month.value)
    if (days.value.length && !days.value.some((d) => d.date === selectedDate.value)) {
      selectedDate.value = days.value[days.value.length - 1].date
      await loadMessages()
    } else if (!days.value.length) {
      selectedDate.value = ''
      messages.value = []
    }
  } catch {
    message.error('加载日期失败')
  }
}

async function selectDay(date: string, count: number) {
  if (!count) return
  selectedDate.value = date
  calendarOpen.value = false
  await loadMessages()
}

async function loadMessages() {
  if (!selectedDate.value) return
  loading.value = true
  try {
    messages.value = await fetchArchiveMessages({ thread: thread.value, date: selectedDate.value, limit: 500 })
    await nextTick()
    if (msgListRef.value) msgListRef.value.scrollTop = msgListRef.value.scrollHeight
  } catch {
    message.error('加载消息失败')
  } finally {
    loading.value = false
  }
}

function shiftMonth(delta: number) {
  const [y, m] = month.value.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  month.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function toggleSelecting() {
  selecting.value = !selecting.value
  if (!selecting.value) selectedIds.value = new Set()
}

function toggleMessage(id: string, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedIds.value = next
}

async function deleteMessage(id: string) {
  try {
    await softDeleteArchiveMessage(id)
    messages.value = messages.value.filter((m) => m.id !== id)
    selectedIds.value.delete(id)
    message.success('已删除')
  } catch {
    message.error('删除失败')
  }
}

function openClipModal() {
  if (!selectedMessages.value.length) {
    message.warning('先选中要截取的消息')
    return
  }
  clipTitle.value = ''
  clipNotes.value = ''
  showClipModal.value = true
}

function buildOriginalText(items: ArchiveMessage[]): string {
  return items
    .map((m) => {
      const who = m.role === 'user' ? '圆圆' : '沈予'
      const when = toLocalDateTime(m.event_at || '')
      return `[${when}] ${who}：\n${m.content}`
    })
    .join('\n\n')
}

async function saveClip() {
  if (!clipTitle.value.trim()) {
    message.warning('给这本书起个名字')
    return
  }
  const items = [...selectedMessages.value].sort((a, b) => (a.event_at || '').localeCompare(b.event_at || ''))
  clipSaving.value = true
  try {
    const result = await createConflictBook({
      title: clipTitle.value.trim(),
      original_text: buildOriginalText(items),
      thread: thread.value,
      span_start: items[0]?.event_at ?? undefined,
      span_end: items[items.length - 1]?.event_at ?? undefined,
      message_refs: items.map((m) => m.id),
      user_notes: clipNotes.value.trim() || undefined,
    })
    if (result.ok) {
      message.success('已截入来历书。原文从这一刻起冻结。')
      showClipModal.value = false
      toggleSelecting()
    } else {
      message.error(result.error || '保存失败')
    }
  } catch {
    message.error('保存失败')
  } finally {
    clipSaving.value = false
  }
}
</script>

<template>
  <div class="archive-view" data-testid="page-archive">
    <!-- Control Panel (calendar + thread + tools) -->
    <div class="control-panel" :class="{ collapsed: !calendarOpen }">
      <!-- Collapsed bar -->
      <div class="control-bar">
        <button class="cal-toggle" @click="calendarOpen = !calendarOpen">
          <span class="cal-toggle-icon" :class="{ open: calendarOpen }">&#9662;</span>
        </button>
        <span v-if="selectedDate" class="bar-date">{{ selectedDateLabel }}</span>
        <span v-if="selectedDate" class="bar-sep">&#183;</span>
        <span class="bar-month">{{ monthLabel }}</span>
        <span v-if="totalThisMonth" class="bar-count">{{ totalThisMonth }} 条</span>
        <div class="bar-right">
          <button class="cal-arrow" @click.stop="shiftMonth(-1)">&lsaquo;</button>
          <button class="cal-arrow" @click.stop="shiftMonth(1)">&rsaquo;</button>
        </div>
      </div>

      <!-- Expanded content -->
      <Transition name="panel-slide">
        <div v-if="calendarOpen" class="control-body">
          <!-- Calendar grid -->
          <div class="cal-weekdays">
            <span v-for="w in weekdayLabels" :key="w" class="cal-wd">{{ w }}</span>
          </div>
          <div class="cal-grid">
            <div
              v-for="(cell, idx) in calendarCells"
              :key="idx"
              class="cal-cell"
              :class="{
                empty: !cell,
                'has-data': cell && cell.count > 0,
                active: cell && cell.date === selectedDate,
                today: cell && cell.date === localDateStr(),
              }"
              @click="cell && selectDay(cell.date, cell.count)"
            >
              <template v-if="cell">
                <span class="cal-day-num">{{ cell.day }}</span>
                <span v-if="cell.count" class="cal-dot"></span>
              </template>
            </div>
          </div>

          <!-- Thread + tools row -->
          <div class="control-tools">
            <NSelect v-model:value="thread" :options="threadOptions" class="thread-select" size="small" />
            <div class="tools-right">
              <NButton size="small" :type="selecting ? 'warning' : 'default'" @click="toggleSelecting">
                {{ selecting ? '取消' : '选取' }}
              </NButton>
              <NButton v-if="selecting" size="small" type="primary" :disabled="!selectedIds.size" @click="openClipModal">
                截入来历书（{{ selectedIds.size }}）
              </NButton>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <!-- Chat Messages -->
    <section ref="msgListRef" class="chat-panel">
      <NSpin :show="loading">
        <div v-if="!messages.length && !loading" class="empty">
          <div class="empty-icon">&#9825;</div>
          <div>{{ selectedDate ? '这天很安静' : '选一天看看' }}</div>
        </div>

        <div
          v-for="msg in messages"
          :key="msg.id"
          class="bubble-row"
          :class="msg.role"
        >
          <NCheckbox
            v-if="selecting"
            class="bubble-check"
            :checked="selectedIds.has(msg.id)"
            @update:checked="(checked: boolean) => toggleMessage(msg.id, checked)"
          />
          <div class="bubble" :class="msg.role">
            <div class="bubble-content">{{ msg.content }}</div>
            <div class="bubble-meta">
              <span class="bubble-time">{{ toLocalHHMM(msg.event_at || '') }}</span>
            </div>
            <NPopconfirm @positive-click="deleteMessage(msg.id)">
              <template #trigger>
                <button class="bubble-delete">&times;</button>
              </template>
              删除这条记录？
            </NPopconfirm>
          </div>
        </div>
      </NSpin>
    </section>

    <!-- Clip Modal -->
    <NModal v-model:show="showClipModal" preset="card" title="截入来历书" style="max-width: 560px">
      <div class="clip-form">
        <NInput v-model:value="clipTitle" placeholder="书名，例如：关于重roll的那次掰扯" />
        <NInput
          v-model:value="clipNotes"
          type="textarea"
          :rows="3"
          placeholder="你的注（可选，之后还能编辑）"
        />
        <div class="clip-preview">
          <div class="clip-preview-title">原文预览（保存后冻结，谁都不能改）</div>
          <pre class="clip-preview-text">{{ buildOriginalText([...selectedMessages].sort((a, b) => (a.event_at || '').localeCompare(b.event_at || ''))) }}</pre>
        </div>
        <div class="clip-actions">
          <NButton @click="showClipModal = false">取消</NButton>
          <NButton type="primary" :loading="clipSaving" @click="saveClip">冻结并保存</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.archive-view {
  max-width: 520px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 70px);
}

/* ── Control Panel ── */
.control-panel {
  background: #fff;
  border: 1px solid #f0e0dc;
  border-radius: 16px;
  padding: 12px 16px;
  margin-bottom: 10px;
  flex-shrink: 0;
  transition: 0.25s ease;
}

/* Collapsed bar */
.control-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
}

.cal-toggle {
  width: 24px;
  height: 24px;
  border: none;
  background: #fdf0ed;
  border-radius: 7px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: 0.2s;
  color: #c4b0ab;
  font-size: 10px;
  flex-shrink: 0;
}

.cal-toggle:hover {
  background: #f8e4df;
  color: #c094a8;
}

.cal-toggle-icon {
  display: inline-block;
  transition: transform 0.25s ease;
}

.cal-toggle-icon.open {
  transform: rotate(0deg);
}

.cal-toggle-icon:not(.open) {
  transform: rotate(-90deg);
}

.bar-date {
  font-size: 13px;
  font-weight: 600;
  color: #8b7082;
}

.bar-sep {
  color: #d4c0bb;
  font-size: 14px;
}

.bar-month {
  font-size: 12px;
  color: #b8a8a3;
}

.bar-count {
  font-size: 11px;
  color: #c4b0ab;
  font-style: italic;
}

.bar-right {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.cal-arrow {
  width: 26px;
  height: 26px;
  border: 1px solid #f2ddd8;
  background: #fff;
  border-radius: 8px;
  cursor: pointer;
  font-size: 15px;
  color: #c094a8;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: 0.2s;
}

.cal-arrow:hover {
  background: #fdf0ed;
  border-color: #e8c4bc;
}

/* Expanded body */
.control-body {
  padding-top: 12px;
  overflow: hidden;
}

.cal-weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: 4px;
}

.cal-wd {
  text-align: center;
  font-size: 10px;
  color: #c4b0ab;
  font-weight: 500;
  padding: 2px 0;
}

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 3px;
}

.cal-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 36px;
  border-radius: 10px;
  cursor: default;
  transition: all 0.2s ease;
}

.cal-cell.empty {
  pointer-events: none;
}

.cal-cell.has-data {
  cursor: pointer;
  background: #fdf6f4;
}

.cal-cell.has-data:hover {
  background: #f8e4df;
  transform: scale(1.06);
}

.cal-cell.active {
  background: #c094a8;
  box-shadow: 0 2px 8px rgba(192, 148, 168, 0.25);
}

.cal-cell.active .cal-day-num {
  color: #fff;
  font-weight: 600;
}

.cal-cell.active .cal-dot {
  background: rgba(255, 255, 255, 0.7);
}

.cal-cell.today:not(.active) {
  box-shadow: inset 0 0 0 1.5px #e8c4bc;
}

.cal-day-num {
  font-size: 12px;
  color: #4a3535;
  line-height: 1;
  font-family: -apple-system, 'Segoe UI', sans-serif;
}

.cal-cell:not(.has-data):not(.active) .cal-day-num {
  color: #ddd4d0;
}

.cal-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #c094a8;
  margin-top: 2px;
}

/* Tools row inside panel */
.control-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f5ece9;
}

.thread-select {
  width: 120px;
}

.tools-right {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

/* Transition */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: all 0.25s ease;
  max-height: 340px;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
}

/* ── Chat Panel ── */
.chat-panel {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px 16px;
}

.empty {
  color: #c4b0ab;
  font-size: 13px;
  text-align: center;
  padding: 60px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-style: italic;
}

.empty-icon {
  font-size: 28px;
  color: #e8c4bc;
}

/* ── Bubble Messages ── */
.bubble-row {
  display: flex;
  align-items: flex-end;
  margin-bottom: 6px;
  gap: 6px;
}

.bubble-row.user {
  justify-content: flex-end;
}

.bubble-row.assistant {
  justify-content: flex-start;
}

.bubble-check {
  flex-shrink: 0;
  margin-bottom: 8px;
}

.bubble {
  position: relative;
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 18px;
  font-size: 13.5px;
  line-height: 1.7;
  word-break: break-word;
  white-space: pre-wrap;
  transition: 0.15s;
}

.bubble.user {
  background: linear-gradient(135deg, #f0e4df 0%, #f5ece9 100%);
  border-bottom-right-radius: 6px;
  color: #4a3535;
}

.bubble.assistant {
  background: #fff;
  border: 1px solid #f0e0dc;
  border-bottom-left-radius: 6px;
  color: #4a3535;
}

.bubble:hover {
  box-shadow: 0 2px 12px rgba(139, 112, 130, 0.08);
}

.bubble-content {
  /* text content */
}

.bubble-meta {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

.bubble-time {
  font-size: 10px;
  color: #c4b0ab;
}

.bubble.user .bubble-time {
  color: #bba89e;
}

.bubble-delete {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 18px;
  height: 18px;
  border: none;
  background: transparent;
  color: #d4726a;
  font-size: 14px;
  line-height: 1;
  border-radius: 5px;
  cursor: pointer;
  opacity: 0;
  transition: 0.15s;
}

.bubble:hover .bubble-delete {
  opacity: 0.35;
}

.bubble-delete:hover {
  opacity: 1 !important;
  background: #fdf2f0;
}

/* ── Clip Modal ── */
.clip-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.clip-preview {
  background: #fdf6f4;
  border: 1px solid #f2ddd8;
  border-radius: 12px;
  padding: 12px 14px;
}

.clip-preview-title {
  font-size: 11px;
  color: #c4b0ab;
  margin-bottom: 6px;
}

.clip-preview-text {
  font-size: 12px;
  line-height: 1.6;
  color: #4a3535;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
  font-family: inherit;
}

.clip-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
