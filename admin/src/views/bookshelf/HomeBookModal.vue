<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NInput, NModal, NSpin } from 'naive-ui'
import type { BookAnnotation, ResidentHomeSnapshot } from '@/api/books'

const props = defineProps<{
  show: boolean
  loading: boolean
  snapshot: ResidentHomeSnapshot | null
  annotations: BookAnnotation[]
  annotation: string
  annotationSaving: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'update:annotation': [value: string]
  annotate: []
}>()

const currentChanges = computed(() => {
  if (!props.snapshot) return []
  return props.snapshot.changes[props.snapshot.live.current_week] || []
})

function fmtDateTime(value: string | null | undefined): string {
  return (value || '').slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="《家现在》"
    style="max-width: 860px"
    @update:show="emit('update:show', $event)"
  >
    <NSpin :show="loading">
      <div v-if="snapshot" class="detail home-detail" data-testid="home-snapshot">
        <div class="home-reader-head">
          <div>
            <span>自动家况</span>
            <strong>只读 · 可以追加批注</strong>
          </div>
          <p>这里来自当前运行现场和住户地图，不存在可以手写覆盖的正文。</p>
        </div>

        <div class="home-live-grid">
          <div class="home-live-card">
            <span>当前 commit</span>
            <strong data-testid="home-snapshot-commit">{{ snapshot.live.commit.slice(0, 12) }}</strong>
            <small v-if="snapshot.live.worktree_dirty">工作区有尚未提交的变化</small>
          </div>
          <div class="home-live-card">
            <span>最后确认</span>
            <strong>{{ fmtDateTime(snapshot.live.last_confirmed_at) || '尚未确认' }}</strong>
            <small>不是页面打开时间，而是最近一次住户影响确认</small>
          </div>
          <div class="home-live-card">
            <span>本周变化</span>
            <strong>{{ snapshot.live.current_week_changes }} 条</strong>
            <small>{{ snapshot.live.current_week }}</small>
          </div>
        </div>

        <div class="section">
          <div class="section-title">家的核心机制</div>
          <div class="home-component-grid">
            <article v-for="component in snapshot.components" :key="component.id" class="home-component">
              <div class="home-component-head">
                <strong>{{ component.title }}</strong>
                <span :class="component.status">{{ component.status === 'ok' ? '已确认' : '待确认' }}</span>
              </div>
              <p>{{ component.summary }}</p>
              <ul>
                <li v-for="rule in component.core" :key="rule">{{ rule }}</li>
              </ul>
              <div class="resident-impact">影响：{{ component.resident_effect }}</div>
            </article>
          </div>
        </div>

        <div class="section">
          <div class="section-title">本周变化</div>
          <div v-if="currentChanges.length" class="home-change-list">
            <div v-for="change in currentChanges" :key="`${change.created_at}-${change.title}`" class="home-change">
              <strong>{{ change.title }}：{{ change.summary }}</strong>
              <p>影响：{{ change.impact }}</p>
            </div>
          </div>
          <div v-else class="home-empty-change">这周还没有登记新的变化。</div>
        </div>

        <div v-if="annotations.length" class="section">
          <div class="section-title">夹在家况里的批注</div>
          <div v-for="anno in annotations" :key="anno.id" class="annotation home-annotation">
            <div class="annotation-date">{{ anno.actor || '圆圆' }} · {{ fmtDateTime(anno.created_at) }}</div>
            <div class="annotation-content">{{ anno.content }}</div>
          </div>
        </div>

        <div class="section annotation-editor">
          <div class="section-title">追加一张批注</div>
          <div class="annotation-compose">
            <NInput
              :value="annotation"
              type="textarea"
              :rows="2"
              placeholder="批注会留下，但不会改写自动家况……"
              @update:value="emit('update:annotation', $event)"
            />
            <NButton
              :loading="annotationSaving"
              :disabled="!annotation.trim()"
              @click="emit('annotate')"
            >
              夹进去
            </NButton>
          </div>
        </div>
      </div>
    </NSpin>
  </NModal>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.home-reader-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f5efe8;
  color: #8b7467;
}

.home-reader-head div {
  flex: 0 0 auto;
}

.home-reader-head span,
.home-reader-head strong {
  display: block;
}

.home-reader-head span {
  color: #b49b8d;
  font-size: 9px;
  letter-spacing: 1.5px;
}

.home-reader-head strong {
  margin-top: 2px;
  color: #6f554a;
  font-size: 14px;
}

.home-reader-head p {
  font-size: 10.5px;
  line-height: 1.6;
  text-align: right;
}

.home-live-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.home-live-card {
  min-width: 0;
  padding: 13px 14px;
  border: 1px solid #eadfd7;
  border-radius: 10px;
  background: #fcfaf7;
}

.home-live-card span,
.home-live-card strong,
.home-live-card small {
  display: block;
}

.home-live-card span {
  color: #b09a8f;
  font-size: 9.5px;
  letter-spacing: 0.5px;
}

.home-live-card strong {
  overflow: hidden;
  margin-top: 5px;
  color: #694f45;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-live-card small {
  margin-top: 6px;
  color: #b19d93;
  font-size: 9.5px;
  line-height: 1.5;
}

.section-title {
  margin-bottom: 8px;
  color: var(--sy-mute);
  font-size: 11.5px;
  letter-spacing: 0.3px;
}

.home-component-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.home-component {
  padding: 13px 14px;
  border: 1px solid #ece3dc;
  border-radius: 10px;
  background: var(--sy-paper, #fff);
}

.home-component-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.home-component-head strong {
  color: #644b42;
  font-size: 13px;
}

.home-component-head span {
  flex: 0 0 auto;
  color: #b48a72;
  font-size: 9px;
}

.home-component-head span.ok {
  color: #6f9976;
}

.home-component > p {
  margin-top: 7px;
  color: #8e776c;
  font-size: 10.5px;
  line-height: 1.6;
}

.home-component ul {
  margin: 8px 0 0 16px;
  color: #776259;
  font-size: 10px;
  line-height: 1.65;
}

.resident-impact {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed #eadfd7;
  color: #9a6f73;
  font-size: 10.5px;
  line-height: 1.6;
}

.home-change-list {
  display: grid;
  gap: 8px;
}

.home-change {
  padding: 11px 13px;
  border-left: 3px solid #b68c75;
  border-radius: 4px 9px 9px 4px;
  background: #faf6f1;
}

.home-change strong {
  color: #6f554a;
  font-size: 11.5px;
}

.home-change p,
.home-empty-change {
  margin-top: 5px;
  color: #9b7477;
  font-size: 10.5px;
  line-height: 1.6;
}

.annotation {
  margin-bottom: 8px;
  padding: 10px 14px;
  border-left: 3px solid #b68c75;
  border-radius: 4px 10px 10px 4px;
  background: #faf6f1;
}

.annotation-date {
  margin-bottom: 4px;
  color: #96786b;
  font-size: 10.5px;
}

.annotation-content {
  color: var(--sy-ink);
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.annotation-compose {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 8px;
}

@media (max-width: 700px) {
  .home-reader-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .home-reader-head p {
    text-align: left;
  }

  .home-live-grid,
  .home-component-grid,
  .annotation-compose {
    grid-template-columns: 1fr;
  }
}
</style>
