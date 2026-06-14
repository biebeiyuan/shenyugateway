<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
const thread = ref('main')
const month = ref(new Date().toISOString().slice(0, 7))
const days = ref<ArchiveDay[]>([])
const selectedDate = ref('')
const messages = ref<ArchiveMessage[]>([])
const loading = ref(false)
const calendarOpen = ref(true)

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
    if (threads.value.length && !threads.value.some((t) => t.thread === thread.value)) {
      thread.value = threads.value[0].thread
    }
  } catch {
    message.error('加载线程列表失败')
  }
  await loadDays()
})

watch([thread, month], loadDays)

async function loadDays() {
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
  await loadMessages()
}

async function loadMessages() {
  if (!selectedDate.value) return
  loading.value = true
  try {
    messages.value = await fetchArchiveMessages({ thread: thread.value, date: selectedDate.value, limit: 500 })
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
      const when = (m.event_at || '').slice(0, 16).replace('T', ' ')
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
      message.success('已截入矛盾书。原文从这一刻起冻结。')
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
  <div class="archive-view">
    <!-- Calendar Panel -->
    <div class="calendar-panel" :class="{ collapsed: !calendarOpen }">
      <div class="calendar-header">
        <button class="cal-toggle" @click="calendarOpen = !calendarOpen">
          <span class="cal-toggle-icon" :class="{ open: calendarOpen }">&#9662;</span>
        </button>
        <div class="cal-title-area">
          <span class="cal-title">{{ monthLabel }}</span>
          <span v-if="totalThisMonth" class="cal-subtitle">{{ totalThisMonth }} 条对话</span>
        </div>
        <div class="cal-nav">
          <button class="cal-arrow" @click="shiftMonth(-1)">&lsaquo;</button>
          <button class="cal-arrow" @click="shiftMonth(1)">&rsaquo;</button>
        </div>
      </div>

      <Transition name="calendar-slide">
        <div v-if="calendarOpen" class="calendar-body">
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
                today: cell && cell.date === new Date().toISOString().slice(0, 10),
              }"
              @click="cell && selectDay(cell.date, cell.count)"
            >
              <template v-if="cell">
                <span class="cal-day-num">{{ cell.day }}</span>
                <span v-if="cell.count" class="cal-dot"></span>
              </template>
            </div>
          </div>
        </div>
      </Transition>

      <div v-if="selectedDate" class="cal-selected-badge">
        <span class="badge-date">{{ selectedDateLabel }}</span>
        <span class="badge-sep">&#183;</span>
        <span class="badge-count">{{ messages.length }} 条</span>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <NSelect v-model:value="thread" :options="threadOptions" class="thread-select" size="small" />
      <div class="toolbar-right">
        <NButton size="small" :type="selecting ? 'warning' : 'default'" @click="toggleSelecting">
          {{ selecting ? '取消选取' : '选取消息' }}
        </NButton>
        <NButton v-if="selecting" size="small" type="primary" :disabled="!selectedIds.size" @click="openClipModal">
          截入矛盾书（{{ selectedIds.size }}）
        </NButton>
      </div>
    </div>

    <!-- Messages -->
    <section class="messages-panel">
      <NSpin :show="loading">
        <div v-if="!messages.length && !loading" class="empty">
          <div class="empty-icon">&#9825;</div>
          <div>{{ selectedDate ? '这天很安静' : '在日历上选一天' }}</div>
        </div>
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="msg"
          :class="msg.role"
        >
          <NCheckbox
            v-if="selecting"
            class="msg-check"
            :checked="selectedIds.has(msg.id)"
            @update:checked="(checked: boolean) => toggleMessage(msg.id, checked)"
          />
          <div class="msg-body">
            <div class="msg-meta">
              <span class="msg-who">{{ msg.role === 'user' ? '圆圆' : '沈予' }}</span>
              <span class="msg-time">{{ (msg.event_at || '').slice(11, 16) }}</span>
              <span class="msg-thread">{{ threadLabel(thread) }}</span>
            </div>
            <div class="msg-content">{{ msg.content }}</div>
          </div>
          <NPopconfirm @positive-click="deleteMessage(msg.id)">
            <template #trigger>
              <button class="msg-delete">&times;</button>
            </template>
            删除这条记录？
          </NPopconfirm>
        </div>
      </NSpin>
    </section>

    <!-- Clip Modal -->
    <NModal v-model:show="showClipModal" preset="card" title="截入矛盾书" style="max-width: 560px">
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
  max-width: 720px;
  margin: 0 auto;
}

/* Calendar Panel */
.calendar-panel {
  background: #fff;
  border: 1px solid #f2ddd8;
  border-radius: 18px;
  padding: 20px 22px;
  margin-bottom: 16px;
  transition: 0.3s ease;
  box-shadow: 0 2px 12px rgba(192, 148, 168, 0.06);
}

.calendar-panel.collapsed {
  padding-bottom: 16px;
}

.calendar-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cal-toggle {
  width: 26px;
  height: 26px;
  border: none;
  background: #fdf0ed;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: 0.2s;
  color: #c4b0ab;
  font-size: 11px;
}

.cal-toggle:hover {
  background: #f8e4df;
  color: #c094a8;
}

.cal-toggle-icon {
  display: inline-block;
  transition: transform 0.3s ease;
}

.cal-toggle-icon.open {
  transform: rotate(0deg);
}

.cal-toggle-icon:not(.open) {
  transform: rotate(-90deg);
}

.cal-title-area {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.cal-title {
  font-size: 15px;
  font-weight: 600;
  color: #4a3535;
  letter-spacing: -0.3px;
}

.cal-subtitle {
  font-size: 11.5px;
  color: #c4b0ab;
  font-style: italic;
}

.cal-nav {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.cal-arrow {
  width: 28px;
  height: 28px;
  border: 1px solid #f2ddd8;
  background: #fff;
  border-radius: 9px;
  cursor: pointer;
  font-size: 16px;
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

/* Calendar Body */
.calendar-body {
  margin-top: 16px;
  overflow: hidden;
}

.cal-weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: 6px;
}

.cal-wd {
  text-align: center;
  font-size: 10.5px;
  color: #c4b0ab;
  font-weight: 500;
  padding: 4px 0;
}

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.cal-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 40px;
  border-radius: 12px;
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
  transform: scale(1.08);
}

.cal-cell.active {
  background: #c094a8;
  box-shadow: 0 2px 10px rgba(192, 148, 168, 0.25);
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
  font-size: 12.5px;
  color: #4a3535;
  line-height: 1;
  font-family: -apple-system, 'Segoe UI', sans-serif;
}

.cal-cell:not(.has-data):not(.active) .cal-day-num {
  color: #ddd4d0;
}

.cal-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #c094a8;
  margin-top: 3px;
  animation: dot-breathe 3s ease-in-out infinite;
}

@keyframes dot-breathe {
  0%, 100% { opacity: 0.6; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.4); }
}

.cal-selected-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  padding: 6px 14px;
  background: linear-gradient(135deg, #fdf0ed 0%, #f8eef5 100%);
  border-radius: 20px;
  border: 1px solid #f2ddd8;
}

.badge-date {
  font-size: 12.5px;
  color: #9b7a8a;
  font-weight: 600;
}

.badge-sep {
  color: #d4c0bb;
}

.badge-count {
  font-size: 11px;
  color: #c4b0ab;
  font-style: italic;
}

/* Transition */
.calendar-slide-enter-active,
.calendar-slide-leave-active {
  transition: all 0.3s ease;
  max-height: 300px;
}

.calendar-slide-enter-from,
.calendar-slide-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
}

/* Toolbar */
.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.thread-select {
  width: 130px;
}

.toolbar-right {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

/* Messages */
.messages-panel {
  background: #fff;
  border: 1px solid #f2ddd8;
  border-radius: 18px;
  padding: 20px 22px;
  max-height: calc(100vh - 440px);
  overflow-y: auto;
  box-shadow: 0 2px 12px rgba(192, 148, 168, 0.06);
}

.empty {
  color: #c4b0ab;
  font-size: 13px;
  text-align: center;
  padding: 48px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-style: italic;
}

.empty-icon {
  font-size: 32px;
  color: #e8c4bc;
  animation: float 4s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-5px); }
}

.msg {
  display: flex;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 14px;
  margin-bottom: 8px;
  transition: 0.2s;
  border: 1px solid transparent;
}

.msg.user {
  background: #fdf6f4;
  border-color: #f8ebe7;
}

.msg.assistant {
  background: linear-gradient(135deg, #f8eef5 0%, #fdf6f4 100%);
  border-color: #f2ddd8;
}

.msg:hover {
  box-shadow: 0 2px 10px rgba(192, 148, 168, 0.08);
  transform: translateY(-1px);
}

.msg-check {
  margin-top: 3px;
}

.msg-body {
  flex: 1;
  min-width: 0;
}

.msg-meta {
  display: flex;
  gap: 8px;
  align-items: baseline;
  margin-bottom: 5px;
}

.msg-who {
  font-size: 12px;
  font-weight: 600;
  color: #c094a8;
}

.msg.user .msg-who {
  color: #c8956a;
}

.msg-time,
.msg-thread {
  font-size: 10.5px;
  color: #c4b0ab;
}

.msg-content {
  font-size: 13px;
  line-height: 1.75;
  color: #4a3535;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-delete {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: #d4726a;
  font-size: 16px;
  line-height: 1;
  border-radius: 6px;
  cursor: pointer;
  opacity: 0;
  transition: 0.15s;
  margin-top: 2px;
}

.msg:hover .msg-delete {
  opacity: 0.4;
}

.msg-delete:hover {
  opacity: 1 !important;
  background: #fdf2f0;
}

/* Clip Modal */
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
