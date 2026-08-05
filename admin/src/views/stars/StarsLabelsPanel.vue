<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, NInputNumber, useMessage } from 'naive-ui'
import {
  backfillStarScenes,
  fetchStars,
  setStarScenes,
  type StarItem,
} from '@/api/stars'

const SCENES = [
  { key: 'warm', label: '暖', color: '#f6a88d', glow: 'rgba(246, 168, 141, .24)' },
  { key: 'want', label: '欲/馋', color: '#bf5d78', glow: 'rgba(191, 93, 120, .22)' },
  { key: 'seen', label: '被看穿', color: '#5f9f9a', glow: 'rgba(95, 159, 154, .22)' },
  { key: 'loose', label: '漏', color: '#9b86b4', glow: 'rgba(155, 134, 180, .22)' },
  { key: 'deep', label: '深', color: '#8e83d9', glow: 'rgba(142, 131, 217, .24)' },
  { key: 'daily', label: '日常', color: '#8fc7b5', glow: 'rgba(143, 199, 181, .22)' },
  { key: 'rift', label: '裂', color: '#d86d86', glow: 'rgba(216, 109, 134, .24)' },
  { key: 'create', label: '造', color: '#66bcd2', glow: 'rgba(102, 188, 210, .22)' },
  { key: 'anchor', label: '锚', color: '#d8b66d', glow: 'rgba(216, 182, 109, .24)' },
] as const

const BATCH_HISTORY_KEY = 'star-scene-batch-history-v1'
const BATCH_HISTORY_LIMIT = 3

interface BatchHistoryItem {
  starId: string
  assignedScenes: string[]
  ok: boolean
  star?: StarItem
  skipped?: boolean
  error?: string
  responsePreview?: string
}

interface BatchHistoryRun {
  id: string
  createdAt: string
  selected: number
  updated: number
  failed: number
  thinking?: string
  items: BatchHistoryItem[]
}

const message = useMessage()
const stars = ref<StarItem[]>([])
const loading = ref(false)
const labeling = ref(false)
const batchSize = ref(10)
const confirmedBatchSize = ref<number | null>(null)
const savingId = ref('')
const filter = ref('all')
const batchHistory = ref<BatchHistoryRun[]>([])

const counts = computed(() => {
  const result: Record<string, number> = { all: stars.value.length, unlabeled: 0 }
  for (const scene of SCENES) result[scene.key] = 0
  for (const star of stars.value) {
    const scenes = Array.isArray(star.scenes) ? star.scenes : []
    if (!scenes.length) result.unlabeled += 1
    for (const scene of scenes) result[scene] = (result[scene] || 0) + 1
  }
  return result
})

const visibleStars = computed(() => {
  if (filter.value === 'all') return stars.value
  if (filter.value === 'unlabeled') return stars.value.filter((star) => !(star.scenes || []).length)
  return stars.value.filter((star) => (star.scenes || []).includes(filter.value))
})

onMounted(() => {
  const saved = Number(window.localStorage.getItem('star-scene-batch-size') || 10)
  batchSize.value = Number.isFinite(saved) ? Math.min(100, Math.max(1, saved)) : 10
  loadBatchHistory()
  loadStars()
})

const batchConfirmed = computed(() => confirmedBatchSize.value !== null && confirmedBatchSize.value === batchSize.value)

function confirmBatch() {
  confirmedBatchSize.value = batchSize.value || 10
  window.localStorage.setItem('star-scene-batch-size', String(confirmedBatchSize.value))
  message.success(`本批固定为 ${confirmedBatchSize.value} 颗`)
}

function sceneLabel(key: string) {
  return SCENES.find((scene) => scene.key === key)?.label || key
}

function chipStyle(key: string) {
  const scene = SCENES.find((item) => item.key === key)
  return scene ? { '--scene': scene.color, '--glow': scene.glow } : {}
}

function loadBatchHistory() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(BATCH_HISTORY_KEY) || '[]') as BatchHistoryRun[]
    if (!Array.isArray(parsed)) return
    batchHistory.value = parsed
      .filter((run) => run && typeof run.id === 'string' && Array.isArray(run.items))
      .map((run) => ({
        ...run,
        items: run.items.filter((item) => item && typeof item.starId === 'string' && Array.isArray(item.assignedScenes)),
      }))
      .slice(0, BATCH_HISTORY_LIMIT)
  } catch {
    window.localStorage.removeItem(BATCH_HISTORY_KEY)
  }
}

function persistBatchHistory() {
  const stored = batchHistory.value.map((run) => ({
    id: run.id,
    createdAt: run.createdAt,
    selected: run.selected,
    updated: run.updated,
    failed: run.failed,
    items: run.items.map((item) => ({
      starId: item.starId,
      assignedScenes: item.assignedScenes,
      ok: item.ok,
      skipped: item.skipped,
    })),
  }))
  window.localStorage.setItem(BATCH_HISTORY_KEY, JSON.stringify(stored))
}

function rememberBatch(result: Awaited<ReturnType<typeof backfillStarScenes>>) {
  if (!result.selected) return
  const createdAt = new Date().toISOString()
  const run: BatchHistoryRun = {
    id: `${createdAt}-${Date.now().toString(36)}`,
    createdAt,
    selected: result.selected,
    updated: result.updated,
    failed: result.failed,
    thinking: result.thinking,
    items: result.items.map((item) => ({
      starId: item.star.id,
      assignedScenes: Array.isArray(item.scenes) ? item.scenes : (item.star.scenes || []),
      ok: item.ok,
      star: {
        ...item.star,
        scenes: Array.isArray(item.scenes) ? item.scenes : (item.star.scenes || []),
      },
      skipped: item.skipped,
      error: item.error,
      responsePreview: item.response_preview,
    })),
  }
  batchHistory.value = [run, ...batchHistory.value].slice(0, BATCH_HISTORY_LIMIT)
  persistBatchHistory()
}

function formatBatchTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '最近一次'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function historyStar(item: BatchHistoryItem) {
  return stars.value.find((star) => star.id === item.starId) || item.star
}

function historyScenes(item: BatchHistoryItem) {
  return historyStar(item)?.scenes || item.assignedScenes
}

function historyItemAdjusted(item: BatchHistoryItem) {
  const star = historyStar(item)
  if (!star) return false
  const current = new Set(star.scenes || [])
  const assigned = new Set(item.assignedScenes)
  return current.size !== assigned.size || [...current].some((scene) => !assigned.has(scene))
}

async function toggleHistoryScene(item: BatchHistoryItem, scene: string) {
  const star = historyStar(item)
  if (!star) {
    message.info('这颗星不在当前列表，暂时不能调整')
    return
  }
  await toggleScene(star, scene)
}

async function loadStars() {
  loading.value = true
  try {
    const result = await fetchStars({ status: 'active', limit: 250 })
    stars.value = result.items || []
  } catch {
    message.error('读取星星标签失败')
  } finally {
    loading.value = false
  }
}

async function runBackfill() {
  if (!batchConfirmed.value) {
    message.info('先点“确定本批数量”')
    return
  }
  labeling.value = true
  try {
    const result = await backfillStarScenes(confirmedBatchSize.value || 10)
    rememberBatch(result)
    await loadStars()
    if (result.failed) {
      message.warning(`本批写入 ${result.updated} 颗，${result.failed} 颗未写入`)
    } else if (!result.selected) {
      message.info('目前没有等待补标签的星星')
    } else {
      message.success(`已为 ${result.updated} 颗星星补好场景`)
    }
  } catch {
    message.error('批量补标签失败，请检查模型配置')
  } finally {
    labeling.value = false
  }
}

async function toggleScene(star: StarItem, scene: string) {
  if (savingId.value) return
  const current = Array.isArray(star.scenes) ? star.scenes : []
  const next = current.includes(scene)
    ? current.filter((item) => item !== scene)
    : [...current, scene]
  savingId.value = star.id
  try {
    const result = await setStarScenes(star.id, next)
    const index = stars.value.findIndex((item) => item.id === star.id)
    if (index >= 0) stars.value[index] = result.star
    else Object.assign(star, result.star)
  } catch {
    message.error('保存场景标签失败')
  } finally {
    savingId.value = ''
  }
}
</script>

<template>
  <section class="labels-panel">
    <div class="labels-intro">
      <div>
        <p class="eyebrow">Scene Labels</p>
        <h3>给屯下来的星星补一层光</h3>
        <p>你决定一次处理多少颗；模型只选择场景，不碰正文。</p>
      </div>
    </div>
    <div class="batch-console">
      <div class="batch-box">
        <span class="console-label">本批数量</span>
        <NInputNumber v-model:value="batchSize" :min="1" :max="100" size="small" />
        <span>颗</span>
        <NButton size="small" :type="batchConfirmed ? 'default' : 'primary'" @click="confirmBatch">
          {{ batchConfirmed ? `已确定 ${confirmedBatchSize} 颗` : '确定本批数量' }}
        </NButton>
        <NButton type="primary" size="small" :disabled="!batchConfirmed" :loading="labeling" @click="runBackfill">开始补标签</NButton>
      </div>
      <span class="console-note">改数字后需要重新确定；本批结果会显示在下面。</span>
    </div>

    <div class="scene-mirror">
      <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
        <i class="all-dot" />全部 <b>{{ counts.all }}</b>
      </button>
      <button
        v-for="scene in SCENES"
        :key="scene.key"
        :class="{ active: filter === scene.key }"
        :style="{ '--scene': scene.color, '--glow': scene.glow }"
        @click="filter = scene.key"
      >
        <i />{{ scene.label }} <b>{{ counts[scene.key] }}</b>
      </button>
      <button :class="{ active: filter === 'unlabeled' }" @click="filter = 'unlabeled'">
        <i class="empty-dot" />未标 <b>{{ counts.unlabeled }}</b>
      </button>
    </div>

    <section v-if="batchHistory.length && !loading" class="batch-history" data-testid="stars-label-history">
      <div class="history-heading">
        <div>
          <p class="eyebrow">Recent Runs</p>
          <h4>最近 3 次补标签</h4>
        </div>
        <span>{{ batchHistory.length }} 次</span>
      </div>
      <details
        v-for="(run, runIndex) in batchHistory"
        :key="run.id"
        class="batch-run"
        :class="{ failed: run.failed }"
        :open="runIndex === 0"
        data-testid="stars-label-history-run"
      >
        <summary>
          <div>
            <span class="result-kicker">{{ runIndex === 0 ? '最新一次' : '历史批次' }}</span>
            <strong>{{ formatBatchTime(run.createdAt) }}</strong>
          </div>
          <span>选中 {{ run.selected }} · 写入 {{ run.updated }} · 失败 {{ run.failed }}</span>
        </summary>
        <details v-if="run.thinking" class="thinking-box">
          <summary>查看这次分类的 Thinking</summary>
          <pre>{{ run.thinking }}</pre>
        </details>
        <div class="batch-results">
          <article
            v-for="item in run.items"
            :key="item.starId"
            class="batch-result-card"
            :class="{ failed: !item.ok }"
            :data-testid="`stars-label-history-item-${item.starId}`"
          >
            <div class="result-star-copy">
              <span class="result-status">
                {{ !item.ok ? '未写入' : item.skipped ? '已跳过' : historyItemAdjusted(item) ? '已手动调整' : '已写入' }}
              </span>
              <p>{{ historyStar(item)?.content || '这颗星不在当前列表' }}</p>
              <div v-if="!item.ok" class="result-failure">
                <span>{{ item.error || '这批分类没有得到可写入的最终答案' }}</span>
                <code v-if="item.responsePreview">模型原文：{{ item.responsePreview }}</code>
              </div>
            </div>
            <div v-if="item.ok" class="result-scene-editor">
              <div class="model-scenes">
                <span>模型原判</span>
                <em v-if="!item.assignedScenes.length">空标签</em>
                <i
                  v-for="sceneKey in item.assignedScenes"
                  :key="sceneKey"
                  :style="chipStyle(sceneKey)"
                >{{ sceneLabel(sceneKey) }}</i>
              </div>
              <div class="adjust-heading">
                <span>当前标签</span>
                <b v-if="historyItemAdjusted(item)">已调整</b>
              </div>
              <div class="scene-picker result-picker" :class="{ saving: savingId === item.starId }">
                <button
                  v-for="scene in SCENES"
                  :key="scene.key"
                  :class="{ selected: historyScenes(item).includes(scene.key) }"
                  :style="{ '--scene': scene.color, '--glow': scene.glow }"
                  :disabled="!historyStar(item)"
                  :data-testid="`stars-label-history-toggle-${item.starId}-${scene.key}`"
                  @click="toggleHistoryScene(item, scene.key)"
                >
                  <i />{{ scene.label }}
                </button>
              </div>
            </div>
          </article>
        </div>
      </details>
    </section>

    <div v-if="loading" class="empty-state">正在数星星……</div>
    <div v-else-if="!visibleStars.length" class="empty-state">这一栏暂时没有星星。</div>
    <div v-else class="star-label-list">
      <article v-for="star in visibleStars" :key="star.id" class="star-label-card">
        <div class="star-copy">
          <div class="star-meta">
            <span v-if="star.chord" class="chord">{{ star.chord }}</span>
            <span>{{ star.session_tag || 'default' }}</span>
          </div>
          <p>{{ star.content }}</p>
        </div>
        <div class="scene-picker" :class="{ saving: savingId === star.id }">
          <button
            v-for="scene in SCENES"
            :key="scene.key"
            :class="{ selected: (star.scenes || []).includes(scene.key) }"
            :style="{ '--scene': scene.color, '--glow': scene.glow }"
            @click="toggleScene(star, scene.key)"
          >
            <i />{{ scene.label }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.labels-panel { display: grid; gap: 18px; }
.labels-intro { padding: 6px 4px 2px; }
.eyebrow { margin: 0 0 5px; color: var(--sy-mute); font-size: 11px; letter-spacing: .16em; text-transform: uppercase; }
h3 { margin: 0; color: var(--sy-ink); font-family: 'Cormorant Garamond', 'Georgia', serif; font-size: 24px; font-weight: 500; }
.labels-intro p:last-child { margin: 6px 0 0; color: #9a858d; font-size: 12px; }
.batch-console { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 17px; border: 1px solid var(--sy-hair-2); border-radius: 12px; background: linear-gradient(135deg, #fff, #fdf7f8); box-shadow: 0 7px 22px rgba(111,76,88,.045); }
.batch-box { display: flex; align-items: center; gap: 9px; flex: 0 0 auto; color: #846d77; font-size: 13px; }
.batch-box :deep(.n-input-number) { width: 82px; }
.console-label { color: #5e4750; font-weight: 600; }.console-note { color: #ad969e; font-size: 11px; }
.scene-mirror { display: flex; gap: 8px; flex-wrap: wrap; }
.scene-mirror button, .scene-picker button { border: 1px solid var(--sy-hair-2); color: #846d77; background: rgba(255,255,255,.82); cursor: pointer; transition: .2s ease; }
.scene-mirror button { display: inline-flex; align-items: center; gap: 7px; padding: 8px 11px; border-radius: 999px; }
.scene-mirror button:hover, .scene-mirror button.active { color: var(--sy-ink); border-color: var(--scene, #c89aa8); background: var(--glow, #f8eef2); transform: translateY(-1px); }
.scene-mirror i, .scene-picker i { width: 7px; height: 7px; border-radius: 50%; background: var(--scene, #d8b66d); box-shadow: 0 0 12px var(--scene, #d8b66d); }
.scene-mirror b { color: #6b555b; font-size: 11px; font-variant-numeric: tabular-nums; }
.all-dot { background: #b88999 !important; }.empty-dot { background: #b9aeb2 !important; box-shadow: none !important; }
.batch-history { display: grid; gap: 0; padding-top: 4px; border-top: 1px solid #eadad7; color: #5f4b53; }
.history-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding: 12px 4px 10px; }
.history-heading h4 { margin: 0; color: #4a353d; font-size: 17px; font-weight: 600; }
.history-heading > span { color: #a58d96; font-size: 11px; }
.batch-run { border-bottom: 1px solid #eadfdd; }
.batch-run > summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 58px; padding: 10px 4px; color: #9a858d; cursor: pointer; font-size: 12px; list-style-position: inside; }
.batch-run > summary:hover { color: #705963; }
.batch-run > summary strong { display: inline-block; margin-left: 8px; color: #523e46; font-size: 15px; }
.batch-run.failed > summary strong { color: #a65f6d; }
.result-kicker { color: #ad8795; font-size: 10px; letter-spacing: .13em; text-transform: uppercase; }
.batch-results { display: grid; gap: 8px; margin: 0 0 16px; }
.batch-result-card { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 430px); align-items: center; gap: 20px; padding: 14px; border: 1px solid #f0e2df; border-radius: 8px; background: var(--sy-paper, #fff); }
.batch-result-card.failed { grid-template-columns: 1fr; background: #fff8f7; }
.result-star-copy p { margin: 4px 0 0; color: #604d54; font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
.result-status { color: #a89099; font-size: 10px; }
.result-failure { display: grid; gap: 4px; margin-top: 8px; color: #b66f78; font-size: 11px; }
.result-failure code { color: #9a7076; white-space: normal; word-break: break-word; }
.result-scene-editor { display: grid; gap: 7px; justify-items: end; }
.model-scenes { display: flex; align-items: center; justify-content: flex-end; gap: 5px; min-height: 22px; color: #a58d96; font-size: 10px; }
.model-scenes i { padding: 3px 6px; border: 1px solid var(--scene); border-radius: 999px; background: var(--glow); color: #6b565e; font-style: normal; }
.model-scenes em { color: #aa9199; font-style: normal; }
.adjust-heading { display: flex; justify-content: space-between; width: 100%; color: #8c737d; font-size: 10px; }
.adjust-heading b { color: #5f8d88; font-weight: 600; }
.result-picker { max-width: 430px; }
.thinking-box { margin-top: 12px; border: 1px solid #eee2df; border-radius: 10px; background: #faf6f5; }.thinking-box summary { padding: 10px 12px; cursor: pointer; color: #876f79; font-size: 12px; }.thinking-box pre { max-height: 360px; overflow: auto; margin: 0; padding: 0 12px 12px; color: #705d65; font: 12px/1.7 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; word-break: break-word; }
.star-label-list { display: grid; gap: 10px; }
.star-label-card { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 22px; align-items: center; padding: 17px 19px; border: 1px solid #f0dfdc; border-radius: 13px; background: rgba(255,255,255,.76); transition: .2s ease; }
.star-label-card:hover { border-color: #ddbfc4; box-shadow: 0 8px 22px rgba(111,76,88,.06); transform: translateY(-1px); }
.star-copy p { margin: 5px 0 0; color: #5e4a51; line-height: 1.65; white-space: pre-wrap; }
.star-meta { display: flex; gap: 9px; color: #aa929a; font-size: 11px; }
.chord { color: #b78755; }
.scene-picker { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; max-width: 280px; }
.scene-picker.saving { opacity: .55; pointer-events: none; }
.scene-picker button { display: inline-flex; align-items: center; gap: 5px; min-height: 30px; padding: 6px 9px; border-radius: 8px; font-size: 12px; }
.scene-picker button.selected { color: var(--sy-ink); border-color: var(--scene); background: var(--glow); box-shadow: inset 0 0 18px var(--glow); }
.scene-picker button:disabled { cursor: not-allowed; opacity: .48; }
.empty-state { padding: 48px 20px; border: 1px dashed var(--sy-hair-2); border-radius: 14px; color: #a0868f; text-align: center; }
@media (max-width: 760px) { .batch-console { align-items: flex-start; flex-direction: column; }.batch-box { flex-wrap: wrap; }.batch-run > summary { align-items: flex-start; flex-direction: column; gap: 4px; }.batch-result-card, .star-label-card { grid-template-columns: 1fr; }.result-scene-editor { justify-items: start; }.model-scenes, .scene-picker { justify-content: flex-start; max-width: none; }.adjust-heading { max-width: none; } }
</style>
