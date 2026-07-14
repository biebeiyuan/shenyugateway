<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  NThing,
  useMessage,
} from 'naive-ui'
import { fetchConfig, saveConfig } from '@/api/config'
import {
  fetchCalendarContextSnapshots,
  fetchCalendarMonth,
  fetchCalendarPage,
  fetchCalendarPrompts,
  fetchCalendarSendPreview,
  generateCalendarPage,
  saveCalendarPrompt,
  type CalendarContextSnapshot,
  type CalendarMonthResponse,
  type CalendarPageDetail,
  type CalendarPeriodType,
  type CalendarPromptsResponse,
  type CalendarSendPreview,
} from '@/api/calendar'

const message = useMessage()

const periodType = ref<CalendarPeriodType>('day')
const periodKey = ref(defaultPeriodKey('day'))
const monthKey = ref(currentMonth())
const prompts = ref<CalendarPromptsResponse | null>(null)
const monthData = ref<CalendarMonthResponse | null>(null)
const snapshots = ref<CalendarContextSnapshot[]>([])
const selectedSessionTag = ref('')
const selectedPage = ref<CalendarPageDetail | null>(null)
const preview = ref<CalendarSendPreview | null>(null)
const loading = ref(false)
const generating = ref(false)
const savingPrompt = ref(false)
const savingUpstream = ref(false)
const promptName = ref('')
const promptContent = ref('')
const calendarModel = ref('')
const calendarUpstreamUrl = ref('')
const calendarApiKey = ref('')
const calendarProtocol = ref('auto')
const savingCalendarContext = ref(false)
const calendarInjectDay = ref(true)
const calendarInjectWeek = ref(true)
const calendarInjectMonth = ref(true)
const calendarContextDayLimit = ref(3)
const calendarContextWeekLimit = ref(1)
const calendarContextMonthLimit = ref(1)

const periodOptions = [
  { label: '天', value: 'day' },
  { label: '周', value: 'week' },
  { label: '月', value: 'month' },
]

const protocolOptions = [
  { label: '自动检测', value: 'auto' },
  { label: 'OpenAI 兼容', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
]

const activePrompt = computed(() => prompts.value?.active?.[periodType.value] || prompts.value?.items?.[periodType.value]?.[0] || null)

onMounted(loadAll)

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadUpstream(), loadPrompts(), loadSnapshots(), loadMonth()])
  } finally {
    loading.value = false
  }
}

async function loadUpstream() {
  try {
    const config = await fetchConfig()
    calendarUpstreamUrl.value = config.calendar_upstream_url || config.upstream_url || ''
    calendarApiKey.value = config.calendar_api_key || config.upstream_api_key || ''
    calendarProtocol.value = config.calendar_protocol || config.upstream_protocol || 'auto'
    calendarModel.value = config.calendar_model || 'claude-opus-4-7'
    calendarInjectDay.value = config.calendar_inject_day ?? true
    calendarInjectWeek.value = config.calendar_inject_week ?? true
    calendarInjectMonth.value = config.calendar_inject_month ?? true
    calendarContextDayLimit.value = config.calendar_context_day_limit ?? 3
    calendarContextWeekLimit.value = config.calendar_context_week_limit ?? 1
    calendarContextMonthLimit.value = config.calendar_context_month_limit ?? 1
  } catch {
    message.error('加载日历上游配置失败')
  }
}

async function saveUpstream() {
  savingUpstream.value = true
  try {
    await saveConfig({
      calendar_upstream_url: calendarUpstreamUrl.value.trim(),
      calendar_api_key: calendarApiKey.value.trim(),
      calendar_protocol: calendarProtocol.value,
      calendar_model: calendarModel.value.trim() || 'claude-opus-4-7',
    } as any)
    message.success('日历上游配置已保存')
  } catch {
    message.error('日历上游配置保存失败')
  } finally {
    savingUpstream.value = false
  }
}

async function saveCalendarContext() {
  savingCalendarContext.value = true
  try {
    await saveConfig({
      calendar_inject_day: calendarInjectDay.value,
      calendar_inject_week: calendarInjectWeek.value,
      calendar_inject_month: calendarInjectMonth.value,
      calendar_context_day_limit: calendarContextDayLimit.value,
      calendar_context_week_limit: calendarContextWeekLimit.value,
      calendar_context_month_limit: calendarContextMonthLimit.value,
    } as any)
    message.success('日历上下文注入配置已保存')
  } catch {
    message.error('日历上下文注入配置保存失败')
  } finally {
    savingCalendarContext.value = false
  }
}

async function loadPrompts() {
  try {
    prompts.value = await fetchCalendarPrompts()
    renderPrompt()
  } catch {
    message.error('加载日历提示词失败')
  }
}

function renderPrompt() {
  const prompt = activePrompt.value
  promptName.value = prompt?.name || ''
  promptContent.value = prompt?.content || ''
}

async function savePrompt() {
  savingPrompt.value = true
  try {
    await saveCalendarPrompt({
      prompt_type: periodType.value,
      name: promptName.value.trim() || `${periodType.value} prompt`,
      content: promptContent.value,
      is_active: true,
    })
    message.success('提示词已保存为新版本')
    await loadPrompts()
  } catch {
    message.error('提示词保存失败')
  } finally {
    savingPrompt.value = false
  }
}

async function loadSnapshots() {
  try {
    const data = await fetchCalendarContextSnapshots({ limit: 8 })
    snapshots.value = data.items || []
  } catch {
    snapshots.value = []
  }
}

async function loadMonth() {
  try {
    monthData.value = await fetchCalendarMonth(monthKey.value)
  } catch {
    monthData.value = null
    message.error('加载日历月份数据失败')
  }
}

function setPeriodType(value: CalendarPeriodType) {
  periodType.value = value
  periodKey.value = defaultPeriodKey(value)
  preview.value = null
  selectedPage.value = null
  renderPrompt()
}

function selectDate(date: string, pageId?: string) {
  periodType.value = 'day'
  periodKey.value = date
  preview.value = null
  renderPrompt()
  if (pageId) showPage(pageId)
}

async function showPage(pageId: string) {
  try {
    selectedPage.value = await fetchCalendarPage(pageId)
    preview.value = null
  } catch {
    message.error('加载日历页面失败')
  }
}

async function sendPreview() {
  try {
    preview.value = await fetchCalendarSendPreview({
      period_type: periodType.value,
      period_key: periodKey.value || defaultPeriodKey(periodType.value),
      model: calendarModel.value.trim() || undefined,
      session_tag: selectedSessionTag.value || undefined,
    })
    selectedPage.value = null
    message.success('预览已就绪')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '预览生成失败')
  }
}

async function generatePage() {
  generating.value = true
  try {
    const result = await generateCalendarPage({
      period_type: periodType.value,
      period_key: periodKey.value || defaultPeriodKey(periodType.value),
      model: calendarModel.value.trim() || undefined,
      session_tag: selectedSessionTag.value || undefined,
    })
    message.success(`已生成 ${result?.page?.title || periodKey.value}`)
    await loadMonth()
    if (result?.page?.id) await showPage(result.page.id)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '生成失败')
  } finally {
    generating.value = false
  }
}

function currentMonth() {
  return new Date().toISOString().slice(0, 7)
}

function currentWeek() {
  const now = new Date()
  const date = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()))
  const day = date.getUTCDay() || 7
  date.setUTCDate(date.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, '0')}`
}

function defaultPeriodKey(type: CalendarPeriodType) {
  if (type === 'day') return new Date().toISOString().slice(0, 10)
  if (type === 'week') return currentWeek()
  return currentMonth()
}

function shiftMonth(delta: number) {
  const [year, month] = monthKey.value.split('-').map(Number)
  const next = new Date(Date.UTC(year, month - 1 + delta, 1))
  monthKey.value = next.toISOString().slice(0, 7)
  loadMonth()
}

function previewText() {
  if (!preview.value) return ''
  return [
    `Model: ${preview.value.model}`,
    `Protocol: ${preview.value.protocol}`,
    `URL: ${preview.value.upstream_url}`,
    `Prompt: ${preview.value.prompt_name} v${preview.value.prompt_version}`,
    `Counts: ${JSON.stringify(preview.value.source_counts || {})}`,
    '',
    '--- system ---',
    preview.value.system_prompt || '',
    '',
    '--- user ---',
    preview.value.user_prompt || '',
    '',
    '--- sources ---',
    preview.value.source_block || '',
  ].join('\n')
}
</script>

<template>
    <div class="calendar-layout" data-testid="page-calendar">
      <NCard title="日历写作" size="small">
        <NSpace vertical size="medium">
          <NSelect :value="periodType" :options="periodOptions" @update:value="setPeriodType" />

          <NForm label-placement="top">
            <NFormItem label="周期标识">
              <NInput v-model:value="periodKey" placeholder="2026-05-06 / 2026-W19 / 2026-05" />
            </NFormItem>
            <NFormItem label="提示词名称">
              <NInput v-model:value="promptName" />
            </NFormItem>
            <NFormItem label="提示词内容">
              <NInput v-model:value="promptContent" type="textarea" :autosize="{ minRows: 8, maxRows: 16 }" />
            </NFormItem>
          </NForm>

          <NSpace>
            <NButton :loading="savingPrompt" @click="savePrompt">保存提示词</NButton>
            <NButton @click="loadPrompts">重新加载</NButton>
            <NButton type="primary" @click="sendPreview">发送预览</NButton>
            <NButton type="success" :loading="generating" @click="generatePage">生成页面</NButton>
          </NSpace>

          <NCard title="日历上游配置" size="small" embedded>
            <NForm label-placement="top">
              <NFormItem label="URL">
                <NInput v-model:value="calendarUpstreamUrl" placeholder="留空则继承主上游配置" />
              </NFormItem>
              <NFormItem label="API 密钥">
                <NInput v-model:value="calendarApiKey" type="password" show-password-on="click" />
              </NFormItem>
              <NFormItem label="模型">
                <NInput v-model:value="calendarModel" placeholder="claude-opus-4-7" />
              </NFormItem>
              <NFormItem label="协议">
                <NSelect v-model:value="calendarProtocol" :options="protocolOptions" />
              </NFormItem>
            </NForm>
            <NButton :loading="savingUpstream" @click="saveUpstream">保存配置</NButton>
          </NCard>

          <NCard title="上下文线程" size="small" embedded>
            <NSpace vertical size="small">
              <NThing
                class="thread"
                :class="{ active: !selectedSessionTag }"
                title="所有近期线程"
                description="使用最近时间窗口的上下文快照"
                @click="selectedSessionTag = ''"
              />
              <NThing
                v-for="item in snapshots"
                :key="item.id"
                class="thread"
                :class="{ active: selectedSessionTag === item.session_tag }"
                :title="item.session_tag || '(空)'"
                :description="`${item.client_name || 'unknown'} / ${item.created_at} / ${(item.messages || []).length} 条消息`"
                @click="selectedSessionTag = item.session_tag || ''"
              >
                <template #footer>{{ item.latest_user_text }}</template>
              </NThing>
            </NSpace>
          </NCard>

          <NCard title="日历上下文注入" size="small" embedded>
            <NForm label-placement="left" label-width="70">
              <NFormItem label="日">
                <div class="inject-row">
                  <NSwitch v-model:value="calendarInjectDay" />
                  <NInputNumber v-model:value="calendarContextDayLimit" :min="1" :max="30" size="small" />
                </div>
              </NFormItem>
              <NFormItem label="周">
                <div class="inject-row">
                  <NSwitch v-model:value="calendarInjectWeek" />
                  <NInputNumber v-model:value="calendarContextWeekLimit" :min="1" :max="12" size="small" />
                </div>
              </NFormItem>
              <NFormItem label="月">
                <div class="inject-row">
                  <NSwitch v-model:value="calendarInjectMonth" />
                  <NInputNumber v-model:value="calendarContextMonthLimit" :min="1" :max="12" size="small" />
                </div>
              </NFormItem>
            </NForm>
            <NButton :loading="savingCalendarContext" @click="saveCalendarContext">保存注入配置</NButton>
          </NCard>
        </NSpace>
      </NCard>

      <div class="right-stack">
        <NCard title="日历概览" size="small" :loading="loading">
          <div class="month-head">
            <NButton size="small" @click="shiftMonth(-1)">上个月</NButton>
            <NInput v-model:value="monthKey" class="month-input" />
            <NButton size="small" @click="shiftMonth(1)">下个月</NButton>
            <NButton size="small" @click="loadMonth">刷新</NButton>
          </div>

          <div class="month-grid">
            <div v-for="day in ['一', '二', '三', '四', '五', '六', '日']" :key="day" class="weekday">{{ day }}</div>
            <button
              v-for="item in monthData?.grid || []"
              :key="item.date"
              class="day-cell"
              :class="{ off: !item.in_month }"
              @click="selectDate(item.date, item.day_page?.id)"
            >
              <span>{{ item.day }}</span>
              <span class="marks">
                <NTag v-if="item.has_day" size="small" type="success">日</NTag>
                <NTag v-if="item.has_week" size="small" type="warning">周</NTag>
                <NTag v-if="item.has_month" size="small" type="info">月</NTag>
              </span>
            </button>
          </div>
        </NCard>

        <NCard title="页面列表" size="small">
          <div class="page-lists">
            <section v-for="type in (['day', 'week', 'month'] as CalendarPeriodType[])" :key="type">
              <h2>{{ { day: '日', week: '周', month: '月' }[type] }}</h2>
              <button v-for="page in monthData?.pages?.[type] || []" :key="page.id" class="page-row" @click="showPage(page.id)">
                <b>{{ page.period_key }} {{ page.title }}</b>
                <span>{{ page.summary }}</span>
              </button>
              <NEmpty v-if="!(monthData?.pages?.[type] || []).length" size="small" description="暂无页面" />
            </section>
          </div>
        </NCard>

        <NCard title="详情" size="small">
          <template v-if="preview">
            <pre>{{ previewText() }}</pre>
          </template>
          <template v-else-if="selectedPage">
            <h2>{{ selectedPage.period_type }} / {{ selectedPage.period_key }} / {{ selectedPage.title }}</h2>
            <pre>{{ selectedPage.content }}</pre>
            <h2>摘要</h2>
            <pre>{{ selectedPage.digest }}</pre>
          </template>
          <NEmpty v-else description="请预览或选择一个页面" />
        </NCard>
      </div>
    </div>
</template>

<style scoped>
.calendar-layout {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(360px, 440px) minmax(520px, 1fr);
  margin: 0 auto;
  max-width: 1280px;
}

.right-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.month-head {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.month-input {
  max-width: 120px;
}

.month-grid {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.weekday {
  color: #999;
  font-size: 12px;
  padding: 4px 0;
  text-align: center;
}

.day-cell {
  aspect-ratio: 1.2;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  color: #1f1f1f;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 0;
  padding: 7px;
  text-align: left;
}

.day-cell:hover {
  border-color: #c094a8;
}

.day-cell.off {
  opacity: 0.35;
}

.marks {
  display: flex;
  gap: 4px;
  min-height: 22px;
}

.inject-row {
  align-items: center;
  display: grid;
  gap: 12px;
  grid-template-columns: auto minmax(110px, 1fr);
  width: 100%;
}

.page-lists {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.page-lists h2,
.n-card h2 {
  font-size: 13px;
  margin: 0 0 8px;
}

.page-row {
  background: transparent;
  border: 0;
  border-bottom: 1px solid #e8e8e8;
  cursor: pointer;
  display: block;
  padding: 8px 0;
  text-align: left;
  width: 100%;
}

.page-row b,
.page-row span {
  display: block;
  overflow-wrap: anywhere;
}

.page-row span {
  color: #999;
  font-size: 12px;
  line-height: 1.45;
  margin-top: 2px;
}

.thread {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  cursor: pointer;
  padding: 8px;
}

.thread.active {
  border-color: #c094a8;
}

pre {
  background: #fafafa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  color: #1f1f1f;
  line-height: 1.5;
  margin: 0;
  max-height: 560px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 960px) {
  .calendar-layout,
  .page-lists {
    grid-template-columns: 1fr;
  }
}
</style>
