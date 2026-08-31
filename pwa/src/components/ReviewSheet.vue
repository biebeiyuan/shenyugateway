<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowRight,
  Bookmark,
  BookmarkCheck,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Search,
  Trash2,
  X,
} from 'lucide-vue-next'
import MarkdownBody from './MarkdownBody.vue'
import {
  fetchArchiveDays,
  fetchArchiveMessages,
  searchArchive,
  type ArchiveMessage,
} from '../api/archive'
import type { RequestContext } from '../api/client'
import { isSaved, loadSaved, removeSaved, toggleSaved, type SavedItem } from '../session/savedStore'

// 回看：搜索 / 按天翻 / 收藏三合一。它只读档案、只写本地收藏，绝不碰 transcript。
// 所以它是一个自洽块，整体搬进组件——App.vue 只管开合与传 ctx。

const props = defineProps<{ open: boolean; ctx: RequestContext }>()
const emit = defineEmits<{ close: [] }>()

type Tab = 'search' | 'archive' | 'saved'
const tab = ref<Tab>('search')
const tabTitle: Record<Tab, string> = { search: '搜索', archive: '按天翻', saved: '收藏' }

// ---- 搜索 ----
const query = ref('')
const searchResults = ref<ArchiveMessage[]>([])
const searching = ref(false)
const searchError = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
let searchToken = 0

async function runSearch() {
  const needle = query.value.trim()
  if (!needle) { searchResults.value = []; searchError.value = ''; return }
  const token = ++searchToken
  searching.value = true
  searchError.value = ''
  try {
    const rows = await searchArchive(props.ctx, needle)
    if (token !== searchToken) return
    searchResults.value = rows
  } catch {
    if (token !== searchToken) return
    searchResults.value = []
    searchError.value = '这次没搜成，待会儿再试试。'
  } finally {
    if (token === searchToken) searching.value = false
  }
}

let debounce: ReturnType<typeof setTimeout> | undefined
watch(query, () => {
  clearTimeout(debounce)
  debounce = setTimeout(runSearch, 220)
})

function clearSearch() {
  query.value = ''
  searchResults.value = []
  searchInput.value?.focus()
}

// ---- 按天翻 ----
const days = ref<{ date: string; count: number }[]>([])
const archiveRows = ref<ArchiveMessage[]>([])
const activeDay = ref('')
const archiveError = ref('')
// 日历：平时收起，要按天找才展开——每天都聊天，一排横条会乱，月历才好找。
const calendarOpen = ref(false)
const calMonth = ref('') // YYYY-MM，展开的那个月
const monthDays = ref<{ date: string; count: number }[]>([]) // 该月哪些天有聊天
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

const monthLabel = computed(() => {
  const [y, m] = calMonth.value.split('-').map(Number)
  return y && m ? `${y}年${m}月` : ''
})
const monthCount = computed(() => monthDays.value.reduce((sum, d) => sum + d.count, 0))
// 一格一天，前面补空格对齐星期（周一开头）。
const calendarCells = computed(() => {
  const [y, m] = calMonth.value.split('-').map(Number)
  if (!y || !m) return [] as Array<{ day: number; date: string; count: number } | null>
  const counts = new Map(monthDays.value.map((d) => [d.date, d.count]))
  let lead = new Date(y, m - 1, 1).getDay() - 1
  if (lead < 0) lead = 6
  const total = new Date(y, m, 0).getDate()
  const cells: Array<{ day: number; date: string; count: number } | null> = []
  for (let i = 0; i < lead; i += 1) cells.push(null)
  for (let d = 1; d <= total; d += 1) {
    const date = `${calMonth.value}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, date, count: counts.get(date) || 0 })
  }
  return cells
})

async function loadMonth(month: string) {
  calMonth.value = month
  try { monthDays.value = await fetchArchiveDays(props.ctx, month) } catch { monthDays.value = [] }
}
function shiftMonth(delta: number) {
  const [y, m] = calMonth.value.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  void loadMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
}
async function toggleCalendar() {
  calendarOpen.value = !calendarOpen.value
  if (!calendarOpen.value) return
  // 打开这一刻才算一次「现在读到哪天」，用来高亮＋定位月份。平时滚动不算，省得卡。
  syncActiveDay()
  const month = (activeDay.value || todayStr()).slice(0, 7)
  if (month !== calMonth.value) await loadMonth(month)
}
function pickCalendarDay(date: string, count: number) {
  if (!count) return
  calendarOpen.value = false
  activeDay.value = date
  loadArchive(date)
}
function todayStr() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
}
// 真正在滚动的是 .review-body（三个 tab 共用的滚动容器），无限滚动的测量与
// prepend 位置补偿都必须挂在它身上——挂在里层不滚动的 .archive-scroll 上，轮子
// 是不转的，「划到顶加载更早」永远不触发（2026-08-31 圆圆报的划不动就是这个）。
const bodyRef = ref<HTMLElement | null>(null)
let archiveLoaded = false
// 连续阅读的两端游标与「翻到头了」标记，避免空翻。
let loadingEdge = false
const reachedOldest = ref(false)
const reachedNewest = ref(false)
const PAGE = 60

// 以某天为锚点打开（默认最后一天），装一屏；之后靠上下滚动继续加载。
async function loadArchive(focusDate?: string, focusId?: string) {
  archiveError.value = ''
  try {
    if (!days.value.length) days.value = await fetchArchiveDays(props.ctx)
    const target = focusDate || activeDay.value || days.value[days.value.length - 1]?.date
    if (!target) { archiveRows.value = []; return }
    activeDay.value = target
    const rows = await fetchArchiveMessages(props.ctx, { date: target, aroundDays: 1 })
    archiveRows.value = rows
    reachedOldest.value = false
    reachedNewest.value = false
    archiveLoaded = true
    await nextTick()
    if (focusId) {
      // 从搜索跳转：只平滑滚到那句并高亮。这里不能补内容——scrollIntoView 的平滑
      // 动画还没跑完，fillViewport 又在往顶上 prepend 并改 scrollTop，两者打架，
      // 落定后一滑就顿一下（2026-08-31 圆圆报的「跳过去再滑会卡」）。跳转本就带了
      // 前后一天，够撑满；等真滑到顶，loadOlder 自然接手。
      flashTo(focusId)
      return
    }
    if (!rows.length) return
    scrollToDivider(target)
    // 非跳转（日历/默认进入）：内容若撑不满容器就补更早的，否则没法滚、也触发不了加载。
    await fillViewport()
  } catch {
    archiveError.value = '这天的对话暂时拿不到，待会儿再试试。'
  }
}

// 反复补更早的，直到内容溢出容器或翻到最早，最多补几轮以防极端情况空转。
async function fillViewport() {
  for (let i = 0; i < 6; i += 1) {
    await nextTick()
    const el = bodyRef.value
    if (!el || reachedOldest.value) return
    if (el.scrollHeight > el.clientHeight + 40) return
    const grew = archiveRows.value.length
    await loadOlder()
    if (archiveRows.value.length === grew) return
  }
}

// 往过去翻：取最早一条之前的，prepend，并把滚动位置钉回原处，让手指停着不动。
async function loadOlder() {
  if (loadingEdge || reachedOldest.value || !archiveRows.value.length) return
  const anchorId = archiveRows.value[0]?.id
  const cursor = archiveRows.value[0]?.event_at
  if (!cursor || !anchorId) return
  loadingEdge = true
  try {
    const older = await fetchArchiveMessages(props.ctx, { before: cursor, limit: PAGE })
    if (!older.length) { reachedOldest.value = true; return }
    const el = bodyRef.value
    // 钉住「插入前的第一条」这个真实元素，而不是靠总高度差补偿。总高度在这一帧里
    // 还会被 Markdown 渲染/换行微调，差值补偿就会偏一点、抖一下再自纠正（圆圆报的
    // 「抖动一下就正常了」）。锚在具体元素的 offsetTop 上，不受别处高度变化影响。
    const anchorBefore = el?.querySelector(`#rev-${cssId(anchorId)}`) as HTMLElement | null
    const offsetBefore = anchorBefore?.offsetTop ?? 0
    const scrollBefore = el?.scrollTop ?? 0
    archiveRows.value = [...older, ...archiveRows.value]
    await nextTick()
    if (el) {
      const anchorAfter = el.querySelector(`#rev-${cssId(anchorId)}`) as HTMLElement | null
      if (anchorAfter) el.scrollTop = scrollBefore + (anchorAfter.offsetTop - offsetBefore)
    }
  } catch { /* 静默：翻不动就停在这儿 */ } finally { loadingEdge = false }
}

// 往当下翻：取最新一条之后的，append。
async function loadNewer() {
  if (loadingEdge || reachedNewest.value || !archiveRows.value.length) return
  const cursor = archiveRows.value[archiveRows.value.length - 1]?.event_at
  if (!cursor) return
  loadingEdge = true
  try {
    const newer = await fetchArchiveMessages(props.ctx, { after: cursor, limit: PAGE })
    if (!newer.length) { reachedNewest.value = true; return }
    archiveRows.value = [...archiveRows.value, ...newer]
  } catch { /* 静默 */ } finally { loadingEdge = false }
}

// review-body 是三个 tab 共用的滚动容器；只有在按天翻时才管无限加载。
// 用 rAF 收敛：一帧最多判一次边缘，别每个 scroll 事件都跑。也刻意不在滚动里算
// activeDay——那要对每条消息 getBoundingClientRect，逐帧强制重排，就是「跳转后
// 上下滑会卡」的元凶（2026-08-31）。activeDay 只有打开日历才用，到那时算一次即可。
let scrollTick = false
function onBodyScroll() {
  if (tab.value !== 'archive' || scrollTick) return
  scrollTick = true
  requestAnimationFrame(() => {
    scrollTick = false
    const el = bodyRef.value
    if (!el) return
    if (el.scrollTop < 240) void loadOlder()
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 240) void loadNewer()
  })
}

// 视口顶部落在哪条消息，日期条就高亮那天。
function syncActiveDay() {
  const el = bodyRef.value
  if (!el) return
  const top = el.getBoundingClientRect().top
  for (const row of archiveRows.value) {
    const node = el.querySelector(`#rev-${cssId(row.id)}`) as HTMLElement | null
    if (node && node.getBoundingClientRect().bottom >= top) {
      const day = cstDay(row.event_at)
      if (day && day !== activeDay.value) activeDay.value = day
      return
    }
  }
}

function scrollToDivider(date: string) {
  const el = bodyRef.value?.querySelector(`[data-anchor="${date}"]`)
  el?.scrollIntoView({ block: 'start' })
}

function flashTo(id: string) {
  const el = bodyRef.value?.querySelector(`#rev-${cssId(id)}`) as HTMLElement | null
  if (!el) return
  // 瞬间定位，不做平滑动画：平滑滚动那几百毫秒里，你一滑手指就和动画抢滚动条，
  // 就是那个「跳过去再滑会卡」。落点改用高亮闪一下告诉你，没有动画就没得抢。
  el.scrollIntoView({ block: 'center' })
  el.classList.add('flash')
  setTimeout(() => el.classList.remove('flash'), 1750)
}

function cssId(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, '')
}

// 从搜索结果跳到按天翻，并定位到那句
function jumpToContext(row: ArchiveMessage) {
  const date = cstDay(row.event_at)
  tab.value = 'archive'
  loadArchive(date, row.id)
}

// ---- 收藏 ----
const saved = ref<SavedItem[]>([])
function refreshSaved() { saved.value = loadSaved() }

function onToggleSave(row: ArchiveMessage) {
  const { saved: nowSaved } = toggleSaved(row)
  refreshSaved()
  return nowSaved
}
function onRemoveSaved(id: string) {
  saved.value = removeSaved(id)
}
function savedIds() {
  return new Set(saved.value.map((row) => row.id))
}

// 收藏页里「回到当时」：把 SavedItem 当成 ArchiveMessage 跳
function gotoSaved(item: SavedItem) {
  jumpToContext({ id: item.id, session_tag: '', role: item.role, content: item.content, event_at: item.event_at, archived_at: '' })
}

// ---- helpers ----
const WHO: Record<string, string> = { self: '圆圆', user: '圆圆', shen: '沈予', assistant: '沈予' }
function whoName(role: string) { return WHO[role] || role }
function whoClass(role: string) { return role === 'user' ? 'self' : 'shen' }

function cstDay(raw: string | null): string {
  if (!raw) return ''
  try {
    return new Date(raw).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).replace(/\//g, '-')
  } catch { return String(raw).slice(0, 10) }
}
function dayLabel(date: string): string {
  const parts = date.split('-')
  return parts.length === 3 ? `${+parts[1]}月${+parts[2]}日` : date
}
// 连续流里，某条与上一条不是同一天，就在它前面插一条日期分隔。
function showDivider(index: number): boolean {
  if (index === 0) return true
  return cstDay(archiveRows.value[index]?.event_at) !== cstDay(archiveRows.value[index - 1]?.event_at)
}
function timeLabel(raw: string | null): string {
  if (!raw) return ''
  try {
    return new Date(raw).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false })
  } catch { return '' }
}

// 命中词高亮：以命中处为中心裁一段，前后各留一点，字面匹配大小写不敏感
function snippetHtml(text: string, q: string): string {
  const escape = (s: string) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] || c))
  const needle = q.trim()
  const i = text.toLowerCase().indexOf(needle.toLowerCase())
  if (i < 0) return escape(text)
  const start = Math.max(0, i - 20)
  const clip = (start > 0 ? '…' : '') + text.slice(start)
  const rel = clip.toLowerCase().indexOf(needle.toLowerCase())
  return escape(clip.slice(0, rel)) + '<mark>' + escape(clip.slice(rel, rel + needle.length)) + '</mark>' + escape(clip.slice(rel + needle.length))
}

function switchTab(next: Tab) {
  tab.value = next
  if (next === 'archive' && !archiveLoaded) loadArchive()
  if (next === 'saved') refreshSaved()
  if (next === 'search') nextTick(() => searchInput.value?.focus())
}

// 每次打开都以搜索开场并聚焦
watch(() => props.open, (open) => {
  if (!open) return
  tab.value = 'search'
  refreshSaved()
  nextTick(() => setTimeout(() => searchInput.value?.focus(), 300))
})

const title = computed(() => tabTitle[tab.value])

function copyText(text: string) {
  void navigator.clipboard?.writeText(text).catch(() => {})
}
</script>

<template>
  <div v-if="open" class="sheet-layer" @click.self="emit('close')">
    <section class="bottom-sheet review-sheet" role="dialog" aria-label="回看">
      <div class="sheet-handle" />
      <div class="sheet-heading">
        <div><h2>{{ title }}</h2></div>
        <button class="icon-button" aria-label="关闭" title="关闭" @click="emit('close')"><X :size="18" /></button>
      </div>

      <div class="review-tabs">
        <button class="review-tab" :class="{ active: tab === 'search' }" type="button" @click="switchTab('search')"><Search :size="17" /><span>搜索</span></button>
        <button class="review-tab" :class="{ active: tab === 'archive' }" type="button" @click="switchTab('archive')"><CalendarDays :size="17" /><span>按天翻</span></button>
        <button class="review-tab" :class="{ active: tab === 'saved' }" type="button" @click="switchTab('saved')"><Bookmark :size="17" /><span>收藏</span></button>
      </div>

      <div ref="bodyRef" class="review-body" @scroll.passive="onBodyScroll">
        <!-- 搜索 -->
        <div v-show="tab === 'search'" class="review-pane">
          <div class="search-field" :class="{ 'has-text': query }">
            <Search :size="18" />
            <input ref="searchInput" v-model="query" placeholder="搜一句你记得的话…" autocomplete="off" @keydown.enter="runSearch" />
            <button v-if="query" class="clear" aria-label="清除" title="清除" @click="clearSearch"><X :size="16" /></button>
          </div>

          <div v-if="!query" class="review-empty">
            <span class="ic"><Search :size="22" /></span>
            <p>想找哪句话？</p>
            <p class="sub">按你记得的字词搜，搜到的就是原话。</p>
          </div>
          <div v-else-if="searchError" class="review-empty"><p>{{ searchError }}</p></div>
          <div v-else-if="!searching && !searchResults.length" class="review-empty">
            <span class="ic"><Search :size="22" /></span>
            <p>没找到「{{ query.trim() }}」。</p>
            <p class="sub">换个说法，或者去按天翻翻看。</p>
          </div>
          <template v-else>
            <div class="result-count">{{ searchResults.length }} 条结果</div>
            <button v-for="row in searchResults" :key="row.id" class="result-card" type="button" @click="jumpToContext(row)">
              <div class="result-meta">
                <span class="who" :class="whoClass(row.role)"><span class="dot" />{{ whoName(row.role) }}</span>
                <span class="result-date">{{ dayLabel(cstDay(row.event_at)) }} · {{ timeLabel(row.event_at) }}</span>
              </div>
              <div class="result-snippet" v-html="snippetHtml(row.content, query)" />
            </button>
          </template>
        </div>

        <!-- 按天翻 -->
        <div v-show="tab === 'archive'" class="review-pane">
          <!-- 收起时只有一个小日历按钮；展开才是月历，选完就收 -->
          <div class="cal-bar">
            <button class="cal-toggle" type="button" @click="toggleCalendar">
              <CalendarDays :size="17" />
              <span>{{ calendarOpen ? (monthLabel || '选个日子') : '按日子找' }}</span>
              <ChevronDown :size="15" class="cal-caret" :class="{ open: calendarOpen }" />
            </button>
            <div v-if="calendarOpen" class="cal-month-nav">
              <button type="button" aria-label="上个月" @click="shiftMonth(-1)"><ChevronLeft :size="18" /></button>
              <button type="button" aria-label="下个月" @click="shiftMonth(1)"><ChevronRight :size="18" /></button>
            </div>
          </div>
          <div v-if="calendarOpen" class="cal-panel">
            <div class="cal-weekdays"><span v-for="w in WEEKDAYS" :key="w">{{ w }}</span></div>
            <div class="cal-grid">
              <button
                v-for="(cell, idx) in calendarCells"
                :key="idx"
                type="button"
                class="cal-cell"
                :class="{ blank: !cell, has: cell && cell.count > 0, active: cell && cell.date === activeDay }"
                :disabled="!cell || !cell.count"
                @click="cell && pickCalendarDay(cell.date, cell.count)"
              >
                <template v-if="cell"><span>{{ cell.day }}</span><span v-if="cell.count" class="cal-dot" /></template>
              </button>
            </div>
          </div>
          <div v-if="archiveError" class="review-empty"><p>{{ archiveError }}</p></div>
          <div v-else class="archive-scroll">
            <template v-for="(row, index) in archiveRows" :key="row.id">
              <div v-if="showDivider(index)" class="day-divider" :data-anchor="cstDay(row.event_at)">{{ dayLabel(cstDay(row.event_at)) }}</div>
              <div class="archive-msg" :class="whoClass(row.role) === 'self' ? 'user' : 'assistant'" :id="`rev-${cssId(row.id)}`">
                <div class="col">
                  <div v-if="row.role === 'user'" class="user-bubble">{{ row.content }}</div>
                  <div v-else class="assistant-body"><MarkdownBody :content="row.content" /></div>
                  <div class="message-actions">
                    <button title="复制" aria-label="复制" @click="copyText(row.content)"><Clipboard :size="15" /></button>
                    <button :class="{ saved: isSaved(row.id, saved) }" :title="isSaved(row.id, saved) ? '取消收藏' : '收藏'" :aria-label="isSaved(row.id, saved) ? '取消收藏' : '收藏'" @click="onToggleSave(row)">
                      <BookmarkCheck v-if="isSaved(row.id, saved)" :size="15" />
                      <Bookmark v-else :size="15" />
                    </button>
                  </div>
                  <span class="archive-time">{{ timeLabel(row.event_at) }}</span>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- 收藏 -->
        <div v-show="tab === 'saved'" class="review-pane">
          <div v-if="!saved.length" class="review-empty">
            <span class="ic"><Bookmark :size="22" /></span>
            <p>这里还空着。</p>
            <p class="sub">翻档案时点一下书签，那句话就留在这儿。</p>
          </div>
          <template v-else>
            <div v-for="item in saved" :key="item.id" class="saved-card">
              <div class="result-meta">
                <span class="who" :class="whoClass(item.role)"><span class="dot" />{{ whoName(item.role) }}</span>
                <span class="result-date">{{ dayLabel(cstDay(item.event_at)) }} · {{ timeLabel(item.event_at) }}</span>
              </div>
              <div class="result-snippet saved-snippet">{{ item.content }}</div>
              <div class="saved-actions">
                <button type="button" @click="gotoSaved(item)"><ArrowRight :size="15" />回到当时</button>
                <button type="button" @click="onRemoveSaved(item.id)"><Trash2 :size="15" />取消收藏</button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </section>
  </div>
</template>

