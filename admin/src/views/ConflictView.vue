<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NButton, NInput, NModal, NPopconfirm, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import {
  deleteConflictBook,
  fetchConflictBook,
  fetchConflictBooks,
  patchConflictBook,
  type ConflictBookDetail,
  type ConflictBookSummary,
} from '@/api/archive'

const message = useMessage()

const books = ref<ConflictBookSummary[]>([])
const loading = ref(false)

const showDetail = ref(false)
const detail = ref<ConflictBookDetail | null>(null)
const detailLoading = ref(false)

const editTitle = ref('')
const editNotes = ref('')
const editEpilogue = ref('')
const editStatus = ref<'open' | 'settled'>('open')
const saving = ref(false)

const statusOptions = [
  { label: '还开着', value: 'open' },
  { label: '已落地', value: 'settled' },
]

onMounted(loadBooks)

async function loadBooks() {
  loading.value = true
  try {
    books.value = await fetchConflictBooks()
  } catch {
    message.error('加载来历书失败')
  } finally {
    loading.value = false
  }
}

async function openBook(book: ConflictBookSummary) {
  showDetail.value = true
  detailLoading.value = true
  try {
    detail.value = await fetchConflictBook(book.id)
    editTitle.value = detail.value.title
    editNotes.value = detail.value.user_notes || ''
    editEpilogue.value = detail.value.epilogue || ''
    editStatus.value = detail.value.status
  } catch {
    message.error('打开失败')
    showDetail.value = false
  } finally {
    detailLoading.value = false
  }
}

async function saveEdits() {
  if (!detail.value) return
  saving.value = true
  try {
    const result = await patchConflictBook(detail.value.id, {
      title: editTitle.value.trim() || detail.value.title,
      user_notes: editNotes.value,
      epilogue: editEpilogue.value,
      status: editStatus.value,
    })
    if (result.ok) {
      message.success('已保存（原文未被改动）')
      await loadBooks()
    } else {
      message.error(result.error || '保存失败')
    }
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function removeBook() {
  if (!detail.value) return
  try {
    await deleteConflictBook(detail.value.id)
    message.success('已收起这本书（软删除，原文仍在档案里）')
    showDetail.value = false
    await loadBooks()
  } catch {
    message.error('删除失败')
  }
}

function fmtDate(value: string | null | undefined): string {
  return (value || '').slice(0, 10)
}

function threadLabel(key: string | null): string {
  if (key === 'hisense') return '海信'
  if (!key || key === 'main') return '主聊天'
  return key
}
</script>

<template>
  <div class="conflict-view" data-testid="page-conflict">
    <div class="header-row">
      <span class="hint">原文在截取那一刻冻结，谁都改不了。批注是沈予的，追加式，不可删。</span>
      <NButton size="small" @click="loadBooks">刷新</NButton>
    </div>

    <NSpin :show="loading">
      <div v-if="!books.length && !loading" class="empty">
        还没有来历书。去「档案」页选取一段聊天记录截进来。
      </div>
      <div class="shelf">
        <button v-for="book in books" :key="book.id" class="book" @click="openBook(book)">
          <div class="book-spine" :class="book.status"></div>
          <div class="book-info">
            <div class="book-title">《{{ book.title }}》</div>
            <div class="book-meta">
              <NTag size="tiny">{{ threadLabel(book.thread) }}</NTag>
              <NTag size="tiny" :class="book.status === 'settled' ? 'tag-settled' : 'tag-open'">
                {{ book.status === 'settled' ? '已落地' : '还开着' }}
              </NTag>
            </div>
            <div class="book-dates">{{ fmtDate(book.span_start) }}<template v-if="book.span_end && fmtDate(book.span_end) !== fmtDate(book.span_start)"> ~ {{ fmtDate(book.span_end) }}</template></div>
            <div class="book-reads">
              {{ book.read_count ? `他翻过 ${book.read_count} 次` : '他还没翻过' }}
              <template v-if="book.last_read_at"> · 最近 {{ fmtDate(book.last_read_at) }}</template>
            </div>
          </div>
        </button>
      </div>
    </NSpin>

    <NModal v-model:show="showDetail" preset="card" :title="detail ? `《${detail.title}》` : ''" style="max-width: 760px">
      <NSpin :show="detailLoading">
        <div v-if="detail" class="detail">
          <div class="section">
            <div class="section-title">原文（冻结）</div>
            <pre class="original-text">{{ detail.original_text }}</pre>
          </div>

          <div v-if="detail.annotations.length" class="section">
            <div class="section-title">他的批注（追加式，不可改不可删）</div>
            <div v-for="anno in detail.annotations" :key="anno.id" class="annotation">
              <div class="annotation-date">{{ (anno.created_at || '').slice(0, 16).replace('T', ' ') }}</div>
              <div class="annotation-content">{{ anno.content }}</div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">你可以编辑的部分</div>
            <div class="edit-form">
              <NInput v-model:value="editTitle" placeholder="标题" />
              <NInput v-model:value="editNotes" type="textarea" :rows="3" placeholder="你的注" />
              <NInput v-model:value="editEpilogue" type="textarea" :rows="3" placeholder="后记：后来怎么和好的、聊出了什么结论" />
              <NSelect v-model:value="editStatus" :options="statusOptions" style="width: 140px" />
            </div>
          </div>

          <div class="detail-actions">
            <NPopconfirm @positive-click="removeBook">
              <template #trigger>
                <NButton type="error" size="small">收起这本书</NButton>
              </template>
              软删除：书从书架上消失，但原文永远留在档案里。
            </NPopconfirm>
            <NButton type="primary" :loading="saving" @click="saveEdits">保存</NButton>
          </div>
        </div>
      </NSpin>
    </NModal>
  </div>
</template>

<style scoped>
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.hint {
  font-size: 12px;
  color: #b0a8a0;
}

.empty {
  color: #b0a8a0;
  font-size: 13px;
  text-align: center;
  padding: 50px 0;
}

.shelf {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 14px;
}

.book {
  display: flex;
  gap: 0;
  background: #fff;
  border: 1px solid #f0ece8;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  text-align: left;
  padding: 0;
  transition: 0.15s;
}

.book:hover {
  border-color: #9b8ec4;
  transform: translateY(-2px);
}

.book-spine {
  width: 7px;
  flex-shrink: 0;
}

.book-spine.open {
  background: #c8956a;
}

.book-spine.settled {
  background: #8bc49b;
}

.book-info {
  padding: 13px 15px;
  min-width: 0;
}

.book-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #3d3535;
  margin-bottom: 7px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.book-meta {
  display: flex;
  gap: 5px;
  margin-bottom: 7px;
}

.tag-settled {
  --n-color: #eef6f0 !important;
  --n-text-color: #5a9a6a !important;
}

.tag-open {
  --n-color: #fbf3ec !important;
  --n-text-color: #c8956a !important;
}

.book-dates {
  font-size: 11px;
  color: #b0a8a0;
  margin-bottom: 4px;
}

.book-reads {
  font-size: 11px;
  color: #9b8ec4;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.section-title {
  font-size: 11.5px;
  color: #b0a8a0;
  margin-bottom: 8px;
  letter-spacing: 0.3px;
}

.original-text {
  background: #faf8f5;
  border: 1px solid #f0ece8;
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 12.5px;
  line-height: 1.75;
  color: #3d3535;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
  font-family: inherit;
}

.annotation {
  background: #f5f3fa;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
}

.annotation-date {
  font-size: 10.5px;
  color: #9b8ec4;
  margin-bottom: 4px;
}

.annotation-content {
  font-size: 12.5px;
  line-height: 1.7;
  color: #3d3535;
  white-space: pre-wrap;
}

.edit-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-actions {
  display: flex;
  justify-content: space-between;
}
</style>
