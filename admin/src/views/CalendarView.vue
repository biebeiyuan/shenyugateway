<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { NButton, NInputNumber, NSwitch, useMessage } from 'naive-ui'
import { fetchConfig, saveConfig } from '@/api/config'
import {
  fetchCalendarMonth,
  fetchCalendarPage,
  type CalendarGridItem,
  type CalendarMonthResponse,
  type CalendarPageDetail,
  type CalendarPageListItem,
  type CalendarPeriodType,
} from '@/api/calendar'

const message = useMessage()

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const todayKey = new Date().toISOString().slice(0, 10)
const monthKey = ref(todayKey.slice(0, 7))
const monthData = ref<CalendarMonthResponse | null>(null)
const selectedDate = ref('')
const selectedPage = ref<CalendarPageDetail | null>(null)
const listTab = ref<CalendarPeriodType>('day')

const settingsOpen = ref(false)
const settingsLoaded = ref(false)
const savingSettings = ref(false)
const injectDay = ref(true)
const injectWeek = ref(true)
const injectMonth = ref(true)
const limitDay = ref(3)
const limitWeek = ref(1)
const limitMonth = ref(1)

const grid = computed(() => monthData.value?.grid || [])
const isCurrentMonth = computed(() => monthKey.value === todayKey.slice(0, 7))

const monthTitle = computed(() => {
  const [year, month] = monthKey.value.split('-').map(Number)
  return `${year} 年 ${month} 月`
})

const gridWeekKeys = computed(() => new Set(grid.value.map((cell) => cell.week_key)))

const dayEntries = computed(() => monthData.value?.pages.day || [])
const weekEntries = computed(() =>
  (monthData.value?.pages.week || []).filter((page) => gridWeekKeys.value.has(page.period_key)),
)
const monthEntries = computed(() =>
  (monthData.value?.pages.month || []).filter((page) => page.period_key === monthKey.value),
)

const tabs = computed(() => [
  { key: 'day' as CalendarPeriodType, label: '日记', count: dayEntries.value.length },
  { key: 'week' as CalendarPeriodType, label: '周记', count: weekEntries.value.length },
  { key: 'month' as CalendarPeriodType, label: '月记', count: monthEntries.value.length },
])

const currentEntries = computed(() => {
  if (listTab.value === 'week') return weekEntries.value
  if (listTab.value === 'month') return monthEntries.value
  return dayEntries.value
})

const emptyListText = computed(() => {
  const label = tabs.value.find((tab) => tab.key === listTab.value)?.label || '日记'
  return `这个月还没有${label}。`
})

const contentSections = computed(() => {
  const raw = selectedPage.value?.content || ''
  return raw
    .split(/\n\s*---\s*\n/)
    .map((section) => section.trim())
    .filter(Boolean)
    .map((section) =>
      section
        .split(/\n{2,}/)
        .map((para) => para.trim())
        .filter(Boolean),
    )
})

const showDigest = computed(() => {
  const page = selectedPage.value
  if (!page?.digest) return false
  const normalize = (text: string) => text.replace(/[\s…]+/g, '').replace(/\.{3,}$/, '')
  const digest = normalize(page.digest)
  if (!digest) return false
  return !normalize(page.content || '').startsWith(digest)
})

const writtenAt = computed(() => formatTimestamp(selectedPage.value?.updated_at || selectedPage.value?.created_at))

const siblingEntries = computed(() => {
  const page = selectedPage.value
  if (!page || !monthData.value) return []
  const pool =
    page.period_type === 'week'
      ? weekEntries.value
      : page.period_type === 'month'
        ? monthEntries.value
        : dayEntries.value
  return [...pool].sort((a, b) => a.period_key.localeCompare(b.period_key))
})

const prevEntry = computed(() => {
  const index = siblingEntries.value.findIndex((entry) => entry.id === selectedPage.value?.id)
  return index > 0 ? siblingEntries.value[index - 1] : null
})

const nextEntry = computed(() => {
  const index = siblingEntries.value.findIndex((entry) => entry.id === selectedPage.value?.id)
  return index >= 0 && index < siblingEntries.value.length - 1 ? siblingEntries.value[index + 1] : null
})

onMounted(async () => {
  await loadMonth()
  const todayCell = grid.value.find((cell) => cell.date === todayKey)
  if (todayCell?.day_page?.id) {
    selectedDate.value = todayKey
    await openPage(todayCell.day_page.id, { scroll: false })
  } else if (dayEntries.value.length) {
    selectedDate.value = dayEntries.value[0].period_key
    await openPage(dayEntries.value[0].id, { scroll: false })
  }
})

const paperWrapRef = ref<HTMLElement | null>(null)

async function scrollToPaper() {
  await nextTick()
  if (window.innerWidth <= 1020) {
    paperWrapRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

async function loadMonth() {
  try {
    monthData.value = await fetchCalendarMonth(monthKey.value)
  } catch {
    monthData.value = null
    message.error('这个月的日历翻不开了，稍后再试试')
  }
}

async function openPage(pageId: string, options: { scroll?: boolean } = {}) {
  try {
    const page = await fetchCalendarPage(pageId)
    selectedPage.value = page
    if (page.period_type === 'day') selectedDate.value = page.period_key
    listTab.value = page.period_type
    if (options.scroll !== false) await scrollToPaper()
  } catch {
    message.error('这一页翻不开，稍后再试试')
  }
}

async function selectDay(cell: CalendarGridItem) {
  if (!cell.in_month) {
    monthKey.value = cell.month_key
    await loadMonth()
  }
  selectedDate.value = cell.date
  const pageId = monthData.value?.grid.find((item) => item.date === cell.date)?.day_page?.id
  if (pageId) {
    await openPage(pageId)
  } else {
    selectedPage.value = null
    listTab.value = 'day'
    await scrollToPaper()
  }
}

async function shiftMonth(delta: number) {
  const [year, month] = monthKey.value.split('-').map(Number)
  const next = new Date(Date.UTC(year, month - 1 + delta, 1))
  monthKey.value = next.toISOString().slice(0, 7)
  await loadMonth()
}

async function goToday() {
  monthKey.value = todayKey.slice(0, 7)
  await loadMonth()
  const todayCell = grid.value.find((cell) => cell.date === todayKey)
  if (todayCell) await selectDay(todayCell)
}

function kindLabel(type: CalendarPeriodType): string {
  return { day: '日记', week: '周记', month: '月记' }[type] || '日记'
}

function isoWeekStart(year: number, week: number): Date {
  const jan4 = new Date(Date.UTC(year, 0, 4))
  const weekday = jan4.getUTCDay() || 7
  const mondayOfW1 = new Date(jan4)
  mondayOfW1.setUTCDate(jan4.getUTCDate() - weekday + 1)
  const start = new Date(mondayOfW1)
  start.setUTCDate(mondayOfW1.getUTCDate() + (week - 1) * 7)
  return start
}

function weekRangeLabel(weekKey: string): string {
  const [yearPart, weekPart] = weekKey.split('-W')
  const start = isoWeekStart(Number(yearPart), Number(weekPart))
  const end = new Date(start)
  end.setUTCDate(start.getUTCDate() + 6)
  return `${start.getUTCMonth() + 1}.${start.getUTCDate()} – ${end.getUTCMonth() + 1}.${end.getUTCDate()}`
}

function formatDayKey(dayKey: string): string {
  const [year, month, day] = dayKey.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return `${year} 年 ${month} 月 ${day} 日 · ${WEEKDAYS[date.getUTCDay()]}`
}

function formatPeriodKey(type: CalendarPeriodType, key: string): string {
  if (type === 'week') {
    const [yearPart, weekPart] = key.split('-W')
    return `${yearPart} 年 第 ${Number(weekPart)} 周 · ${weekRangeLabel(key)}`
  }
  if (type === 'month') {
    const [year, month] = key.split('-').map(Number)
    return `${year} 年 ${month} 月`
  }
  return formatDayKey(key)
}

function entryDateLabel(entry: CalendarPageListItem): string {
  if (listTab.value === 'week') return `第 ${Number(entry.period_key.split('-W')[1] || 0)} 周 · ${weekRangeLabel(entry.period_key)}`
  if (listTab.value === 'month') return formatPeriodKey('month', entry.period_key)
  const [, month, day] = entry.period_key.split('-').map(Number)
  const date = new Date(Date.UTC(Number(entry.period_key.slice(0, 4)), month - 1, day))
  return `${month} 月 ${day} 日 · ${WEEKDAYS[date.getUTCDay()]}`
}

function entryNavLabel(entry: CalendarPageListItem, type: CalendarPeriodType): string {
  if (type === 'week') return `第 ${Number(entry.period_key.split('-W')[1] || 0)} 周`
  if (type === 'month') return `${Number(entry.period_key.split('-')[1])} 月`
  const [, month, day] = entry.period_key.split('-').map(Number)
  return `${month} 月 ${day} 日`
}

function formatTimestamp(iso?: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function toggleSettings() {
  settingsOpen.value = !settingsOpen.value
  if (settingsOpen.value && !settingsLoaded.value) {
    try {
      const config = await fetchConfig()
      injectDay.value = config.calendar_inject_day ?? true
      injectWeek.value = config.calendar_inject_week ?? true
      injectMonth.value = config.calendar_inject_month ?? true
      limitDay.value = config.calendar_context_day_limit ?? 3
      limitWeek.value = config.calendar_context_week_limit ?? 1
      limitMonth.value = config.calendar_context_month_limit ?? 1
      settingsLoaded.value = true
    } catch {
      message.error('注入配置加载失败')
    }
  }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await saveConfig({
      calendar_inject_day: injectDay.value,
      calendar_inject_week: injectWeek.value,
      calendar_inject_month: injectMonth.value,
      calendar_context_day_limit: limitDay.value,
      calendar_context_week_limit: limitWeek.value,
      calendar_context_month_limit: limitMonth.value,
    })
    message.success('注入配置已保存')
  } catch {
    message.error('注入配置保存失败')
  } finally {
    savingSettings.value = false
  }
}
</script>

<template>
  <div class="diary-layout" data-testid="page-calendar">
    <aside class="rail">
      <section class="card month-card">
        <div class="month-head">
          <button class="nav-btn" aria-label="上个月" @click="shiftMonth(-1)">‹</button>
          <div class="month-title">
            <span class="month-title-text">{{ monthTitle }}</span>
            <button v-if="!isCurrentMonth" class="today-link" @click="goToday">回到今天</button>
          </div>
          <button class="nav-btn" aria-label="下个月" @click="shiftMonth(1)">›</button>
        </div>

        <div class="weekday-row">
          <span v-for="day in ['一', '二', '三', '四', '五', '六', '日']" :key="day">{{ day }}</span>
        </div>

        <div class="day-grid">
          <button
            v-for="cell in grid"
            :key="cell.date"
            class="day-cell"
            :class="{
              off: !cell.in_month,
              today: cell.date === todayKey,
              selected: cell.date === selectedDate,
            }"
            @click="selectDay(cell)"
          >
            <span class="day-num">{{ cell.day }}</span>
            <span v-if="cell.has_day" class="day-dot"></span>
          </button>
        </div>
      </section>

      <section class="card entries-card">
        <div class="tab-row">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: listTab === tab.key }"
            @click="listTab = tab.key"
          >
            {{ tab.label }}<em v-if="tab.count">{{ tab.count }}</em>
          </button>
        </div>

        <div class="entry-list">
          <button
            v-for="entry in currentEntries"
            :key="entry.id"
            class="entry-row"
            :class="{ active: selectedPage?.id === entry.id }"
            @click="openPage(entry.id)"
          >
            <span class="entry-date">{{ entryDateLabel(entry) }}</span>
            <span class="entry-title">{{ entry.title || '未命名的一页' }}</span>
            <span v-if="entry.summary" class="entry-summary">{{ entry.summary }}</span>
          </button>
          <p v-if="!currentEntries.length" class="entry-empty">{{ emptyListText }}</p>
        </div>
      </section>

      <section class="card settings-card">
        <button class="settings-toggle" @click="toggleSettings">
          <span>上下文注入</span>
          <span class="chev" :class="{ open: settingsOpen }">›</span>
        </button>
        <div v-if="settingsOpen" class="settings-body">
          <p class="settings-hint">她醒来时，随身带上最近的几页。</p>
          <div class="settings-row">
            <span class="settings-label">日记</span>
            <NSwitch v-model:value="injectDay" size="small" />
            <NInputNumber v-model:value="limitDay" :min="1" :max="30" size="small" :disabled="!injectDay" />
          </div>
          <div class="settings-row">
            <span class="settings-label">周记</span>
            <NSwitch v-model:value="injectWeek" size="small" />
            <NInputNumber v-model:value="limitWeek" :min="1" :max="12" size="small" :disabled="!injectWeek" />
          </div>
          <div class="settings-row">
            <span class="settings-label">月记</span>
            <NSwitch v-model:value="injectMonth" size="small" />
            <NInputNumber v-model:value="limitMonth" :min="1" :max="12" size="small" :disabled="!injectMonth" />
          </div>
          <NButton size="small" :loading="savingSettings" @click="saveSettings">保存</NButton>
        </div>
      </section>
    </aside>

    <main ref="paperWrapRef" class="paper-wrap">
      <article v-if="selectedPage" class="paper">
        <header class="paper-head">
          <div class="paper-eyebrow">
            <span class="kind-chip">{{ kindLabel(selectedPage.period_type) }}</span>
            <span class="paper-date">{{ formatPeriodKey(selectedPage.period_type, selectedPage.period_key) }}</span>
            <span v-if="(selectedPage.version || 1) > 1" class="version-chip">第 {{ selectedPage.version }} 稿</span>
          </div>
          <h1 class="paper-title">{{ selectedPage.title || '未命名的一页' }}</h1>
        </header>

        <div class="paper-body">
          <template v-for="(section, sectionIndex) in contentSections" :key="sectionIndex">
            <div v-if="sectionIndex > 0" class="section-divider"><span>✦</span></div>
            <p v-for="(para, paraIndex) in section" :key="`${sectionIndex}-${paraIndex}`" class="para">{{ para }}</p>
          </template>
          <p v-if="!contentSections.length" class="para para-blank">这一页是空白的。</p>
        </div>

        <footer class="paper-foot">
          <span class="signature">—— {{ selectedPage.author || '沈予' }}</span>
          <span v-if="writtenAt" class="written-at">写于 {{ writtenAt }}</span>
        </footer>

        <aside v-if="showDigest" class="digest">
          <span class="digest-label">摘一句</span>
          <p>{{ selectedPage.digest }}</p>
        </aside>

        <nav v-if="prevEntry || nextEntry" class="paper-nav">
          <button v-if="prevEntry" class="nav-page" @click="openPage(prevEntry.id)">
            ‹ {{ entryNavLabel(prevEntry, selectedPage.period_type) }}
          </button>
          <span class="nav-spacer"></span>
          <button v-if="nextEntry" class="nav-page" @click="openPage(nextEntry.id)">
            {{ entryNavLabel(nextEntry, selectedPage.period_type) }} ›
          </button>
        </nav>
      </article>

      <div v-else class="paper paper-empty">
        <span class="empty-mark">✦</span>
        <p v-if="selectedDate">{{ formatDayKey(selectedDate) }}<br />这一天，她还没有写下什么。</p>
        <p v-else>从左边挑一天，翻开那一页。</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.diary-layout {
  display: grid;
  gap: 18px;
  grid-template-columns: 320px minmax(0, 1fr);
  margin: 0 auto;
  max-width: 1180px;
}

.rail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.card {
  background: #fff;
  border: 1px solid #f2ddd8;
  border-radius: 18px;
  padding: 16px;
}

/* ---- month calendar ---- */

.month-head {
  align-items: center;
  display: flex;
  gap: 6px;
  justify-content: space-between;
  margin-bottom: 10px;
}

.month-title {
  align-items: baseline;
  display: flex;
  gap: 10px;
}

.month-title-text {
  color: #4a3535;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', Georgia, serif;
  font-size: 16.5px;
  font-weight: 600;
  letter-spacing: 1px;
}

.today-link {
  background: none;
  border: 0;
  color: #c094a8;
  cursor: pointer;
  font-size: 11px;
  padding: 0;
}

.today-link:hover {
  text-decoration: underline;
}

.nav-btn {
  align-items: center;
  background: none;
  border: 0;
  border-radius: 8px;
  color: #b8a8a3;
  cursor: pointer;
  display: flex;
  font-size: 18px;
  height: 26px;
  justify-content: center;
  line-height: 1;
  width: 26px;
}

.nav-btn:hover {
  background: #faf0ee;
  color: #c094a8;
}

.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  margin-bottom: 4px;
}

.weekday-row span {
  color: #cbb8b3;
  font-size: 10.5px;
  padding: 4px 0;
  text-align: center;
}

.day-grid {
  display: grid;
  gap: 2px;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.day-cell {
  align-items: center;
  aspect-ratio: 1;
  background: none;
  border: 0;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  justify-content: center;
  min-width: 0;
  padding: 0;
  position: relative;
  transition: background 0.15s;
}

.day-cell:hover {
  background: #faf0ee;
}

.day-cell.off {
  opacity: 0.3;
}

.day-num {
  color: #6b5454;
  font-size: 12.5px;
  line-height: 1;
}

.day-dot {
  background: #c094a8;
  border-radius: 50%;
  height: 4px;
  width: 4px;
}

.day-cell.today {
  box-shadow: inset 0 0 0 1px #c094a8;
}

.day-cell.selected {
  background: #c094a8;
}

.day-cell.selected:hover {
  background: #b08898;
}

.day-cell.selected .day-num {
  color: #fff;
}

.day-cell.selected .day-dot {
  background: #fff;
}

/* ---- entry list ---- */

.tab-row {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.tab-btn {
  background: none;
  border: 0;
  border-radius: 999px;
  color: #b8a8a3;
  cursor: pointer;
  font-size: 12px;
  padding: 4px 12px;
  transition: 0.15s;
}

.tab-btn em {
  font-size: 10px;
  font-style: normal;
  margin-left: 3px;
  opacity: 0.75;
}

.tab-btn:hover {
  color: #8b7082;
}

.tab-btn.active {
  background: #faf0ee;
  color: #8b7082;
}

.entry-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  overflow-y: auto;
}

.entry-row {
  background: none;
  border: 0;
  border-radius: 12px;
  cursor: pointer;
  display: block;
  padding: 9px 12px;
  text-align: left;
  transition: background 0.15s;
  width: 100%;
}

.entry-row:hover {
  background: #fdf6f4;
}

.entry-row.active {
  background: #faf0ee;
}

.entry-date {
  color: #b8a8a3;
  display: block;
  font-size: 10.5px;
  letter-spacing: 0.5px;
}

.entry-title {
  color: #4a3535;
  display: block;
  font-size: 13.5px;
  font-weight: 600;
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.entry-summary {
  -webkit-box-orient: vertical;
  color: #b8a8a3;
  display: -webkit-box;
  font-size: 11.5px;
  -webkit-line-clamp: 2;
  line-height: 1.5;
  margin-top: 2px;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.entry-empty {
  color: #cbb8b3;
  font-size: 12px;
  margin: 6px 0;
  padding: 4px 12px;
}

/* ---- injection settings ---- */

.settings-card {
  padding: 6px 8px;
}

.settings-toggle {
  align-items: center;
  background: none;
  border: 0;
  color: #b8a8a3;
  cursor: pointer;
  display: flex;
  font-size: 12px;
  justify-content: space-between;
  letter-spacing: 1px;
  padding: 8px 10px;
  width: 100%;
}

.settings-toggle:hover {
  color: #8b7082;
}

.chev {
  display: inline-block;
  font-size: 14px;
  transition: transform 0.2s;
}

.chev.open {
  transform: rotate(90deg);
}

.settings-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 10px 12px;
}

.settings-hint {
  color: #cbb8b3;
  font-size: 11px;
  margin: 0;
}

.settings-row {
  align-items: center;
  display: grid;
  gap: 10px;
  grid-template-columns: 30px auto minmax(90px, 1fr);
}

.settings-label {
  color: #6b5454;
  font-size: 12px;
}

/* ---- reading paper ---- */

.paper-wrap {
  min-width: 0;
}

.paper {
  background: #fff;
  border: 1px solid #f2ddd8;
  border-radius: 18px;
  box-shadow: 0 10px 34px rgba(192, 148, 168, 0.09);
  margin: 0 auto;
  max-width: 760px;
  padding: 44px 48px 36px;
}

.paper-head {
  margin-bottom: 26px;
}

.paper-eyebrow {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.kind-chip {
  background: #faf0ee;
  border-radius: 999px;
  color: #a08090;
  font-size: 11px;
  letter-spacing: 2px;
  padding: 3px 10px 3px 12px;
}

.paper-date {
  color: #b8a8a3;
  font-size: 12.5px;
  letter-spacing: 1px;
}

.version-chip {
  color: #d4c0bb;
  font-size: 10.5px;
}

.paper-title {
  color: #4a3535;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', Georgia, serif;
  font-size: 25px;
  font-weight: 600;
  letter-spacing: 0.5px;
  line-height: 1.4;
  margin: 0;
}

.paper-body {
  color: #4a3535;
}

.para {
  font-size: 15.5px;
  letter-spacing: 0.02em;
  line-height: 2.1;
  margin: 0 0 1.05em;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.para:last-child {
  margin-bottom: 0;
}

.para-blank {
  color: #cbb8b3;
}

.section-divider {
  align-items: center;
  color: #ddbfcc;
  display: flex;
  gap: 14px;
  margin: 26px 0;
}

.section-divider::before,
.section-divider::after {
  background: #f2ddd8;
  content: '';
  flex: 1;
  height: 1px;
}

.section-divider span {
  font-size: 11px;
}

.paper-foot {
  align-items: baseline;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 30px;
  text-align: right;
}

.signature {
  align-self: flex-end;
  color: #a08090;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', Georgia, serif;
  font-size: 15.5px;
}

.written-at {
  align-self: flex-end;
  color: #d4c0bb;
  font-size: 11px;
  letter-spacing: 0.5px;
}

.digest {
  background: #fdf6f4;
  border-left: 3px solid #e3c3d0;
  border-radius: 12px;
  margin-top: 30px;
  padding: 14px 18px;
}

.digest-label {
  color: #b8a8a3;
  display: block;
  font-size: 10.5px;
  letter-spacing: 3px;
  margin-bottom: 6px;
}

.digest p {
  color: #6b5454;
  font-size: 13.5px;
  line-height: 1.9;
  margin: 0;
}

.paper-nav {
  border-top: 1px solid #f7e8e4;
  display: flex;
  margin-top: 30px;
  padding-top: 14px;
}

.nav-page {
  background: none;
  border: 0;
  color: #b8a8a3;
  cursor: pointer;
  font-size: 12.5px;
  padding: 4px 0;
  transition: color 0.15s;
}

.nav-page:hover {
  color: #c094a8;
}

.nav-spacer {
  flex: 1;
}

.paper-empty {
  align-items: center;
  color: #b8a8a3;
  display: flex;
  flex-direction: column;
  gap: 14px;
  justify-content: center;
  min-height: 340px;
  text-align: center;
}

.empty-mark {
  color: #e3c3d0;
  font-size: 18px;
}

.paper-empty p {
  font-size: 13.5px;
  line-height: 2;
  margin: 0;
}

@media (max-width: 1020px) {
  .diary-layout {
    grid-template-columns: 1fr;
  }

  .paper {
    padding: 28px 22px 26px;
  }

  .entry-list {
    max-height: none;
  }
}
</style>
