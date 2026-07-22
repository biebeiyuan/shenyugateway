<script setup lang="ts">
import { ref } from 'vue'
import { NAlert, NModal, NSpin } from 'naive-ui'
import type { ProjectMapSnapshot } from '@/api/books'
import ProjectMapChangesPanel from './ProjectMapChangesPanel.vue'
import ProjectMapConnectionsPanel from './ProjectMapConnectionsPanel.vue'
import ProjectMapFlowPanel from './ProjectMapFlowPanel.vue'
import ProjectMapOverviewPanel from './ProjectMapOverviewPanel.vue'

const props = defineProps<{
  show: boolean
  loading: boolean
  snapshot: ProjectMapSnapshot | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

type AtlasView = 'overview' | 'flow' | 'connections' | 'changes'

const activeView = ref<AtlasView>('overview')
const tabs: Array<{ id: AtlasView; label: string }> = [
  { id: 'overview', label: '先看全貌' },
  { id: 'flow', label: '消息怎样走' },
  { id: 'connections', label: '哪里连接' },
  { id: 'changes', label: '最近变化' },
]

function fmtDateTime(value: string | null | undefined): string {
  return (value || '').slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="《家里地图》"
    style="width: min(1120px, calc(100vw - 24px)); max-height: calc(100dvh - 24px); overflow: hidden"
    content-style="min-height: 0; overflow-y: auto; background: #fffdfb"
    @update:show="emit('update:show', $event)"
  >
    <NSpin :show="loading">
      <div v-if="props.snapshot" class="atlas" data-testid="project-map-atlas">
        <header class="atlas-head">
          <div>
            <span class="atlas-kicker">给圆圆的只读地图</span>
            <strong>此刻的家，怎样连在一起</strong>
            <p>从当前版本、现行地图和确认记录现场重画。</p>
          </div>
          <div class="atlas-state" :class="props.snapshot.summary.status">
            <span class="state-dot"></span>
            <div>
              <strong data-testid="project-map-status">
                {{ props.snapshot.summary.pending_count ? `${props.snapshot.summary.pending_count} 处待复核` : '地图与现场一致' }}
              </strong>
              <small>
                {{ props.snapshot.live.worktree_dirty
                  ? '工作区有尚未提交的变化'
                  : `版本 ${props.snapshot.live.commit.slice(0, 9)}` }}
              </small>
            </div>
          </div>
        </header>

        <NAlert v-for="warning in props.snapshot.warnings" :key="warning" type="warning" :show-icon="false">
          {{ warning }}
        </NAlert>

        <nav class="atlas-tabs" aria-label="地图册分页">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            type="button"
            :class="{ active: activeView === tab.id }"
            :data-testid="`project-map-tab-${tab.id}`"
            @click="activeView = tab.id"
          >
            {{ tab.label }}
          </button>
        </nav>

        <ProjectMapOverviewPanel v-if="activeView === 'overview'" :snapshot="props.snapshot" />
        <ProjectMapFlowPanel v-else-if="activeView === 'flow'" :snapshot="props.snapshot" />
        <ProjectMapConnectionsPanel v-else-if="activeView === 'connections'" :snapshot="props.snapshot" />
        <ProjectMapChangesPanel v-else :snapshot="props.snapshot" />

        <footer class="atlas-foot">
          <span>读取于 {{ fmtDateTime(props.snapshot.live.observed_at) }}</span>
          <span>这册只在 Admin 里出现，不进入沈予的上下文。</span>
        </footer>
      </div>
    </NSpin>
  </NModal>
</template>

<style scoped>
.atlas {
  --ink: #5e4745;
  --muted: #9b8583;
  --rose: #b97e91;
  --rose-soft: #f7e9ed;
  --sage: #728d7c;
  --sage-soft: #edf4ef;
  --paper: #fffdfb;
  --line: #eadcda;
  display: flex;
  flex-direction: column;
  color: var(--ink);
}

.atlas-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 2px 2px 16px;
  border-bottom: 1px solid var(--line);
}

.atlas-kicker {
  display: block;
  color: var(--rose);
  font-size: 10px;
}

.atlas-head > div:first-child > strong {
  display: block;
  margin-top: 4px;
  font-size: 21px;
  font-weight: 600;
}

.atlas-head p {
  margin-top: 5px;
  color: var(--muted);
  font-size: 11px;
}

.atlas-state {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 190px;
  padding: 10px 12px;
  border: 1px solid #dce9df;
  border-radius: 6px;
  background: var(--sage-soft);
}

.atlas-state.attention {
  border-color: #ecd9c7;
  background: #fff5e9;
}

.state-dot {
  flex: 0 0 9px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--sage);
  box-shadow: 0 0 0 4px rgb(114 141 124 / 12%);
}

.attention .state-dot {
  background: #c28c60;
  box-shadow: 0 0 0 4px rgb(194 140 96 / 12%);
}

.atlas-state strong,
.atlas-state small {
  display: block;
}

.atlas-state strong { font-size: 12px; }

.atlas-state small {
  margin-top: 3px;
  color: var(--muted);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 9px;
}

.atlas-tabs {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin: 15px 0 18px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #faf5f4;
}

.atlas-tabs button {
  min-height: 34px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-family: inherit;
  font-size: 11px;
}

.atlas-tabs button.active {
  background: #fff;
  color: #76565f;
  box-shadow: 0 2px 8px rgb(92 55 65 / 8%);
}

.atlas-foot {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  color: #ac9997;
  font-size: 9px;
}

@media (max-width: 760px) {
  .atlas-head { align-items: flex-start; }
  .atlas-head > div:first-child > strong { font-size: 17px; }
  .atlas-head p { max-width: 210px; }
  .atlas-state { min-width: 0; padding: 8px; }
  .atlas-state small { display: none; }
  .atlas-tabs { overflow-x: auto; }
  .atlas-tabs button { min-width: 76px; padding: 0 6px; }
  .atlas-foot { display: grid; gap: 4px; }
}
</style>
