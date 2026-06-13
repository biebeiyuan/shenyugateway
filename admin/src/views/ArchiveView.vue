<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NCheckbox, NInput, NModal, NSelect, NSpin, useMessage } from 'naive-ui'
import {
  createConflictBook,
  fetchArchiveDays,
  fetchArchiveMessages,
  fetchArchiveThreads,
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

async function selectDay(date: string) {
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
    <div class="toolbar">
      <NSelect v-model:value="thread" :options="threadOptions" class="thread-select" size="small" />
      <div class="month-nav">
        <NButton size="tiny" quaternary @click="shiftMonth(-1)">←</NButton>
        <span class="month-label">{{ month }}</span>
        <NButton size="tiny" quaternary @click="shiftMonth(1)">→</NButton>
      </div>
      <div class="toolbar-right">
        <NButton size="small" :type="selecting ? 'warning' : 'default'" @click="toggleSelecting">
          {{ selecting ? '取消选取' : '选取消息' }}
        </NButton>
        <NButton v-if="selecting" size="small" type="primary" :disabled="!selectedIds.size" @click="openClipModal">
          截入矛盾书（{{ selectedIds.size }}）
        </NButton>
      </div>
    </div>

    <div class="body">
      <aside class="day-list">
        <div v-if="!days.length" class="empty">这个月没有记录</div>
        <button
          v-for="day in days"
          :key="day.date"
          class="day-item"
          :class="{ active: day.date === selectedDate }"
          @click="selectDay(day.date)"
        >
          <span>{{ day.date.slice(5) }}</span>
          <span class="day-count">{{ day.count }}</span>
        </button>
      </aside>

      <section class="messages">
        <NSpin :show="loading">
          <div v-if="!messages.length && !loading" class="empty">选一个日期</div>
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
          </div>
        </NSpin>
      </section>
    </div>

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
.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.thread-select {
  width: 130px;
}

.month-nav {
  display: flex;
  align-items: center;
  gap: 6px;
}

.month-label {
  font-size: 13px;
  color: #3d3535;
  min-width: 62px;
  text-align: center;
}

.toolbar-right {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.body {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.day-list {
  width: 110px;
  flex-shrink: 0;
  background: #fff;
  border: 1px solid #f0ece8;
  border-radius: 12px;
  padding: 6px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}

.day-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 7px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 12.5px;
  color: #3d3535;
  cursor: pointer;
}

.day-item:hover {
  background: #faf8f5;
}

.day-item.active {
  background: #f1eef8;
  color: #9b8ec4;
  font-weight: 600;
}

.day-count {
  font-size: 10px;
  color: #b0a8a0;
}

.messages {
  flex: 1;
  background: #fff;
  border: 1px solid #f0ece8;
  border-radius: 12px;
  padding: 16px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}

.empty {
  color: #b0a8a0;
  font-size: 12.5px;
  text-align: center;
  padding: 30px 0;
}

.msg {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  margin-bottom: 8px;
}

.msg.user {
  background: #faf8f5;
}

.msg.assistant {
  background: #f5f3fa;
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
  margin-bottom: 4px;
}

.msg-who {
  font-size: 12px;
  font-weight: 600;
  color: #9b8ec4;
}

.msg.user .msg-who {
  color: #c8956a;
}

.msg-time,
.msg-thread {
  font-size: 10.5px;
  color: #b0a8a0;
}

.msg-content {
  font-size: 13px;
  line-height: 1.7;
  color: #3d3535;
  white-space: pre-wrap;
  word-break: break-word;
}

.clip-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.clip-preview {
  background: #faf8f5;
  border: 1px solid #f0ece8;
  border-radius: 10px;
  padding: 10px 12px;
}

.clip-preview-title {
  font-size: 11px;
  color: #b0a8a0;
  margin-bottom: 6px;
}

.clip-preview-text {
  font-size: 12px;
  line-height: 1.6;
  color: #3d3535;
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
