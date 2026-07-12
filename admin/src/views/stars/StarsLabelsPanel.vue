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
const savingId = ref('')
const filter = ref('all')

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

onMounted(loadStars)

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
  labeling.value = true
  try {
    const result = await backfillStarScenes(batchSize.value || 10)
    await loadStars()
    if (result.failed) {
      message.warning(`写入 ${result.updated} 颗，${result.failed} 颗分类失败，可稍后重试`)
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
    <div class="labels-hero">
      <div>
        <p class="eyebrow">Scene Labels</p>
        <h3>给屯下来的星星补一层光</h3>
        <p class="hero-copy">只处理还没标过的星。模型只选场景，不碰正文；已有标签永远跳过。</p>
      </div>
      <div class="batch-box">
        <span>这次捞</span>
        <NInputNumber v-model:value="batchSize" :min="1" :max="100" size="small" />
        <span>颗</span>
        <NButton type="primary" size="small" :loading="labeling" @click="runBackfill">帮我补标签</NButton>
      </div>
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
.labels-hero { display: flex; justify-content: space-between; gap: 24px; align-items: center; padding: 24px; border: 1px solid rgba(216,182,109,.2); border-radius: 22px; background: radial-gradient(circle at 12% 10%, rgba(216,182,109,.12), transparent 34%), linear-gradient(145deg, rgba(20,24,37,.96), rgba(12,15,25,.92)); box-shadow: 0 20px 50px rgba(3,6,14,.22); }
.eyebrow { margin: 0 0 5px; color: #d8b66d; font-size: 11px; letter-spacing: .18em; text-transform: uppercase; }
h3 { margin: 0; color: #f3eee3; font-size: 20px; font-weight: 600; }
.hero-copy { max-width: 610px; margin: 8px 0 0; color: #8e97aa; font-size: 13px; line-height: 1.7; }
.batch-box { display: flex; align-items: center; gap: 9px; flex: 0 0 auto; color: #aeb5c4; font-size: 13px; }
.batch-box :deep(.n-input-number) { width: 82px; }
.scene-mirror { display: flex; gap: 8px; flex-wrap: wrap; }
.scene-mirror button, .scene-picker button { border: 1px solid rgba(142,151,170,.16); color: #929bad; background: rgba(15,19,29,.72); cursor: pointer; transition: .2s ease; }
.scene-mirror button { display: inline-flex; align-items: center; gap: 7px; padding: 8px 11px; border-radius: 999px; }
.scene-mirror button:hover, .scene-mirror button.active { color: #f5efe4; border-color: var(--scene, rgba(216,182,109,.45)); background: var(--glow, rgba(216,182,109,.12)); transform: translateY(-1px); }
.scene-mirror i, .scene-picker i { width: 7px; height: 7px; border-radius: 50%; background: var(--scene, #d8b66d); box-shadow: 0 0 12px var(--scene, #d8b66d); }
.scene-mirror b { color: #d9dce4; font-size: 11px; font-variant-numeric: tabular-nums; }
.all-dot { background: #e8e0cf !important; }.empty-dot { background: #596174 !important; box-shadow: none !important; }
.star-label-list { display: grid; gap: 10px; }
.star-label-card { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 22px; align-items: center; padding: 17px 19px; border: 1px solid rgba(132,143,164,.12); border-radius: 16px; background: linear-gradient(135deg, rgba(19,23,34,.88), rgba(13,16,25,.78)); transition: .2s ease; }
.star-label-card:hover { border-color: rgba(216,182,109,.22); transform: translateY(-1px); }
.star-copy p { margin: 5px 0 0; color: #d9dce4; line-height: 1.65; white-space: pre-wrap; }
.star-meta { display: flex; gap: 9px; color: #646d80; font-size: 11px; }
.chord { color: #c8a962; }
.scene-picker { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; max-width: 280px; }
.scene-picker.saving { opacity: .55; pointer-events: none; }
.scene-picker button { display: inline-flex; align-items: center; gap: 5px; padding: 6px 9px; border-radius: 9px; font-size: 12px; }
.scene-picker button.selected { color: #f6f0e5; border-color: var(--scene); background: var(--glow); box-shadow: inset 0 0 18px var(--glow); }
.empty-state { padding: 48px 20px; border: 1px dashed rgba(132,143,164,.18); border-radius: 18px; color: #737d91; text-align: center; }
@media (max-width: 760px) { .labels-hero { align-items: flex-start; flex-direction: column; }.batch-box { flex-wrap: wrap; }.star-label-card { grid-template-columns: 1fr; }.scene-picker { justify-content: flex-start; max-width: none; } }
</style>
