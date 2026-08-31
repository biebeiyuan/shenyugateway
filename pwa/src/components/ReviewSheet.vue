<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowRight,
  Bookmark,
  BookmarkCheck,
  CalendarDays,
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
const archiveScroll = ref<HTMLElement | null>(null)
let archiveLoaded = false

async function loadArchive(focusDate?: string, focusId?: string) {
  archiveError.value = ''
  try {
    if (!days.value.length) days.value = await fetchArchiveDays(props.ctx)
    const target = focusDate || activeDay.value || days.value[days.value.length - 1]?.date
    if (!target) { archiveRows.value = []; return }
    activeDay.value = target
    archiveRows.value = await fetchArchiveMessages(props.ctx, { date: target, aroundDays: 1 })
    archiveLoaded = true
    await nextTick()
    if (focusId) flashTo(focusId)
    else scrollToDivider(target)
  } catch {
    archiveError.value = '这天的对话暂时拿不到，待会儿再试试。'
  }
}

function scrollToDivider(date: string) {
  const el = archiveScroll.value?.querySelector(`[data-anchor="${date}"]`)
  el?.scrollIntoView({ block: 'start' })
}

function flashTo(id: string) {
  const el = archiveScroll.value?.querySelector(`#rev-${cssId(id)}`) as HTMLElement | null
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('flash')
  setTimeout(() => el.classList.remove('flash'), 1750)
}

function cssId(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, '')
}

function pickDay(date: string) {
  activeDay.value = date
  loadArchive(date)
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

      <div class="review-body">
        <!-- 搜索 -->
        <div v-show="tab === 'search'" class="review-pane">
          <div class="search-field" :class="{ 'has-text': query }">
            <Search :size="18" />
            <input ref="searchInput" v-model="query" placeholder="搜一句你记得的话…" autocomplete="off" @keydown.enter="runSearch" />
            <button v-if="query" class="clear" aria-label="清除" title="清除" @click="clearSearch"><X :size="16" /></button>
          </div>

          <div v-if="!query" class="review-empty">
            <span class="ic"><Search :size="22" /></span>
            <p>搜一句你记得的话。</p>
            <p class="sub">字面匹配——你敲的字，就是要找的字。</p>
          </div>
          <div v-else-if="searchError" class="review-empty"><p>{{ searchError }}</p></div>
          <div v-else-if="!searching && !searchResults.length" class="review-empty">
            <span class="ic"><Search :size="22" /></span>
            <p>没找到「{{ query.trim() }}」。</p>
            <p class="sub">换个词，或者切到「按天翻」慢慢找。</p>
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
          <div v-if="days.length" class="day-strip">
            <button v-for="day in days" :key="day.date" class="day-pill" :class="{ active: day.date === activeDay }" type="button" @click="pickDay(day.date)">{{ dayLabel(day.date) }}</button>
          </div>
          <div v-if="archiveError" class="review-empty"><p>{{ archiveError }}</p></div>
          <div v-else ref="archiveScroll" class="archive-scroll">
            <template v-for="row in archiveRows" :key="row.id">
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
            <p>还没有收藏。</p>
            <p class="sub">在「按天翻」里点消息旁的书签，存到这儿。</p>
          </div>
          <template v-else>
            <div class="saved-intro">这些是你私下留起来的话。安静待在这儿，不打扰谁，也不进沈予的记忆——除非你想。</div>
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

