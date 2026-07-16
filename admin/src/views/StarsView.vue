<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, useMessage } from 'naive-ui'
import { fetchConfig, saveConfig, type GatewayConfig } from '@/api/config'
import {
  connectStars,
  createStar,
  reviewStars,
  searchStars,
  sendStarFeedback,
  type StarCandidate,
  type StarItem,
  type StarReviewItem,
} from '@/api/stars'
import StarsListPanel from '@/views/stars/StarsListPanel.vue'
import StarsLabelsPanel from '@/views/stars/StarsLabelsPanel.vue'
import StarsReviewPanel from '@/views/stars/StarsReviewPanel.vue'
import StarsSettingsPanel from '@/views/stars/StarsSettingsPanel.vue'
import StarsWritePanel from '@/views/stars/StarsWritePanel.vue'
import { feedbackLabel } from '@/views/stars/starUi'

const StarMapView = defineAsyncComponent(() => import('@/views/stars/StarMapView.vue'))

const message = useMessage()
const route = useRoute()
const router = useRouter()

const STAR_DEFAULTS: Partial<GatewayConfig> = {
  inject_star_prompt: true,
  enable_inline_star_capture: true,
  inject_stars: true,
  enable_gateway_tools: true,
  enable_star_embeddings: false,
  star_inject_limit: 3,
  star_review_new_limit: 4,
  star_review_candidates_per_star: 2,
  star_review_total_candidate_limit: 8,
  star_chat_explicit_fallback_limit: 1,
  star_candidate_limit: 500,
  star_shadow_candidate_limit: 20,
  star_min_score: 0.18,
  star_related_min_score: 0.22,
  star_recent_fatigue_hours: 6,
  star_recent_fatigue_penalty: 0.14,
  star_soft_direct_cooldown_turns: 8,
  star_weight_content: 0.3,
  star_weight_keyword: 0.2,
  star_weight_harmony: 0.35,
  star_weight_chord: 0.18,
  star_weight_actr: 0.08,
  star_constant_bonus: 0.08,
  star_novelty_bonus: 0.04,
  star_ignored_penalty: 0.18,
}

type WorkMode = 'score' | 'labels' | 'settings' | 'write' | 'list'
type FeedbackCandidatePayload = {
  seed: StarItem
  candidate: StarCandidate
  feedback: 'positive' | 'negative' | 'skipped'
}

const config = ref<Partial<GatewayConfig>>({ ...STAR_DEFAULTS })
const savingConfig = ref(false)
const mode = ref<WorkMode>('score')

const reviewItems = ref<StarReviewItem[]>([])
const reviewSessionTag = ref('')
const reviewing = ref(false)
const feedbackingKey = ref('')
const connectName = ref('')
const connectNote = ref('')

const searchQuery = ref('')
const searchResults = ref<StarCandidate[]>([])
const searching = ref(false)

const createContent = ref('')
const createChord = ref('')
const createSessionTag = ref('')
const createConstant = ref(false)
const creating = ref(false)
const mapInitialStarId = ref('')

const isMapRoute = computed(() => route.path === '/stars/map')
const unscoredCount = computed(() => reviewItems.value.reduce((total, item) => total + item.candidates.length, 0))

onMounted(loadConfig)

function splitChordSequence(value: string): string[] {
  const text = value.trim()
  if (!text) return []
  const normalized = text
    .replace(/→|⇒|->|=>|｜|•|·|；|;|，|,/g, '|')
    .replace(/\s+\/\s+/g, '|')
  const parts = normalized.split('|').map((part) => part.trim()).filter(Boolean)
  return parts.length > 1 ? parts : []
}

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
    const settingsPatch: Partial<GatewayConfig> = {
      inject_star_prompt: config.value.inject_star_prompt,
      enable_inline_star_capture: config.value.enable_inline_star_capture,
      inject_stars: config.value.inject_stars,
      enable_gateway_tools: config.value.enable_gateway_tools,
      enable_star_embeddings: config.value.enable_star_embeddings,
      star_inject_limit: config.value.star_inject_limit,
      star_review_new_limit: config.value.star_review_new_limit,
      star_review_candidates_per_star: config.value.star_review_candidates_per_star,
      star_review_total_candidate_limit: config.value.star_review_total_candidate_limit,
      star_chat_explicit_fallback_limit: config.value.star_chat_explicit_fallback_limit,
      star_candidate_limit: config.value.star_candidate_limit,
      star_shadow_candidate_limit: config.value.star_shadow_candidate_limit,
      star_min_score: config.value.star_min_score,
      star_related_min_score: config.value.star_related_min_score,
      star_recent_fatigue_hours: config.value.star_recent_fatigue_hours,
      star_recent_fatigue_penalty: config.value.star_recent_fatigue_penalty,
      star_soft_direct_cooldown_turns: config.value.star_soft_direct_cooldown_turns,
      star_weight_content: config.value.star_weight_content,
      star_weight_keyword: config.value.star_weight_keyword,
      star_weight_harmony: config.value.star_weight_harmony,
      star_weight_chord: config.value.star_weight_chord,
      star_weight_actr: config.value.star_weight_actr,
      star_constant_bonus: config.value.star_constant_bonus,
      star_novelty_bonus: config.value.star_novelty_bonus,
      star_ignored_penalty: config.value.star_ignored_penalty,
      star_scene_llm_model: config.value.star_scene_llm_model,
      star_scene_llm_url: config.value.star_scene_llm_url,
      star_scene_llm_protocol: config.value.star_scene_llm_protocol,
    }
    if (config.value.star_scene_llm_api_key?.trim()) {
      settingsPatch.star_scene_llm_api_key = config.value.star_scene_llm_api_key.trim()
    }
    const result = await saveConfig(settingsPatch)
    config.value = { ...config.value, ...result.config }
    message.success('Star 设置已保存')
  } catch {
    message.error('保存 Star 设置失败')
  } finally {
    savingConfig.value = false
  }
}

function setStarQuietTools() {
  config.value.inject_star_prompt = false
  config.value.enable_inline_star_capture = false
  config.value.inject_stars = false
  config.value.enable_gateway_tools = true
  message.info('已切到静音星星模式，保存后生效')
}

function resetStarDefaults() {
  config.value = { ...config.value, ...STAR_DEFAULTS }
  message.info('已恢复 Star 默认值，保存后生效')
}

async function runReview() {
  reviewing.value = true
  try {
    const result = await reviewStars({
      limit_new: config.value.star_review_new_limit || 4,
      candidates_per_star: config.value.star_review_candidates_per_star || 2,
      total_candidate_limit: config.value.star_review_total_candidate_limit || 8,
      session_tag: reviewSessionTag.value.trim() || undefined,
    })
    reviewItems.value = result.items || []
    message.success(`拿到 ${reviewItems.value.length} 颗新星`)
  } catch {
    message.error('Review 失败')
  } finally {
    reviewing.value = false
  }
}

async function addStar() {
  const content = createContent.value.trim()
  if (!content) return
  creating.value = true
  try {
    const chord = createChord.value.trim()
    const chords = splitChordSequence(chord)
    const result = await createStar({
      content,
      chord,
      chords: chords.length ? chords : undefined,
      session_tag: createSessionTag.value.trim() || undefined,
      status: 'active',
      is_constant: createConstant.value,
      metadata: { surface: 'admin:stars' },
    })
    createContent.value = ''
    createChord.value = ''
    createConstant.value = false
    if (result.star_id) mapInitialStarId.value = result.star_id
    message.success('星星已写入')
  } catch {
    message.error('写入星星失败')
  } finally {
    creating.value = false
  }
}

async function runSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const result = await searchStars({
      q,
      limit: 8,
      log_run: true,
    })
    searchResults.value = result.items || []
  } catch {
    message.error('搜索星星失败')
  } finally {
    searching.value = false
  }
}

async function feedbackCandidate(payload: FeedbackCandidatePayload) {
  const { seed, candidate, feedback } = payload
  const key = candidateKey(seed, candidate)
  feedbackingKey.value = `${key}:${feedback}`
  try {
    await sendStarFeedback({
      feedback,
      run_id: candidate.run_id,
      candidate_id: candidate.candidate_id,
      candidate_star_id: candidate.id,
      scored_by: '圆圆',
      metadata: { surface: 'admin:stars' },
    })
    removeCandidateFromReview(seed.id, candidate.id, candidate.candidate_id)
    message.success(feedbackLabel(feedback))
  } catch {
    message.error('反馈失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function feedbackMissed(payload: { seed: StarItem; runId?: string | null; expectedStarId: string }) {
  const { seed, runId, expectedStarId } = payload
  const key = `${seed.id}:missed`
  feedbackingKey.value = key
  try {
    await sendStarFeedback({
      feedback: 'missed',
      run_id: runId,
      expected_star_id: expectedStarId,
      scored_by: '圆圆',
      note: `Review ${seed.id} 时漏反`,
      metadata: { surface: 'admin:stars' },
    })
    clearSeedIfEmpty(seed.id)
    message.success('已记下漏反')
  } catch {
    message.error('记录漏反失败')
  } finally {
    feedbackingKey.value = ''
  }
}

async function connectCandidate(payload: { seed: StarItem; candidate: StarCandidate }) {
  const { seed, candidate } = payload
  const key = candidateKey(seed, candidate)
  feedbackingKey.value = `${key}:connected`
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
    removeCandidateFromReview(seed.id, candidate.id, candidate.candidate_id)
    mapInitialStarId.value = seed.id
    message.success('星座连上了')
  } catch {
    message.error('连线失败')
  } finally {
    feedbackingKey.value = ''
  }
}

function selectStar(starId: string) {
  mapInitialStarId.value = starId
  router.push('/stars/map')
}

function candidateKey(seed: StarItem, candidate: StarCandidate): string {
  return candidate.candidate_id || `${seed.id}:${candidate.id}`
}

function removeCandidateFromReview(seedId: string, candidateId: string, candidateRowId?: string | null) {
  reviewItems.value = reviewItems.value
    .map((item) => {
      if (item.star.id !== seedId) return item
      return {
        ...item,
        candidates: item.candidates.filter((candidate) => {
          if (candidateRowId && candidate.candidate_id === candidateRowId) return false
          return candidate.id !== candidateId
        }),
      }
    })
    .filter((item) => item.candidates.length > 0)
}

function clearSeedIfEmpty(seedId: string) {
  reviewItems.value = reviewItems.value.filter((item) => item.star.id !== seedId || item.candidates.length > 0)
}
</script>

<template>
  <div class="stars-page" data-testid="page-stars" :class="{ 'map-page': isMapRoute }">
    <StarMapView v-if="isMapRoute" :initial-star-id="mapInitialStarId" />

    <section v-else class="workbench">
      <div class="stars-head">
        <div>
          <div class="page-eyebrow">Star Memory</div>
          <h2>星星</h2>
        </div>
        <div class="head-actions">
          <NButton size="small" @click="router.push('/stars/map')">记忆星图</NButton>
          <NButton size="small" type="primary" :loading="reviewing" @click="runReview">拿一小批</NButton>
        </div>
      </div>

      <div class="mode-rail">
        <button type="button" :class="{ active: mode === 'score' }" @click="mode = 'score'">
          评分
          <span v-if="unscoredCount">{{ unscoredCount }}</span>
        </button>
        <button data-testid="stars-mode-labels" type="button" :class="{ active: mode === 'labels' }" @click="mode = 'labels'">标签</button>
        <button data-testid="stars-mode-settings" type="button" :class="{ active: mode === 'settings' }" @click="mode = 'settings'">配置</button>
        <button type="button" :class="{ active: mode === 'write' }" @click="mode = 'write'">写星</button>
        <button type="button" :class="{ active: mode === 'list' }" @click="mode = 'list'">星列</button>
      </div>

      <StarsReviewPanel
        v-if="mode === 'score'"
        v-model:session-tag="reviewSessionTag"
        v-model:connect-name="connectName"
        v-model:connect-note="connectNote"
        :items="reviewItems"
        :feedbacking-key="feedbackingKey"
        @feedback-candidate="feedbackCandidate"
        @feedback-missed="feedbackMissed"
        @connect-candidate="connectCandidate"
        @select-star="selectStar"
      />
      <StarsSettingsPanel
        v-else-if="mode === 'settings'"
        :config="config"
        :saving="savingConfig"
        @save="saveSettings"
        @quiet-tools="setStarQuietTools"
        @reset="resetStarDefaults"
      />
      <StarsLabelsPanel v-else-if="mode === 'labels'" />
      <StarsListPanel
        v-else-if="mode === 'list'"
        @select-star="selectStar"
      />
      <StarsWritePanel
        v-else
        v-model:content="createContent"
        v-model:chord="createChord"
        v-model:session-tag="createSessionTag"
        v-model:constant="createConstant"
        v-model:query="searchQuery"
        :results="searchResults"
        :creating="creating"
        :searching="searching"
        @create="addStar"
        @search="runSearch"
        @select-star="selectStar"
      />
    </section>
  </div>
</template>

<style scoped>
.stars-page {
  max-width: 1320px;
  margin: 0 auto;
}

.stars-page.map-page {
  max-width: min(1440px, calc(100vw - 24px));
}

.workbench {
  max-width: 980px;
  margin: 0 auto;
  border: 1px solid #f2ddd8;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  padding: 16px;
}

.stars-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid #f0e0dc;
  border-radius: 8px;
  background:
    radial-gradient(circle at 12% 18%, rgba(255, 224, 174, 0.26), transparent 34%),
    linear-gradient(135deg, #fffdfb 0%, #f8eef2 58%, #eff7f2 100%);
}

.page-eyebrow {
  color: #a08090;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.stars-head h2 {
  margin: 2px 0 3px;
  color: #4a3535;
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 34px;
  font-weight: 500;
  letter-spacing: 0;
}

.head-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.mode-rail {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.mode-rail button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid #ead4cf;
  border-radius: 999px;
  background: #fff;
  color: #846d77;
  cursor: pointer;
}

.mode-rail button.active {
  background: #4f4052;
  color: #fff7ee;
  border-color: #4f4052;
}

.mode-rail span {
  min-width: 18px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #f1c37a;
  color: #4f4052;
  font-size: 11px;
}

@media (max-width: 980px) {
  .stars-head {
    flex-direction: column;
  }

  .head-actions {
    justify-content: flex-start;
  }
}
</style>
