<script setup lang="ts">
import { ref, watch } from 'vue'
import { NButton } from 'naive-ui'
import type { StarCandidate, StarItem, StarReviewItem } from '@/api/stars'
import { rootLabel, scoreParts, sourceMeta } from './starUi'

const props = defineProps<{
  items: StarReviewItem[]
  sessionTag: string
  connectName: string
  connectNote: string
  feedbackingKey: string
}>()

const emit = defineEmits<{
  (event: 'update:sessionTag', value: string): void
  (event: 'update:connectName', value: string): void
  (event: 'update:connectNote', value: string): void
  (event: 'feedbackCandidate', payload: { seed: StarItem; candidate: StarCandidate; feedback: 'positive' | 'negative' | 'skipped' }): void
  (event: 'feedbackMissed', payload: { seed: StarItem; runId?: string | null; expectedStarId: string }): void
  (event: 'connectCandidate', payload: { seed: StarItem; candidate: StarCandidate }): void
  (event: 'selectStar', starId: string): void
}>()

const expandedSeeds = ref<string[]>([])
const missedStarId = ref<Record<string, string>>({})

watch(
  () => props.items,
  (items) => {
    if (!items.length) {
      expandedSeeds.value = []
      return
    }
    const stillVisible = expandedSeeds.value.some((id) => items.some((item) => item.star.id === id))
    if (!stillVisible) expandedSeeds.value = [items[0].star.id]
  },
  { immediate: true },
)

function candidateKey(seed: StarItem, candidate: StarCandidate): string {
  return candidate.candidate_id || `${seed.id}:${candidate.id}`
}

function toggleSeed(seedId: string) {
  if (expandedSeeds.value.includes(seedId)) {
    expandedSeeds.value = expandedSeeds.value.filter((item) => item !== seedId)
    return
  }
  expandedSeeds.value = [...expandedSeeds.value, seedId]
}

function feedbackCandidate(seed: StarItem, candidate: StarCandidate, feedback: 'positive' | 'negative' | 'skipped') {
  emit('feedbackCandidate', { seed, candidate, feedback })
}

function feedbackMissed(seed: StarItem, runId?: string | null) {
  const expectedStarId = (missedStarId.value[seed.id] || '').trim()
  if (!expectedStarId) return
  missedStarId.value[seed.id] = ''
  emit('feedbackMissed', { seed, runId, expectedStarId })
}

function connectCandidate(seed: StarItem, candidate: StarCandidate) {
  emit('connectCandidate', { seed, candidate })
}
</script>

<template>
  <div class="score-space">
    <div class="soft-toolbar">
      <input
        :value="sessionTag"
        class="soft-input"
        placeholder="session_tag"
        @input="emit('update:sessionTag', ($event.target as HTMLInputElement).value)"
      >
      <input
        :value="connectName"
        class="soft-input"
        placeholder="星座名"
        @input="emit('update:connectName', ($event.target as HTMLInputElement).value)"
      >
      <input
        :value="connectNote"
        class="soft-input wide"
        placeholder="连线备注"
        @input="emit('update:connectNote', ($event.target as HTMLInputElement).value)"
      >
    </div>

    <div v-if="!items.length" class="empty-score">
      <span>没有待评分批次</span>
      <span>右上角拿一小批</span>
    </div>

    <div
      v-for="item in items"
      :key="item.star.id"
      class="seed-tile"
      :class="{ open: expandedSeeds.includes(item.star.id) }"
    >
      <button class="seed-head" type="button" @click="toggleSeed(item.star.id)">
        <span class="seed-dot"></span>
        <span class="seed-chord">{{ rootLabel(item.star) }}</span>
        <span class="seed-text">{{ item.star.content }}</span>
        <span class="seed-count">{{ item.candidates.length }} 待评</span>
      </button>

      <div v-if="expandedSeeds.includes(item.star.id)" class="seed-body">
        <div class="source-box light">
          <div class="source-meta">{{ sourceMeta(item.star) || '来源暂缺' }}</div>
          <div class="source-text">{{ item.star.source_excerpt || '这颗星没有保存来源原文。' }}</div>
        </div>
        <div class="missed-line">
          <input v-model="missedStarId[item.star.id]" class="soft-input wide" placeholder="漏反的 star id">
          <NButton size="small" :loading="feedbackingKey === `${item.star.id}:missed`" @click="feedbackMissed(item.star, item.run_id)">记漏反</NButton>
        </div>

        <div v-if="!item.candidates.length" class="empty-candidates">没有候选</div>
        <div v-for="candidate in item.candidates" :key="candidate.id" class="candidate-line fresh">
          <button class="candidate-main" type="button" @click="emit('selectStar', candidate.id)">
            <span class="candidate-status">未评分</span>
            <span class="candidate-chord">{{ rootLabel(candidate) }}</span>
            <span class="candidate-text">{{ candidate.content }}</span>
            <span class="candidate-score">{{ candidate.score ?? 0 }}</span>
          </button>
          <details v-if="candidate.source_excerpt" class="candidate-source">
            <summary>{{ sourceMeta(candidate) || '来源原文' }}</summary>
            <div>{{ candidate.source_excerpt }}</div>
          </details>
          <div class="candidate-detail">
            <span>{{ scoreParts(candidate) || 'no scores' }}</span>
            <div class="score-actions">
              <NButton size="tiny" type="primary" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:connected`" @click="connectCandidate(item.star, candidate)">连起来</NButton>
              <NButton size="tiny" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:positive`" @click="feedbackCandidate(item.star, candidate, 'positive')">该反</NButton>
              <NButton size="tiny" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:negative`" @click="feedbackCandidate(item.star, candidate, 'negative')">不该反</NButton>
              <NButton size="tiny" :loading="feedbackingKey === `${candidateKey(item.star, candidate)}:skipped`" @click="feedbackCandidate(item.star, candidate, 'skipped')">先放过</NButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.soft-toolbar,
.missed-line {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.soft-input {
  min-width: 150px;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #ead4cf;
  border-radius: 6px;
  background: #fff;
  color: #4a3535;
  outline: none;
  transition: border-color 0.16s, background 0.16s;
}

.soft-input.wide {
  flex: 1;
  min-width: 240px;
}

.seed-tile {
  margin-top: 10px;
  border: 1px solid #ead4cf;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.seed-tile.open {
  border-color: #d4a7a2;
  box-shadow: 0 10px 26px rgba(98, 70, 82, 0.08);
}

.seed-tile.done {
  border-color: #b8d6c0;
}

.seed-head {
  width: 100%;
  display: grid;
  grid-template-columns: auto minmax(64px, auto) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 0;
  background: transparent;
  color: #4a3535;
  cursor: pointer;
  text-align: left;
}

.seed-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #d9c8c4;
  box-shadow: 0 0 0 rgba(217, 200, 196, 0);
}

.seed-dot.warm {
  background: #e5b275;
  box-shadow: 0 0 14px rgba(229, 178, 117, 0.55);
}

.seed-dot.done {
  background: #92ba9c;
  box-shadow: 0 0 16px rgba(146, 186, 156, 0.5);
}

.seed-chord,
.candidate-chord {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 46px;
  max-width: 92px;
  min-height: 26px;
  padding: 2px 8px;
  border: 1px solid #ead4cf;
  border-radius: 999px;
  background: #fffaf8;
  color: #967180;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}

.seed-text,
.candidate-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.45;
}

.seed-count,
.candidate-score,
.candidate-status {
  color: #b8a8a3;
  font-size: 12px;
  white-space: nowrap;
}

.seed-body {
  padding: 0 12px 12px;
}

.source-box {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid rgba(255, 232, 199, 0.18);
  border-radius: 7px;
  background: rgba(255, 250, 244, 0.08);
}

.source-box.light {
  margin: 0 0 10px;
  border-color: #f0e0dc;
  background: #fffaf8;
}

.source-meta {
  margin-bottom: 6px;
  color: #a88780;
  font-size: 11px;
}

.source-text {
  max-height: 180px;
  overflow: auto;
  color: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: 12px;
}

.candidate-line {
  margin-top: 8px;
  border: 1px solid #f0e0dc;
  border-radius: 7px;
  background: #fffdfc;
}

.candidate-main {
  width: 100%;
  display: grid;
  grid-template-columns: 74px minmax(64px, auto) minmax(0, 1fr) 54px;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border: 0;
  background: transparent;
  color: #4a3535;
  cursor: pointer;
  text-align: left;
}

.candidate-detail {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  padding: 0 10px 10px;
  color: #7a6a6a;
  font-size: 12px;
  flex-wrap: wrap;
}

.candidate-source {
  margin: 0 10px 8px;
  padding: 8px 9px;
  border: 1px solid #f0e0dc;
  border-radius: 6px;
  background: #fffaf8;
  color: #6f5d5d;
  font-size: 12px;
}

.candidate-source summary {
  cursor: pointer;
  color: #a88780;
}

.candidate-source div {
  margin-top: 6px;
  max-height: 160px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
}

.score-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.empty-score,
.empty-candidates {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 86px;
  color: #9b8a88;
  font-size: 13px;
}

@media (max-width: 980px) {
  .seed-head {
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: start;
    gap: 8px;
  }

  .seed-chord {
    grid-column: 2;
    justify-self: start;
  }

  .seed-text {
    grid-column: 2 / 4;
    white-space: normal;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .seed-count {
    grid-column: 2;
  }

  .candidate-main {
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: start;
    gap: 7px 8px;
  }

  .candidate-chord {
    grid-column: 1;
    grid-row: 1;
    justify-self: start;
  }

  .candidate-text {
    grid-column: 1 / 3;
    grid-row: 2;
    white-space: normal;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .candidate-status,
  .candidate-score {
    display: none;
  }

  .soft-input,
  .soft-input.wide {
    width: 100%;
  }
}
</style>
