<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NCheckbox,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import { fetchConfig, saveConfig, type GatewayConfig } from '@/api/config'
import {
  connectStars,
  createStar,
  fetchStars,
  markConstantStar,
  reviewStars,
  searchStars,
  sendStarFeedback,
  type StarCandidate,
  type StarItem,
  type StarReviewItem,
  type StarStatus,
} from '@/api/stars'

const message = useMessage()

const STAR_DEFAULTS: Partial<GatewayConfig> = {
  inject_star_prompt: true,
  enable_inline_star_capture: true,
  inject_stars: true,
  enable_gateway_tools: true,
  enable_star_embeddings: false,
  star_inject_limit: 3,
  star_review_new_limit: 5,
  star_review_candidates_per_star: 3,
  star_review_total_candidate_limit: 15,
  star_candidate_limit: 500,
  star_shadow_candidate_limit: 20,
  star_weight_content: 0.3,
  star_weight_keyword: 0.2,
  star_weight_harmony: 0.35,
  star_weight_chord: 0.18,
  star_weight_actr: 0.08,
  star_constant_bonus: 0.08,
  star_novelty_bonus: 0.04,
  star_ignored_penalty: 0.18,
}

const statusOptions = [
  { label: '会参与', value: 'active' },
  { label: '暂停', value: 'paused' },
  { label: '归档', value: 'archived' },
  { label: '全部', value: 'all' },
]

const reviewedOptions = [
  { label: '全部', value: 'all' },
  { label: '未 review', value: 'unreviewed' },
  { label: '已 review', value: 'reviewed' },
]

const config = ref<Partial<GatewayConfig>>({ ...STAR_DEFAULTS })
const savingConfig = ref(false)

const stars = ref<StarItem[]>([])
const loadingStars = ref(false)
const starStatus = ref<StarStatus | 'all'>('active')
const starReviewed = ref<'all' | 'reviewed' | 'unreviewed'>('all')
const starQuery = ref('')
const starSessionTag = ref('')
const starLimit = ref(50)

const searchQuery = ref('')
const searchResults = ref<StarCandidate[]>([])
const searchRunId = ref<string | null>(null)
const searching = ref(false)

const createContent = ref('')
const createChord = ref('')
const createSessionTag = ref('')
const createConstant = ref(false)
const creating = ref(false)

const reviewItems = ref<StarReviewItem[]>([])
const reviewSessionTag = ref('')
const reviewing = ref(false)
const feedbackingKey = ref('')
const missedStarId = ref<Record<string, string>>({})
const connectName = ref('')
const connectNote = ref('')

const selectedStarIds = ref<string[]>([])
const selectedStars = computed(() => stars.value.filter((item) => selectedStarIds.value.includes(item.id)))

onMounted(async () => {
  await Promise.all([loadConfig(), loadStars()])
})

async function loadConfig() {
  try {
    const data = await fetchConfig()
    config.value = { ...STAR_DEFAULTS, ...data }
  } catch {
    message.error('读取 Star 设置失败')
  }
}

async function saveSettings() {
  savingConfig.value = true
  try {
    const result = await saveConfig({
      inject_star_prompt: config.value.inject_star_prompt,
      enable_inline_star_capture: config.value.enable_inline_star_capture,
      inject_stars: config.value.inject_stars,
      enable_gateway_tools: config.value.enable_gateway_tools,
      enable_star_embeddings: config.value.enable_star_embeddings,
      star_inject_limit: config.value.star_inject_limit,
      star_review_new_limit: config.value.star_review_new_limit,
      star_review_candidates_per_star: config.value.star_review_candidates_per_star,
      star_review_total_candidate_limit: config.value.star_review_total_candidate_limit,
      star_candidate_limit: config.value.star_candidate_limit,
      star_shadow_candidate_limit: config.value.star_shadow_candidate_limit,
      star_weight_content: config.value.star_weight_content,
      star_weight_keyword: config.value.star_weight_keyword,
      star_weight_harmony: config.value.star_weight_harmony,
      star_weight_chord: config.value.star_weight_chord,
      star_weight_actr: config.value.star_weight_actr,
      star_constant_bonus: config.value.star_constant_bonus,
      star_novelty_bonus: config.value.star_novelty_bonus,
      star_ignored_penalty: config.value.star_ignored_penalty,
    })
    config.value = { ...config.value, ...result.config }
    message.success('Star 设置已保存')
  } catch {
    message.error('保存 Star 设置失败')
  } finally {
    savingConfig.value = false
  }
}

function resetStarDefaults() {
  config.value = { ...config.value, ...STAR_DEFAULTS }
  message.info('已恢复 Star 默认值，保存后生效')
}

function setStarQuietTools() {
  config.value.inject_star_prompt = false
  config.value.enable_inline_star_capture = false
  config.value.inject_stars = false
  config.value.enable_gateway_tools = true
  message.info('已关闭提示、捕获和注入，并保留网关工具；保存后生效')
}

async function loadStars() {
  loadingStars.value = true
  try {
    const result = await fetchStars({
      status: starStatus.value,
      reviewed: starReviewed.value,
      q: starQuery.value.trim() || undefined,
      session_tag: starSessionTag.value.trim() || undefined,
      limit: Number(starLimit.value || 50),
    })
    stars.value = result.items || []
    const visible = new Set(stars.value.map((item) => item.id))
    selectedStarIds.value = selectedStarIds.value.filter((id) => visible.has(id))
  } catch {
    stars.value = []
    message.error('读取星星失败')
  } finally {
    loadingStars.value = false
  }
}

async function runSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    searchRunId.value = null
    return
  }
  searching.value = true
  try {
    const result = await searchStars({
      q,
      session_tag: starSessionTag.value.trim() || undefined,
      limit: 12,
      log_run: true,
    })
    searchResults.value = result.items || []
    searchRunId.value = result.run_id || null
  } catch {
    message.error('搜索星星失败')
  } finally {
    searching.value = false
  }
}

async function addStar() {
  const content = createContent.value.trim()
  if (!content) return
  creating.value = true
  try {
    await createStar({
      content,
      chord: createChord.value.trim(),
      session_tag: createSessionTag.value.trim() || undefined,
      status: 'active',
      is_constant: createConstant.value,
      metadata: { surface: 'admin' },
    })
    createContent.value = ''
    createChord.value = ''
    createConstant.value = false
    message.success('星星已写入')
    await loadStars()
  } catch {
    message.error('写入星星失败')
  } finally {
    creating.value = false
  }
}

async function runReview() {
  reviewing.value = true
  try {
    const result = await reviewStars({
      limit_new: config.value.star_review_new_limit || 5,
      candidates_per_star: config.value.star_review_candidates_per_star || 3,
      total_candidate_limit: config.value.star_review_total_candidate_limit || 15,
      session_tag: reviewSessionTag.value.trim() || undefined,
    })
    reviewItems.value = result.items || []
    missedStarId.value = {}
    message.success(`拿到 ${reviewItems.value.length} 颗新星`)
    await loadStars()
  } catch {
    message.error('Review 失败')
  } finally {
    reviewing.value = false
  }
}

async function feedbackCandidate(seed: StarItem, candidate: StarCandidate, feedback: 'positive' | 'negative' | 'skipped') {
  const key = `${seed.id}:${candidate.id}:${feedback}`
  feedbackingKey.value = key
  try {
    await sendStarFeedback({
      feedback,
      run_id: candidate.run_id,
      candidate_id: candidate.candidate_id,
      candidate_star_id: candidate.id,
      scored_by: '圆圆',
      metadata: { surface: 'admin:stars' },
    })
    message.success(feedbackLabel(feedback))
  } catch {
    message.error('反馈失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function feedbackMissed(seed: StarItem, runId?: string | null) {
  const expected = (missedStarId.value[seed.id] || '').trim()
  if (!expected) return
  const key = `${seed.id}:missed`
  feedbackingKey.value = key
  try {
    await sendStarFeedback({
      feedback: 'missed',
      run_id: runId,
      expected_star_id: expected,
      scored_by: '圆圆',
      note: `Review ${seed.id} 时漏反`,
      metadata: { surface: 'admin:stars' },
    })
    missedStarId.value[seed.id] = ''
    message.success('已记录漏反')
  } catch {
    message.error('记录漏反失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function connectCandidate(seed: StarItem, candidate: StarCandidate) {
  const key = `${seed.id}:${candidate.id}:connect`
  feedbackingKey.value = key
  try {
    await connectStars({
      star_ids: [seed.id, candidate.id],
      name: connectName.value.trim(),
      relation_type: 'constellation',
      scored_by: '圆圆',
      note: connectNote.value.trim(),
    })
    await sendStarFeedback({
      feedback: 'connected',
      run_id: candidate.run_id,
      candidate_id: candidate.candidate_id,
      candidate_star_id: candidate.id,
      scored_by: '圆圆',
      note: connectNote.value.trim(),
      metadata: { surface: 'admin:stars' },
    })
    message.success('已连线')
  } catch {
    message.error('连线失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function connectSelected() {
  if (selectedStarIds.value.length < 2) return
  try {
    await connectStars({
      star_ids: selectedStarIds.value,
      name: connectName.value.trim(),
      relation_type: 'constellation',
      scored_by: '圆圆',
      note: connectNote.value.trim(),
    })
    selectedStarIds.value = []
    message.success('已把所选星星连成星座')
  } catch {
    message.error('连线失败')
  }
}

async function toggleConstant(star: StarItem) {
  try {
    await markConstantStar(star.id, !star.is_constant)
    star.is_constant = !star.is_constant
    message.success(star.is_constant ? '已设为恒星' : '已取消恒星')
  } catch {
    message.error('更新恒星失败')
  }
}

function toggleSelected(id: string, checked: boolean) {
  if (checked) {
    if (!selectedStarIds.value.includes(id)) selectedStarIds.value = [...selectedStarIds.value, id]
    return
  }
  selectedStarIds.value = selectedStarIds.value.filter((item) => item !== id)
}

function scoreParts(candidate: StarCandidate): string {
  const scores = candidate.scores || {}
  const labels: Array<[string, string]> = [
    ['content_score', '内容'],
    ['harmony_score', '和声'],
    ['chord_score', '和弦'],
    ['keyword_score', '关键词'],
    ['actr_score', '亮度'],
  ]
  return labels
    .filter(([key]) => scores[key] !== undefined)
    .map(([key, label]) => `${label} ${scores[key]}`)
    .join(' · ')
}

function feedbackLabel(value: string): string {
  if (value === 'positive') return '已记为该反'
  if (value === 'negative') return '已记为不该反'
  if (value === 'skipped') return '已记为跳过'
  return '已记录'
}

function statusTagType(status: string) {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'info'
  if (status === 'archived') return 'default'
  return 'default'
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}
</script>

<template>
  <div class="stars-page">
    <NCard title="Star 设置" size="small">
      <NForm label-placement="top">
        <div class="cfg-inline five">
          <NFormItem label="Star 写法提示">
            <NSwitch v-model:value="config.inject_star_prompt" />
          </NFormItem>
          <NFormItem label="自动捕获 star">
            <NSwitch v-model:value="config.enable_inline_star_capture" />
          </NFormItem>
          <NFormItem label="聊天注入">
            <NSwitch v-model:value="config.inject_stars" />
          </NFormItem>
          <NFormItem label="网关工具">
            <NSwitch v-model:value="config.enable_gateway_tools" />
          </NFormItem>
          <NFormItem label="embedding">
            <NSwitch v-model:value="config.enable_star_embeddings" />
          </NFormItem>
        </div>
        <div class="cfg-inline four">
          <NFormItem label="日常注入条数">
            <NInputNumber v-model:value="config.star_inject_limit" :min="1" :max="5" style="width:100%" />
            <span class="cfg-help">默认 3</span>
          </NFormItem>
          <NFormItem label="Review 新星">
            <NInputNumber v-model:value="config.star_review_new_limit" :min="1" :max="10" style="width:100%" />
            <span class="cfg-help">默认 5</span>
          </NFormItem>
          <NFormItem label="每星候选">
            <NInputNumber v-model:value="config.star_review_candidates_per_star" :min="1" :max="5" style="width:100%" />
            <span class="cfg-help">默认 3</span>
          </NFormItem>
          <NFormItem label="Review 总量">
            <NInputNumber v-model:value="config.star_review_total_candidate_limit" :min="1" :max="30" style="width:100%" />
            <span class="cfg-help">默认 15</span>
          </NFormItem>
        </div>
        <div class="cfg-inline five">
          <NFormItem label="内容权重">
            <NInputNumber v-model:value="config.star_weight_content" :min="0" :max="2" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="关键词权重">
            <NInputNumber v-model:value="config.star_weight_keyword" :min="0" :max="2" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="和声权重">
            <NInputNumber v-model:value="config.star_weight_harmony" :min="0" :max="2" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="和弦权重">
            <NInputNumber v-model:value="config.star_weight_chord" :min="0" :max="2" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="亮度权重">
            <NInputNumber v-model:value="config.star_weight_actr" :min="0" :max="2" :step="0.01" style="width:100%" />
          </NFormItem>
        </div>
        <div class="cfg-inline five">
          <NFormItem label="恒星加成">
            <NInputNumber v-model:value="config.star_constant_bonus" :min="0" :max="1" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="新鲜加成">
            <NInputNumber v-model:value="config.star_novelty_bonus" :min="0" :max="1" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="跳过惩罚">
            <NInputNumber v-model:value="config.star_ignored_penalty" :min="0" :max="1" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="候选池">
            <NInputNumber v-model:value="config.star_candidate_limit" :min="50" :max="5000" style="width:100%" />
          </NFormItem>
          <NFormItem label="shadow top">
            <NInputNumber v-model:value="config.star_shadow_candidate_limit" :min="3" :max="100" style="width:100%" />
          </NFormItem>
        </div>
      </NForm>
      <NSpace>
        <NButton type="primary" :loading="savingConfig" @click="saveSettings">保存设置</NButton>
        <NButton :disabled="savingConfig" @click="setStarQuietTools">静音 Star</NButton>
        <NButton :disabled="savingConfig" @click="resetStarDefaults">恢复默认</NButton>
      </NSpace>
    </NCard>

    <div class="workspace-grid">
      <NCard title="写一颗星" size="small" class="section-card">
        <NForm label-placement="top">
          <div class="cfg-inline two">
            <NFormItem label="和弦">
              <NInput v-model:value="createChord" placeholder="Am / Cmaj7 / F#" />
            </NFormItem>
            <NFormItem label="session_tag">
              <NInput v-model:value="createSessionTag" placeholder="默认 default" />
            </NFormItem>
          </div>
          <NFormItem label="内容">
            <NInput v-model:value="createContent" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" />
          </NFormItem>
          <NSpace align="center">
            <NCheckbox v-model:checked="createConstant">恒星</NCheckbox>
            <NButton type="primary" :loading="creating" :disabled="!createContent.trim()" @click="addStar">写入</NButton>
          </NSpace>
        </NForm>
      </NCard>

      <NCard title="手动搜索" size="small" class="section-card">
        <div class="rev-toolbar">
          <input v-model="searchQuery" class="cal-input wide" placeholder="按最新聊天或感觉搜星星">
          <NButton size="small" type="primary" :loading="searching" @click="runSearch">搜索</NButton>
          <NTag v-if="searchRunId" size="small">run {{ searchRunId }}</NTag>
        </div>
        <div v-if="!searchResults.length" class="rev-empty">还没有搜索结果</div>
        <div v-for="item in searchResults" :key="item.id" class="mini-row">
          <div class="rev-meta">
            <NTag size="small">{{ item.chord || '无和弦' }}</NTag>
            <NTag size="small">score {{ item.score ?? 0 }}</NTag>
            <NTag v-if="item.is_constant" size="small" type="warning">恒星</NTag>
          </div>
          <div class="star-content">{{ item.content }}</div>
          <div v-if="scoreParts(item)" class="score-line">{{ scoreParts(item) }}</div>
        </div>
      </NCard>
    </div>

    <NCard title="Review 连线" size="small" class="section-card">
      <div class="rev-toolbar">
        <input v-model="reviewSessionTag" class="cal-input short" placeholder="session_tag">
        <input v-model="connectName" class="cal-input" placeholder="星座名（可选）">
        <input v-model="connectNote" class="cal-input" placeholder="连线备注（可选）">
        <NButton type="primary" size="small" :loading="reviewing" @click="runReview">拿新星</NButton>
      </div>
      <div v-if="!reviewItems.length" class="rev-empty">还没有 review 批次</div>
      <div v-for="item in reviewItems" :key="item.star.id" class="review-block">
        <div class="seed-col">
          <div class="rev-meta">
            <NTag size="small" type="success">新星</NTag>
            <NTag size="small">{{ item.star.chord || '无和弦' }}</NTag>
            <NTag size="small">{{ item.star.session_tag || 'default' }}</NTag>
          </div>
          <div class="star-content seed">{{ item.star.content }}</div>
          <div class="missed-row">
            <input v-model="missedStarId[item.star.id]" class="cal-input" placeholder="漏反的 star id">
            <NButton size="small" :loading="feedbackingKey === `${item.star.id}:missed`" @click="feedbackMissed(item.star, item.run_id)">记 missed</NButton>
          </div>
        </div>
        <div class="candidate-col">
          <div v-if="!item.candidates.length" class="rev-empty small">没有候选</div>
          <div v-for="candidate in item.candidates" :key="candidate.id" class="candidate-card">
            <div class="rev-meta">
              <NTag size="small">{{ candidate.chord || '无和弦' }}</NTag>
              <NTag size="small">score {{ candidate.score ?? 0 }}</NTag>
              <NTag v-if="candidate.is_constant" size="small" type="warning">恒星</NTag>
              <NTag size="small">{{ candidate.session_tag || 'default' }}</NTag>
            </div>
            <div class="star-content">{{ candidate.content }}</div>
            <div v-if="scoreParts(candidate)" class="score-line">{{ scoreParts(candidate) }}</div>
            <div class="rev-actions">
              <NButton size="tiny" type="primary" :loading="feedbackingKey === `${item.star.id}:${candidate.id}:connect`" @click="connectCandidate(item.star, candidate)">连线</NButton>
              <NButton size="tiny" :loading="feedbackingKey === `${item.star.id}:${candidate.id}:positive`" @click="feedbackCandidate(item.star, candidate, 'positive')">该反</NButton>
              <NButton size="tiny" :loading="feedbackingKey === `${item.star.id}:${candidate.id}:negative`" @click="feedbackCandidate(item.star, candidate, 'negative')">不该反</NButton>
              <NButton size="tiny" :loading="feedbackingKey === `${item.star.id}:${candidate.id}:skipped`" @click="feedbackCandidate(item.star, candidate, 'skipped')">跳过</NButton>
            </div>
          </div>
        </div>
      </div>
    </NCard>

    <NCard title="星星库" size="small" class="section-card">
      <div class="rev-toolbar">
        <NSelect v-model:value="starStatus" :options="statusOptions" style="width:120px" />
        <NSelect v-model:value="starReviewed" :options="reviewedOptions" style="width:130px" />
        <input v-model="starQuery" class="cal-input" placeholder="搜索内容/和弦">
        <input v-model="starSessionTag" class="cal-input short" placeholder="session_tag">
        <input v-model="starLimit" class="cal-input tiny" type="number" min="1" max="200">
        <NButton size="small" :loading="loadingStars" @click="loadStars">刷新</NButton>
        <NButton size="small" :disabled="selectedStarIds.length < 2" @click="connectSelected">连所选</NButton>
        <NTag v-if="selectedStarIds.length" size="small">已选 {{ selectedStarIds.length }}</NTag>
      </div>
      <div v-if="selectedStars.length" class="selected-line">
        {{ selectedStars.map((item) => item.chord || item.content.slice(0, 12)).join(' / ') }}
      </div>
      <div v-if="!stars.length" class="rev-empty">当前筛选没有星星</div>
      <div v-for="star in stars" :key="star.id" class="star-row">
        <NCheckbox :checked="selectedStarIds.includes(star.id)" @update:checked="(checked) => toggleSelected(star.id, checked)" />
        <div class="star-main">
          <div class="rev-meta">
            <NTag size="small" :type="statusTagType(star.status)">{{ star.status }}</NTag>
            <NTag size="small">{{ star.chord || '无和弦' }}</NTag>
            <NTag size="small">{{ star.session_tag || 'default' }}</NTag>
            <NTag v-if="star.is_constant" size="small" type="warning">恒星</NTag>
            <NTag size="small">亮 {{ star.activation_count || 0 }}</NTag>
            <NTag size="small">review {{ formatTime(star.reviewed_at) }}</NTag>
          </div>
          <div class="star-content">{{ star.content }}</div>
          <div class="score-line">id {{ star.id }} · updated {{ formatTime(star.updated_at) }}</div>
        </div>
        <NButton size="tiny" @click="toggleConstant(star)">{{ star.is_constant ? '取消恒星' : '设恒星' }}</NButton>
      </div>
    </NCard>
  </div>
</template>

<style scoped>
.stars-page {
  margin: 0 auto;
  max-width: 1260px;
}

.section-card {
  margin-top: 12px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 12px;
}

.cfg-inline {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.cfg-inline.two {
  grid-template-columns: 1fr 1fr;
}

.cfg-inline.four {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.cfg-inline.five {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.cfg-help {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.cal-input {
  min-height: 34px;
  min-width: 180px;
  padding: 6px 10px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #fff;
}

.cal-input.short {
  min-width: 130px;
}

.cal-input.tiny {
  min-width: 80px;
  width: 90px;
}

.cal-input.wide {
  flex: 1;
  min-width: 260px;
}

.rev-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.rev-empty {
  padding: 18px 0;
  text-align: center;
  color: #6b7280;
  font-size: 12px;
}

.rev-empty.small {
  padding: 8px 0;
}

.mini-row,
.candidate-card,
.star-row,
.review-block {
  margin-top: 10px;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.review-block {
  display: grid;
  grid-template-columns: minmax(240px, 0.8fr) minmax(0, 1.2fr);
  gap: 12px;
  background: #fdfafa;
}

.star-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.rev-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 8px;
}

.star-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.star-content.seed {
  font-weight: 600;
}

.score-line,
.selected-line {
  margin-top: 6px;
  color: #64748b;
  font-size: 12px;
  word-break: break-word;
}

.missed-row,
.rev-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
  align-items: center;
}

@media (max-width: 980px) {
  .workspace-grid,
  .review-block,
  .cfg-inline,
  .cfg-inline.two,
  .cfg-inline.four,
  .cfg-inline.five {
    grid-template-columns: 1fr;
  }

  .cal-input {
    width: 100%;
  }

  .star-row {
    grid-template-columns: auto minmax(0, 1fr);
  }
}
</style>
