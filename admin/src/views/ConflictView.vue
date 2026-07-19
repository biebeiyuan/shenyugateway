<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NAlert, NButton, NInput, NModal, NPopconfirm, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import {
  deleteConflictBook,
  fetchConflictBook,
  fetchConflictBooks,
  patchConflictBook,
  type ConflictBookDetail,
  type ConflictBookSummary,
} from '@/api/archive'
import {
  annotateBook,
  fetchHomeBook,
  fetchIdentityBook,
  fetchResidentOverview,
  updateIdentityBook,
  type BookAnnotation,
  type HomeOverview,
  type LivingBookDetail,
  type LivingBookRevision,
  type LivingBookSummary,
  type ResidentHomeSnapshot,
} from '@/api/books'
import HomeBookModal from '@/views/bookshelf/HomeBookModal.vue'

const message = useMessage()

const originBooks = ref<ConflictBookSummary[]>([])
const identityBook = ref<LivingBookSummary | null>(null)
const homeOverview = ref<HomeOverview | null>(null)
const warnings = ref<string[]>([])
const loading = ref(false)

const showOriginDetail = ref(false)
const originDetail = ref<ConflictBookDetail | null>(null)
const originDetailLoading = ref(false)
const editTitle = ref('')
const editNotes = ref('')
const editEpilogue = ref('')
const editStatus = ref<'open' | 'settled'>('open')
const originSaving = ref(false)

const showLivingDetail = ref(false)
const livingDetail = ref<LivingBookDetail | null>(null)
const livingRevisions = ref<LivingBookRevision[]>([])
const livingDetailLoading = ref(false)
const livingBody = ref('')
const livingSummary = ref('')
const livingAnnotation = ref('')
const livingSaving = ref(false)
const annotationSaving = ref(false)

const showHomeDetail = ref(false)
const homeDetailLoading = ref(false)
const homeSnapshot = ref<ResidentHomeSnapshot | null>(null)
const homeAnnotations = ref<BookAnnotation[]>([])
const homeAnnotation = ref('')
const homeAnnotationSaving = ref(false)

const statusOptions = [
  { label: '还开着', value: 'open' },
  { label: '已落地', value: 'settled' },
]

const homeShelfNote = computed(() => {
  const changes = Number(homeOverview.value?.current_week_changes || 0)
  return changes ? `这周家里记下了 ${changes} 条变化。` : '这周的家还安稳地待在原处。'
})

onMounted(loadBooks)

async function loadBooks() {
  loading.value = true
  const nextWarnings: string[] = []
  try {
    const [shelfResult, originResult] = await Promise.allSettled([
      fetchResidentOverview(),
      fetchConflictBooks(),
    ])

    if (shelfResult.status === 'fulfilled') {
      homeOverview.value = shelfResult.value.home || null
      identityBook.value = shelfResult.value.identity || null
      nextWarnings.push(...(shelfResult.value.warnings || []))
    } else {
      nextWarnings.push('“我是谁”和“家现在”暂时没有接上，来历书仍可单独使用。')
    }

    if (originResult.status === 'fulfilled') {
      originBooks.value = originResult.value
    } else {
      originBooks.value = []
      nextWarnings.push('来历书这一层暂时没有接上。')
    }

    warnings.value = nextWarnings
  } finally {
    loading.value = false
  }
}

function livingRevision(): string {
  return identityBook.value ? `第 ${identityBook.value.revision} 版` : '等第一笔'
}

function livingUpdated(): string {
  if (!identityBook.value) return '可以从这里开始写'
  const who = identityBook.value.updated_by ? `${identityBook.value.updated_by}更新` : '最近更新'
  const day = fmtDate(identityBook.value.updated_at)
  return day ? `${who} · ${day}` : who
}

async function openLivingBook() {
  showLivingDetail.value = true
  await reloadLivingBook()
}

async function reloadLivingBook() {
  livingDetailLoading.value = true
  try {
    const result = await fetchIdentityBook('history')
    if (!result.ok || !result.book) throw new Error(result.error || '打开失败')
    livingDetail.value = result.book
    livingRevisions.value = result.revisions || []
    livingBody.value = result.book.body || ''
    livingSummary.value = ''
  } catch (error) {
    message.error(error instanceof Error ? error.message : '打开失败')
    showLivingDetail.value = false
  } finally {
    livingDetailLoading.value = false
  }
}

async function saveLivingBook() {
  if (!livingDetail.value) return
  if (!livingBody.value.trim()) {
    message.warning('书页还不能是空的')
    return
  }
  livingSaving.value = true
  try {
    const result = await updateIdentityBook({
      content: livingBody.value,
      expected_revision: livingDetail.value.revision,
      summary: livingSummary.value.trim(),
    })
    if (!result.ok) {
      message.error(result.error || '保存失败')
      return
    }
    message.success('新一版已经放回书架，旧版本也还留着')
    await reloadLivingBook()
    await loadBooks()
  } catch {
    message.error('保存失败')
  } finally {
    livingSaving.value = false
  }
}

async function addLivingAnnotation() {
  if (!livingDetail.value || !livingAnnotation.value.trim()) return
  annotationSaving.value = true
  try {
    const result = await annotateBook('identity', {
      content: livingAnnotation.value.trim(),
      target_revision: livingDetail.value.revision,
    })
    if (!result.ok) {
      message.error(result.error || '批注失败')
      return
    }
    livingAnnotation.value = ''
    message.success('批注已经夹进这一版里')
    await reloadLivingBook()
  } catch {
    message.error('批注失败')
  } finally {
    annotationSaving.value = false
  }
}

async function openHomeBook() {
  showHomeDetail.value = true
  await reloadHomeBook()
}

async function reloadHomeBook() {
  homeDetailLoading.value = true
  try {
    const result = await fetchHomeBook()
    if (!result.ok || !result.snapshot || !result.book) throw new Error(result.error || '打开失败')
    homeSnapshot.value = result.snapshot
    homeAnnotations.value = result.book.annotations || []
  } catch (error) {
    message.error(error instanceof Error ? error.message : '打开失败')
    showHomeDetail.value = false
  } finally {
    homeDetailLoading.value = false
  }
}

async function addHomeAnnotation() {
  if (!homeAnnotation.value.trim()) return
  homeAnnotationSaving.value = true
  try {
    const result = await annotateBook('home', { content: homeAnnotation.value.trim() })
    if (!result.ok) {
      message.error(result.error || '批注失败')
      return
    }
    homeAnnotation.value = ''
    message.success('批注已经夹进《家现在》')
    await reloadHomeBook()
  } catch {
    message.error('批注失败')
  } finally {
    homeAnnotationSaving.value = false
  }
}

async function openOriginBook(book: ConflictBookSummary) {
  showOriginDetail.value = true
  originDetailLoading.value = true
  try {
    originDetail.value = await fetchConflictBook(book.id)
    editTitle.value = originDetail.value.title
    editNotes.value = originDetail.value.user_notes || ''
    editEpilogue.value = originDetail.value.epilogue || ''
    editStatus.value = originDetail.value.status
  } catch {
    message.error('打开失败')
    showOriginDetail.value = false
  } finally {
    originDetailLoading.value = false
  }
}

async function saveOriginEdits() {
  if (!originDetail.value) return
  originSaving.value = true
  try {
    const result = await patchConflictBook(originDetail.value.id, {
      title: editTitle.value.trim() || originDetail.value.title,
      user_notes: editNotes.value,
      epilogue: editEpilogue.value,
      status: editStatus.value,
    })
    if (result.ok) {
      message.success('已保存（原文未被改动）')
      originDetail.value = await fetchConflictBook(originDetail.value.id)
      await loadBooks()
    } else {
      message.error(result.error || '保存失败')
    }
  } catch {
    message.error('保存失败')
  } finally {
    originSaving.value = false
  }
}

async function removeOriginBook() {
  if (!originDetail.value) return
  try {
    await deleteConflictBook(originDetail.value.id)
    message.success('已收起这本书（软删除，原文仍在档案里）')
    showOriginDetail.value = false
    await loadBooks()
  } catch {
    message.error('删除失败')
  }
}

function fmtDate(value: string | null | undefined): string {
  return (value || '').slice(0, 10)
}

function fmtDateTime(value: string | null | undefined): string {
  return (value || '').slice(0, 16).replace('T', ' ')
}

function fmtShortDate(value: string | null | undefined): string {
  const parts = (value || '').slice(0, 10).split('-')
  if (parts.length !== 3) return ''
  return `${Number(parts[1])}.${Number(parts[2])}`
}

function threadLabel(key: string | null): string {
  if (key === 'hisense') return '海信'
  if (!key || key === 'main') return '主聊天'
  return key
}

function bookTone(index: number): string {
  return `tone-${index % 6}`
}

function spineChars(title: string, limit = 5): string[] {
  const characters = Array.from(title || '')
  return characters.length > limit ? [...characters.slice(0, limit), '…'] : characters
}
</script>

<template>
  <div class="bookshelf-view" data-testid="page-conflict">
    <header class="bookshelf-header">
      <div>
        <div class="eyebrow">OUR LITTLE LIBRARY</div>
        <h2>我们的小书架</h2>
        <p>三层，三种规则：家况自动生成，自述留下版本，来历保留原文。</p>
      </div>
      <NButton size="small" data-testid="bookshelf-refresh" @click="loadBooks">掸掸灰</NButton>
    </header>

    <div v-if="warnings.length" class="warning-stack">
      <NAlert v-for="warning in warnings" :key="warning" type="warning" :show-icon="false">
        {{ warning }}
      </NAlert>
    </div>

    <NSpin :show="loading">
      <div class="bookcase" aria-label="三层共享书架">
        <section class="shelf-tier identity-tier" data-testid="bookshelf-tier-identity">
          <div class="shelf-label">
            <span>第一层</span>
            <strong>我是谁</strong>
            <small>一册会继续长大的自述</small>
          </div>
          <div class="shelf-stage">
            <div class="shelf-books">
              <button
                class="book-volume feature-book identity-book"
                data-testid="bookshelf-book-identity"
                title="翻开《我是谁》"
                @click="openLivingBook"
              >
                <span class="book-ridge"></span>
                <span class="feature-title"><span>我</span><span>是</span><span>谁</span></span>
                <span class="feature-mark">可续写</span>
                <span class="feature-meta">{{ livingRevision() }}</span>
              </button>
              <div class="shelf-card">
                <strong>{{ livingRevision() }}</strong>
                <span>{{ livingUpdated() }}</span>
                <p>每次改写都会留下上一版，不会悄悄覆盖。</p>
              </div>
            </div>
          </div>
        </section>

        <section class="shelf-tier home-tier" data-testid="bookshelf-tier-home">
          <div class="shelf-label">
            <span>第二层</span>
            <strong>家现在</strong>
            <small>我们此刻住着的地方</small>
          </div>
          <div class="shelf-stage">
            <div class="shelf-books">
              <button
                class="book-volume feature-book home-book"
                data-testid="bookshelf-book-home"
                title="翻开《家现在》"
                @click="openHomeBook"
              >
                <span class="book-ridge"></span>
                <span class="feature-title"><span>家</span><span>现</span><span>在</span></span>
                <span class="feature-mark auto-mark">自动</span>
                <span class="feature-meta">只读 · 可批注</span>
              </button>
              <div class="shelf-card home-card">
                <strong>{{ homeOverview?.current_week_changes || 0 }} 条本周变化</strong>
                <span>
                  {{ homeOverview?.last_confirmed_at ? `最后确认于 ${fmtShortDate(homeOverview.last_confirmed_at)}` : '等待第一次确认' }}
                </span>
                <p>{{ homeShelfNote }}</p>
              </div>
            </div>
          </div>
        </section>

        <section class="shelf-tier origin-tier" data-testid="bookshelf-tier-origin">
          <div class="shelf-label">
            <span>第三层</span>
            <strong>来历书</strong>
            <small>从过去剪下来的冻结原文</small>
          </div>
          <div class="shelf-stage">
            <div v-if="originBooks.length" class="shelf-books origin-row">
              <button
                v-for="(book, index) in originBooks"
                :key="book.id"
                class="book-volume origin-book"
                :class="[bookTone(index), book.status]"
                :data-testid="`bookshelf-origin-${book.id}`"
                :title="`翻开《${book.title}》`"
                @click="openOriginBook(book)"
              >
                <span class="book-ridge"></span>
                <span class="origin-status">{{ book.status === 'settled' ? '落' : '开' }}</span>
                <span class="origin-title">
                  <span v-for="(character, characterIndex) in spineChars(book.title)" :key="characterIndex">
                    {{ character }}
                  </span>
                </span>
                <span class="origin-foot">{{ book.read_count ? `${book.read_count} 次` : '未翻' }}</span>
              </button>
              <div class="bookend" aria-hidden="true"><span>♡</span></div>
            </div>
            <div v-else class="empty-shelf">
              <div class="empty-book"><span>还没有来历书</span></div>
              <p>去「档案」选一段聊天，冻结成第一本。</p>
            </div>
          </div>
        </section>
      </div>
    </NSpin>

    <p class="shelf-footnote">上下文只露出书架一览；完整家况、自述正文和来历原文都要明确翻开。</p>

    <NModal
      v-model:show="showLivingDetail"
      preset="card"
      title="《我是谁》"
      style="max-width: 780px"
    >
      <NSpin :show="livingDetailLoading">
        <div v-if="livingDetail" class="detail">
          <div class="living-reader-head">
            <div>
              <span>活文档</span>
              <strong>第 {{ livingDetail.revision }} 版</strong>
            </div>
            <p>保存会生成新版本；如果这期间书被别人改过，旧页面不会覆盖新内容。</p>
          </div>

          <div class="section">
            <div class="section-title">现在这一页</div>
            <NInput
              v-model:value="livingBody"
              type="textarea"
              :rows="12"
              placeholder="从这里写下这一册现在的样子……"
              data-testid="living-book-body"
            />
            <NInput
              v-model:value="livingSummary"
              placeholder="这次改了什么（可选，会写在版本边上）"
              data-testid="living-book-summary"
            />
          </div>

          <div v-if="livingDetail.annotations.length" class="section">
            <div class="section-title">夹在书页里的批注</div>
            <div v-for="anno in livingDetail.annotations" :key="anno.id" class="annotation">
              <div class="annotation-date">
                {{ anno.actor || '圆圆' }} · 第 {{ anno.target_revision }} 版 · {{ fmtDateTime(anno.created_at) }}
              </div>
              <div class="annotation-content">{{ anno.content }}</div>
            </div>
          </div>

          <div class="section annotation-editor">
            <div class="section-title">留一张不可擦掉的批注</div>
            <div class="annotation-compose">
              <NInput v-model:value="livingAnnotation" type="textarea" :rows="2" placeholder="批注会带着时间夹进当前版本……" />
              <NButton
                :loading="annotationSaving"
                :disabled="!livingAnnotation.trim()"
                @click="addLivingAnnotation"
              >
                夹进去
              </NButton>
            </div>
          </div>

          <details v-if="livingRevisions.length" class="revision-history">
            <summary>以前的版本（{{ livingRevisions.length }}）</summary>
            <div v-for="revision in livingRevisions" :key="revision.id" class="revision-page">
              <div class="revision-head">
                <strong>第 {{ revision.revision }} 版</strong>
                <span>{{ revision.actor }} · {{ fmtDateTime(revision.created_at) }}</span>
              </div>
              <p v-if="revision.summary" class="revision-summary">{{ revision.summary }}</p>
              <pre>{{ revision.body }}</pre>
            </div>
          </details>

          <div class="detail-actions living-actions">
            <span>旧版本会一直留在书后面。</span>
            <NButton type="primary" :loading="livingSaving" @click="saveLivingBook">保存成新一版</NButton>
          </div>
        </div>
      </NSpin>
    </NModal>

    <HomeBookModal
      v-model:show="showHomeDetail"
      v-model:annotation="homeAnnotation"
      :loading="homeDetailLoading"
      :snapshot="homeSnapshot"
      :annotations="homeAnnotations"
      :annotation-saving="homeAnnotationSaving"
      @annotate="addHomeAnnotation"
    />

    <NModal
      v-model:show="showOriginDetail"
      preset="card"
      :title="originDetail ? `《${originDetail.title}》` : ''"
      style="max-width: 760px"
    >
      <NSpin :show="originDetailLoading">
        <div v-if="originDetail" class="detail">
          <div class="origin-reader-head">
            <span>冻结原文</span>
            <p>这部分停在截取那一刻，谁都改不了。</p>
          </div>

          <div class="section">
            <div class="section-title">原文（冻结）</div>
            <pre class="original-text">{{ originDetail.original_text }}</pre>
          </div>

          <div v-if="originDetail.annotations.length" class="section">
            <div class="section-title">他的批注（追加式，不可改不可删）</div>
            <div v-for="anno in originDetail.annotations" :key="anno.id" class="annotation origin-annotation">
              <div class="annotation-date">{{ fmtDateTime(anno.created_at) }}</div>
              <div class="annotation-content">{{ anno.content }}</div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">你可以整理的书封</div>
            <div class="edit-form">
              <NInput v-model:value="editTitle" placeholder="标题" />
              <NInput v-model:value="editNotes" type="textarea" :rows="3" placeholder="你的注" />
              <NInput v-model:value="editEpilogue" type="textarea" :rows="3" placeholder="后记：后来怎么和好的、聊出了什么结论" />
              <div class="origin-meta-row">
                <NSelect v-model:value="editStatus" :options="statusOptions" style="width: 140px" />
                <NTag size="small">{{ threadLabel(originDetail.thread) }}</NTag>
                <span>{{ fmtDate(originDetail.span_start) }}</span>
              </div>
            </div>
          </div>

          <div class="detail-actions">
            <NPopconfirm @positive-click="removeOriginBook">
              <template #trigger>
                <NButton type="error" size="small">收起这本书</NButton>
              </template>
              软删除：书从书架上消失，但原文永远留在档案里。
            </NPopconfirm>
            <NButton type="primary" :loading="originSaving" @click="saveOriginEdits">保存书封</NButton>
          </div>
        </div>
      </NSpin>
    </NModal>
  </div>
</template>

<style scoped>
.bookshelf-view {
  max-width: 1040px;
  margin: 0 auto;
  padding: 12px 0 36px;
}

.bookshelf-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin: 4px 4px 22px;
}

.eyebrow {
  margin-bottom: 5px;
  color: #b49483;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2.6px;
}

.bookshelf-header h2 {
  color: #5f4138;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 34px;
  font-weight: 500;
  letter-spacing: 1px;
}

.bookshelf-header p {
  margin-top: 5px;
  color: #aa9188;
  font-size: 12px;
  line-height: 1.7;
}

.warning-stack {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}

.bookcase {
  position: relative;
  overflow: hidden;
  padding: 20px 22px 24px;
  border: 12px solid #76503e;
  border-color: #8b6250 #694637 #5d3d31 #825a46;
  border-radius: 10px 10px 15px 15px;
  background:
    linear-gradient(90deg, rgb(255 255 255 / 5%) 1px, transparent 1px) 0 0 / 42px 100%,
    linear-gradient(112deg, #875f49, #6f4b3b 48%, #7e5844);
  box-shadow:
    0 18px 35px rgb(91 55 43 / 18%),
    inset 0 0 0 2px rgb(255 255 255 / 8%),
    inset 14px 0 24px rgb(44 25 20 / 18%),
    inset -14px 0 24px rgb(44 25 20 / 18%);
}

.bookcase::before {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(6deg, transparent 0 34px, rgb(60 35 27 / 7%) 35px 36px);
  content: '';
  pointer-events: none;
}

.shelf-tier {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  min-height: 196px;
  border: 1px solid rgb(71 42 32 / 35%);
  border-bottom: 0;
  background:
    radial-gradient(circle at 25% 10%, rgb(255 255 255 / 82%), transparent 38%),
    linear-gradient(180deg, #f8eee0 0%, #f1e1cf 100%);
  box-shadow: inset 0 12px 22px rgb(69 40 29 / 10%);
}

.shelf-tier + .shelf-tier {
  margin-top: 20px;
}

.shelf-tier::after {
  position: absolute;
  right: -8px;
  bottom: -17px;
  left: -8px;
  height: 20px;
  border-top: 2px solid #a77a5e;
  border-bottom: 4px solid #4f3329;
  border-radius: 2px 2px 6px 6px;
  background: linear-gradient(180deg, #9a6d53 0%, #76503e 54%, #5d3d31 100%);
  box-shadow: 0 8px 12px rgb(52 31 24 / 24%);
  content: '';
}

.shelf-label {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 24px 20px;
  border-right: 1px dashed rgb(124 86 67 / 23%);
  color: #7a5849;
}

.shelf-label span {
  margin-bottom: 8px;
  color: #bc9278;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
}

.shelf-label strong {
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 2px;
}

.shelf-label small {
  margin-top: 8px;
  color: #b1998c;
  font-size: 10.5px;
  line-height: 1.6;
}

.shelf-stage {
  min-width: 0;
  padding: 18px 22px 0;
}

.shelf-books {
  display: flex;
  align-items: flex-end;
  min-width: 0;
  height: 177px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.book-volume {
  position: relative;
  flex: 0 0 auto;
  align-self: flex-end;
  overflow: hidden;
  border: 0;
  border-radius: 4px 6px 2px 3px;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transform-origin: bottom center;
  transition: transform 160ms ease, filter 160ms ease;
  box-shadow:
    5px 5px 8px rgb(63 38 30 / 22%),
    inset -5px 0 8px rgb(45 25 20 / 15%),
    inset 2px 0 1px rgb(255 255 255 / 25%);
}

.book-volume:hover,
.book-volume:focus-visible {
  z-index: 2;
  filter: saturate(1.08) brightness(1.03);
  outline: none;
  transform: translateY(-7px) rotate(-1deg);
}

.book-ridge {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 7px;
  width: 2px;
  background: rgb(255 255 255 / 18%);
  box-shadow: 2px 0 rgb(40 20 16 / 12%);
}

.feature-book {
  width: 92px;
  height: 154px;
  margin-left: 8px;
  padding: 20px 14px 12px 20px;
  color: #fffaf4;
}

.identity-book {
  background: linear-gradient(105deg, #6f7f91 0%, #8796a5 55%, #687889 100%);
}

.home-book {
  width: 104px;
  height: 160px;
  background: linear-gradient(105deg, #8c6d5c 0%, #a5826d 55%, #7f604f 100%);
}

.feature-title {
  position: absolute;
  top: 33px;
  left: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  font-size: 18px;
  font-weight: 600;
  line-height: 1;
  transform: translateX(-50%);
}

.feature-title span,
.origin-title span {
  display: block;
}

.feature-mark {
  position: absolute;
  top: 13px;
  right: 8px;
  padding: 3px 2px;
  border: 1px solid rgb(255 255 255 / 35%);
  border-radius: 7px;
  color: rgb(255 255 255 / 76%);
  font-size: 8px;
  letter-spacing: 1px;
  writing-mode: vertical-rl;
}

.feature-mark.auto-mark {
  border-color: rgb(255 244 213 / 50%);
  color: #fff0cc;
}

.feature-meta {
  position: absolute;
  right: 12px;
  bottom: 12px;
  color: rgb(255 255 255 / 68%);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 8.5px;
}

.shelf-card {
  align-self: center;
  width: min(300px, calc(100% - 130px));
  margin: 0 18px 24px;
  padding: 13px 16px;
  border: 1px solid rgb(133 102 82 / 16%);
  border-radius: 3px;
  background: rgb(255 252 246 / 62%);
  color: #8d7365;
  transform: rotate(-0.8deg);
  box-shadow: 0 5px 14px rgb(76 47 35 / 8%);
}

.shelf-card::before {
  display: block;
  width: 38px;
  height: 6px;
  margin: -18px auto 9px;
  background: rgb(198 166 129 / 45%);
  content: '';
  transform: rotate(2deg);
}

.shelf-card strong,
.shelf-card span {
  display: block;
}

.shelf-card strong {
  color: #70564a;
  font-size: 12px;
}

.shelf-card span {
  margin-top: 3px;
  color: #af9588;
  font-size: 10px;
}

.shelf-card p {
  margin-top: 8px;
  font-size: 10.5px;
  line-height: 1.6;
}

.home-card {
  transform: rotate(0.7deg);
}

.origin-row {
  gap: 3px;
  padding: 0 10px 0 4px;
}

.origin-book {
  width: 58px;
  height: 142px;
  padding: 14px 8px 9px 15px;
  color: #fffaf2;
}

.origin-book:nth-child(3n) { height: 151px; }
.origin-book:nth-child(4n) { height: 134px; }
.origin-book:nth-child(5n) { width: 65px; }

.origin-book.tone-0 { background: linear-gradient(100deg, #9f655f, #b67b71 55%, #8d5753); }
.origin-book.tone-1 { background: linear-gradient(100deg, #76856e, #8fa087 55%, #687760); }
.origin-book.tone-2 { background: linear-gradient(100deg, #756b8d, #8e82a5 55%, #675d7d); }
.origin-book.tone-3 { background: linear-gradient(100deg, #a17a54, #b88f64 55%, #8e6947); }
.origin-book.tone-4 { background: linear-gradient(100deg, #557f86, #6c969c 55%, #496f75); }
.origin-book.tone-5 { background: linear-gradient(100deg, #8d6c75, #a4828b 55%, #7b5d66); }

.origin-book.settled {
  filter: saturate(0.76) brightness(1.08);
}

.origin-status {
  position: absolute;
  top: 7px;
  right: 5px;
  display: grid;
  width: 17px;
  height: 17px;
  place-items: center;
  border: 1px solid rgb(255 255 255 / 35%);
  border-radius: 50%;
  color: rgb(255 255 255 / 82%);
  font-size: 8px;
}

.origin-title {
  position: absolute;
  top: 31px;
  left: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  transform: translateX(-50%);
}

.origin-foot {
  position: absolute;
  right: 8px;
  bottom: 8px;
  color: rgb(255 255 255 / 68%);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 8px;
}

.bookend {
  position: relative;
  flex: 0 0 34px;
  align-self: flex-end;
  height: 76px;
  margin-left: 7px;
  border-right: 9px solid #89624c;
  border-bottom: 12px solid #89624c;
  color: #a9826d;
}

.bookend span {
  position: absolute;
  right: 5px;
  bottom: 15px;
  font-size: 13px;
}

.empty-shelf {
  display: flex;
  align-items: flex-end;
  height: 177px;
  padding: 0 10px 26px;
  color: #aa9185;
}

.empty-book {
  display: grid;
  width: 72px;
  height: 116px;
  margin-right: 18px;
  place-items: center;
  border: 1px dashed #c7aa96;
  border-radius: 4px 6px 2px 3px;
  background: rgb(255 255 255 / 28%);
}

.empty-book span {
  color: #b39888;
  font-size: 9px;
  letter-spacing: 2px;
  writing-mode: vertical-rl;
}

.empty-shelf p {
  max-width: 230px;
  margin-bottom: 16px;
  font-size: 11px;
  line-height: 1.7;
}

.shelf-footnote {
  margin-top: 20px;
  color: #b29a90;
  font-size: 10.5px;
  text-align: center;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.living-reader-head,
.origin-reader-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f7f3ed;
  color: #8b7467;
}

.living-reader-head div {
  flex: 0 0 auto;
}

.living-reader-head span,
.living-reader-head strong,
.origin-reader-head span {
  display: block;
}

.living-reader-head span,
.origin-reader-head span {
  color: #b49b8d;
  font-size: 9px;
  letter-spacing: 1.5px;
}

.living-reader-head strong {
  margin-top: 2px;
  color: #6f554a;
  font-size: 14px;
}

.living-reader-head p,
.origin-reader-head p {
  font-size: 10.5px;
  line-height: 1.6;
  text-align: right;
}


.section-title {
  margin-bottom: 8px;
  color: #b0a8a0;
  font-size: 11.5px;
  letter-spacing: 0.3px;
}

.section :deep(.n-input + .n-input) {
  margin-top: 9px;
}

.original-text,
.revision-page pre {
  overflow-y: auto;
  border: 1px solid #f0ece8;
  border-radius: 10px;
  background: #faf8f5;
  color: #3d3535;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.original-text {
  max-height: 340px;
  padding: 14px 16px;
}

.annotation {
  margin-bottom: 8px;
  padding: 10px 14px;
  border-left: 3px solid #90a0ad;
  border-radius: 4px 10px 10px 4px;
  background: #f3f6f8;
}

.origin-annotation {
  border-left-color: #9b8ec4;
  background: #f5f3fa;
}

.annotation-date {
  margin-bottom: 4px;
  color: #8294a0;
  font-size: 10.5px;
}

.annotation-content {
  color: #3d3535;
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.annotation-compose {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 8px;
}

.revision-history {
  border: 1px solid #eee6df;
  border-radius: 10px;
  background: #fcfaf7;
}

.revision-history summary {
  padding: 12px 14px;
  color: #8c7569;
  cursor: pointer;
  font-size: 11.5px;
}

.revision-page {
  margin: 0 12px 12px;
  padding-top: 12px;
  border-top: 1px dashed #e4d8cf;
}

.revision-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #9e887d;
  font-size: 10px;
}

.revision-head strong {
  color: #725b50;
  font-size: 11px;
}

.revision-summary {
  margin-top: 7px;
  color: #927a6e;
  font-size: 11px;
}

.revision-page pre {
  max-height: 180px;
  margin-top: 8px;
  padding: 10px 12px;
}

.edit-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.origin-meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #ad978c;
  font-size: 10.5px;
}

.detail-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.living-actions span {
  color: #b09a90;
  font-size: 10.5px;
}

@media (max-width: 700px) {
  .bookshelf-view {
    padding-top: 2px;
  }

  .bookshelf-header {
    align-items: flex-start;
    margin-bottom: 16px;
  }

  .bookshelf-header h2 {
    font-size: 29px;
  }

  .bookcase {
    padding: 12px 10px 18px;
    border-width: 8px;
  }

  .shelf-tier {
    display: block;
    min-height: 0;
  }

  .shelf-label {
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: baseline;
    gap: 0 10px;
    padding: 10px 13px 7px;
    border-right: 0;
    border-bottom: 1px dashed rgb(124 86 67 / 18%);
  }

  .shelf-label span {
    grid-row: 1;
    margin: 0;
  }

  .shelf-label strong {
    grid-row: 1;
    font-size: 17px;
  }

  .shelf-label small {
    grid-column: 1 / -1;
    margin-top: 3px;
  }

  .shelf-stage {
    padding: 9px 8px 0;
  }

  .shelf-books,
  .empty-shelf {
    height: 159px;
  }

  .feature-book {
    height: 139px;
  }

  .home-book {
    height: 145px;
  }

  .shelf-card {
    min-width: 190px;
    margin-right: 8px;
  }

  .origin-book {
    height: 127px;
  }

  .origin-book:nth-child(3n) { height: 137px; }
  .origin-book:nth-child(4n) { height: 122px; }

  .living-reader-head,
  .origin-reader-head,
  .detail-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .living-reader-head p,
  .origin-reader-head p {
    text-align: left;
  }

  .annotation-compose {
    grid-template-columns: 1fr;
  }

  .detail-actions :deep(.n-button) {
    align-self: stretch;
  }
}
</style>
