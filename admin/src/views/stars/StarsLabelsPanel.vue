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
  { key: 'deep', label: '深', color: '#8e83d9', glow: 'rgba(142, 131, 217, .24)' },
  { key: 'daily', label: '日常', color: '#8fc7b5', glow: 'rgba(143, 199, 181, .22)' },
  { key: 'rift', label: '裂', color: '#d86d86', glow: 'rgba(216, 109, 134, .24)' },
  { key: 'create', label: '造', color: '#66bcd2', glow: 'rgba(102, 188, 210, .22)' },
  { key: 'anchor', label: '锚', color: '#d8b66d', glow: 'rgba(216, 182, 109, .24)' },
] as const

const message = useMessage()
const stars = ref<StarItem[]>([])
const loading = ref(false)
const labeling = ref(false)
const batchSize = ref(10)
const confirmedBatchSize = ref<number | null>(null)
const savingId = ref('')
const filter = ref('all')
const lastResult = ref<Awaited<ReturnType<typeof backfillStarScenes>> | null>(null)

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
    lastResult.value = result
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

    <div v-if="lastResult" class="run-result" :class="{ failed: lastResult.failed }">
      <div class="run-summary">
        <div><span class="result-kicker">本批结果</span><strong v-if="lastResult.failed">有星星暂未写入</strong><strong v-else>这一批都写好了</strong></div>
        <span>选中 {{ lastResult.selected }} · 写入 {{ lastResult.updated }} · 失败 {{ lastResult.failed }}</span>
      </div>
      <details v-if="lastResult.thinking" class="thinking-box">
        <summary>查看这次分类的 Thinking</summary>
        <pre>{{ lastResult.thinking }}</pre>
      </details>
      <div class="batch-results">
        <article v-for="item in lastResult.items" :key="item.star.id" class="batch-result-card" :class="{ failed: !item.ok }">
          <div class="result-star-copy">
            <span class="result-status">{{ item.ok ? '已写入' : '未写入' }}</span>
            <p>{{ item.star.content }}</p>
          </div>
          <div class="result-scenes" v-if="item.ok">
            <span v-if="item.scenes?.length === 0" class="no-scene">空标签</span>
            <span v-for="sceneKey in item.scenes" :key="sceneKey" class="result-chip" :style="chipStyle(sceneKey)">{{ sceneLabel(sceneKey) }}</span>
          </div>
          <span v-else class="result-failure">未写入</span>
        </article>
      </div>
      <div v-if="lastResult.failed" class="failure-list">
        <p>{{ lastResult.items.find((entry) => !entry.ok)?.error || '这批分类没有得到可写入的最终答案' }}</p>
        <code v-if="lastResult.items.find((entry) => !entry.ok)?.response_preview">模型原文：{{ lastResult.items.find((entry) => !entry.ok)?.response_preview }}</code>
      </div>
    </div>

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
.eyebrow { margin: 0 0 5px; color: #a08090; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; }
h3 { margin: 0; color: #4a3535; font-family: 'Cormorant Garamond', 'Georgia', serif; font-size: 24px; font-weight: 500; }
.labels-intro p:last-child { margin: 6px 0 0; color: #9a858d; font-size: 12px; }
.batch-console { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 17px; border: 1px solid #ead4cf; border-radius: 12px; background: linear-gradient(135deg, #fff, #fdf7f8); box-shadow: 0 7px 22px rgba(111,76,88,.045); }
.batch-box { display: flex; align-items: center; gap: 9px; flex: 0 0 auto; color: #846d77; font-size: 13px; }
.batch-box :deep(.n-input-number) { width: 82px; }
.console-label { color: #5e4750; font-weight: 600; }.console-note { color: #ad969e; font-size: 11px; }
.scene-mirror { display: flex; gap: 8px; flex-wrap: wrap; }
.scene-mirror button, .scene-picker button { border: 1px solid #ead4cf; color: #846d77; background: rgba(255,255,255,.82); cursor: pointer; transition: .2s ease; }
.scene-mirror button { display: inline-flex; align-items: center; gap: 7px; padding: 8px 11px; border-radius: 999px; }
.scene-mirror button:hover, .scene-mirror button.active { color: #4f4052; border-color: var(--scene, #c89aa8); background: var(--glow, #f8eef2); transform: translateY(-1px); }
.scene-mirror i, .scene-picker i { width: 7px; height: 7px; border-radius: 50%; background: var(--scene, #d8b66d); box-shadow: 0 0 12px var(--scene, #d8b66d); }
.scene-mirror b { color: #6b555b; font-size: 11px; font-variant-numeric: tabular-nums; }
.all-dot { background: #b88999 !important; }.empty-dot { background: #b9aeb2 !important; box-shadow: none !important; }
.run-result { padding: 18px; border: 1px solid #e7d8d5; border-radius: 14px; background: #fffdfc; color: #5f4b53; box-shadow: 0 12px 30px rgba(111,76,88,.055); }
.run-result.failed { border-color: #efcbc8; }
.run-summary { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; font-size: 12px; color: #9a858d; }.run-summary strong { display: block; margin-top: 3px; color: #523e46; font-size: 16px; }.result-kicker { color: #ad8795; font-size: 10px; letter-spacing: .13em; text-transform: uppercase; }
.batch-results { display: grid; gap: 8px; margin-top: 14px; }
.batch-result-card { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 16px; padding: 12px 13px; border: 1px solid #f0e2df; border-radius: 11px; background: #fff; }.batch-result-card.failed { background: #fff8f7; }.result-star-copy p { margin: 4px 0 0; color: #604d54; font-size: 12px; line-height: 1.55; }.result-status { color: #a89099; font-size: 10px; }.result-scenes { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }.result-chip { padding: 5px 9px; border: 1px solid var(--scene); border-radius: 999px; background: var(--glow); color: #59464e; font-size: 12px; }.no-scene, .result-failure { color: #aa9199; font-size: 11px; }.result-failure { color: #b66f78; }
.failure-list { margin-top: 10px; padding: 10px 12px; border-radius: 9px; background: #fff3f2; }.failure-list p { margin: 0; color: #855f65; font-size: 12px; }.failure-list code { display: block; margin-top: 5px; color: #9a7076; white-space: normal; word-break: break-word; }
.thinking-box { margin-top: 12px; border: 1px solid #eee2df; border-radius: 10px; background: #faf6f5; }.thinking-box summary { padding: 10px 12px; cursor: pointer; color: #876f79; font-size: 12px; }.thinking-box pre { max-height: 360px; overflow: auto; margin: 0; padding: 0 12px 12px; color: #705d65; font: 12px/1.7 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; word-break: break-word; }
.star-label-list { display: grid; gap: 10px; }
.star-label-card { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 22px; align-items: center; padding: 17px 19px; border: 1px solid #f0dfdc; border-radius: 13px; background: rgba(255,255,255,.76); transition: .2s ease; }
.star-label-card:hover { border-color: #ddbfc4; box-shadow: 0 8px 22px rgba(111,76,88,.06); transform: translateY(-1px); }
.star-copy p { margin: 5px 0 0; color: #5e4a51; line-height: 1.65; white-space: pre-wrap; }
.star-meta { display: flex; gap: 9px; color: #aa929a; font-size: 11px; }
.chord { color: #b78755; }
.scene-picker { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; max-width: 280px; }
.scene-picker.saving { opacity: .55; pointer-events: none; }
.scene-picker button { display: inline-flex; align-items: center; gap: 5px; padding: 6px 9px; border-radius: 9px; font-size: 12px; }
.scene-picker button.selected { color: #4f4052; border-color: var(--scene); background: var(--glow); box-shadow: inset 0 0 18px var(--glow); }
.empty-state { padding: 48px 20px; border: 1px dashed #ead4cf; border-radius: 14px; color: #a0868f; text-align: center; }
@media (max-width: 760px) { .batch-console { align-items: flex-start; flex-direction: column; }.batch-box { flex-wrap: wrap; }.batch-result-card, .star-label-card { grid-template-columns: 1fr; }.result-scenes, .scene-picker { justify-content: flex-start; max-width: none; } }
</style>
