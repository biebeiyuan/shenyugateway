<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectMapComponent, ProjectMapSnapshot } from '@/api/books'

const props = defineProps<{ snapshot: ProjectMapSnapshot }>()

const reviewTimeline = computed(() => (
  [...props.snapshot.components]
    .sort((left, right) => String(right.reviewed.reviewed_at || '').localeCompare(String(left.reviewed.reviewed_at || '')))
))

function statusText(status: ProjectMapComponent['status']): string {
  if (status === 'ok') return '已确认'
  if (status === 'error') return '映射中断'
  return '待复核'
}

function fmtDateTime(value: string | null | undefined): string {
  return (value || '').slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <section class="changes-page">
    <div class="review-banner" :class="props.snapshot.summary.status">
      <span class="state-dot"></span>
      <div>
        <strong>{{ props.snapshot.summary.pending_count ? '还有变化等待确认' : '当前映射都已确认' }}</strong>
        <p>
          {{ props.snapshot.summary.pending_count
            ? '源码已经变化，但住户影响还没有被最后确认。'
            : '当前组件指纹与最近一次人工复核一致。' }}
        </p>
      </div>
    </div>

    <div v-if="props.snapshot.summary.pending_count" class="pending-list">
      <article v-for="component in props.snapshot.components.filter(item => item.status !== 'ok')" :key="component.id">
        <span>{{ statusText(component.status) }}</span>
        <strong>{{ component.title }}</strong>
        <p>{{ component.summary }}</p>
      </article>
    </div>

    <div class="change-columns">
      <section>
        <div class="section-label">已经记下的生活变化</div>
        <div v-if="props.snapshot.changes.length" class="change-timeline">
          <article v-for="change in props.snapshot.changes" :key="`${change.created_at}-${change.title}`">
            <time>{{ fmtDateTime(change.created_at) }}</time>
            <strong>{{ change.title }} · {{ change.summary }}</strong>
            <p>{{ change.impact }}</p>
          </article>
        </div>
        <p v-else class="empty-note">还没有新的住户影响记录。</p>
      </section>

      <section>
        <div class="section-label">最近确认过的机制</div>
        <div class="review-list">
          <article v-for="component in reviewTimeline" :key="component.id">
            <span :class="component.status"></span>
            <div>
              <strong>{{ component.title }}</strong>
              <small>
                {{ component.reviewed.reviewed_by || '尚未署名' }} ·
                {{ fmtDateTime(component.reviewed.reviewed_at) || '尚未确认' }}
              </small>
            </div>
          </article>
        </div>
      </section>
    </div>

    <details class="document-fold">
      <summary>这张地图依据的现行文档</summary>
      <div class="document-list">
        <article v-for="document in props.snapshot.documents" :key="document['文档']">
          <code>{{ document['文档'] }}</code>
          <p>{{ document['职责'] }}</p>
        </article>
      </div>
    </details>
  </section>
</template>

<style scoped>
.review-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #dce9df;
  border-radius: 6px;
  background: var(--sage-soft);
}

.review-banner.attention { border-color: #ecd9c7; background: #fff5e9; }
.state-dot { flex: 0 0 9px; width: 9px; height: 9px; border-radius: 50%; background: var(--sage); box-shadow: 0 0 0 4px rgb(114 141 124 / 12%); }
.attention .state-dot { background: #c28c60; box-shadow: 0 0 0 4px rgb(194 140 96 / 12%); }
.review-banner strong,
.review-banner p { display: block; }
.review-banner strong { font-size: 12px; }
.review-banner p { margin-top: 3px; color: var(--muted); font-size: 9.5px; }

.pending-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.pending-list article { padding: 12px 14px; border-left: 3px solid #c28c60; border-radius: 4px; background: #fff8ef; }
.pending-list span,
.pending-list strong { display: block; }
.pending-list span { color: #b27a4d; font-size: 8.5px; }
.pending-list strong { margin-top: 3px; font-size: 11px; }
.pending-list p { margin-top: 5px; color: var(--muted); font-size: 9.5px; line-height: 1.55; }

.change-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(260px, 0.8fr);
  gap: 24px;
  margin-top: 18px;
}

.section-label { display: block; margin-bottom: 10px; color: var(--rose); font-size: 10px; }
.change-timeline { border-left: 1px solid #d8b7c0; }
.change-timeline article { position: relative; padding: 0 0 17px 17px; }

.change-timeline article::before {
  position: absolute;
  top: 4px;
  left: -4px;
  width: 7px;
  height: 7px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: var(--rose);
  box-shadow: 0 0 0 1px #d8b7c0;
  content: '';
}

.change-timeline time,
.change-timeline strong,
.change-timeline p { display: block; }
.change-timeline time { color: var(--muted); font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 8.5px; }
.change-timeline strong { margin-top: 3px; font-size: 10.5px; }
.change-timeline p { margin-top: 4px; color: #8f7775; font-size: 9.5px; line-height: 1.55; }

.review-list { display: grid; gap: 6px; }
.review-list article { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 8px 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--sy-paper, #fff); }
.review-list article > span { flex: 0 0 7px; width: 7px; height: 7px; border-radius: 50%; background: var(--sage); }
.review-list article > span.review_required { background: #c28c60; }
.review-list article > span.error { background: #b85f64; }
.review-list strong,
.review-list small { display: block; }
.review-list strong { font-size: 10px; }
.review-list small { margin-top: 2px; color: var(--muted); font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 8.5px; }
.empty-note { color: var(--muted); font-size: 10px; }

.document-fold { margin-top: 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--sy-paper, #fff); }
.document-fold summary { padding: 10px 12px; color: #90787a; cursor: pointer; font-size: 10px; }
.document-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; padding: 1px; background: var(--line); }
.document-list article { min-width: 0; padding: 10px 12px; background: var(--sy-paper, #fff); }
.document-list code { overflow-wrap: anywhere; color: #8e6270; font-size: 9px; }
.document-list p { margin-top: 4px; color: var(--muted); font-size: 9px; line-height: 1.5; }

@media (max-width: 760px) {
  .pending-list,
  .document-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .change-columns { grid-template-columns: 1fr; }
}
</style>
