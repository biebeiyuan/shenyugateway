<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NModal, NSelect, NSpin } from 'naive-ui'
import type {
  ProjectMapComponent,
  ProjectMapFlowStage,
  ProjectMapSnapshot,
  ProjectMapZone,
} from '@/api/books'

const props = defineProps<{
  show: boolean
  loading: boolean
  snapshot: ProjectMapSnapshot | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

type AtlasView = 'overview' | 'flow' | 'connections' | 'changes'
type OverviewFocus = 'components' | 'zones' | 'bridges'

const activeView = ref<AtlasView>('overview')
const overviewFocus = ref<OverviewFocus | null>(null)
const selectedComponentId = ref('')
const selectedZoneId = ref('')
const selectedFlowId = ref('')

const tabs: Array<{ id: AtlasView; label: string }> = [
  { id: 'overview', label: '先看全貌' },
  { id: 'flow', label: '消息怎样走' },
  { id: 'connections', label: '哪里连接' },
  { id: 'changes', label: '最近变化' },
]

watch(
  () => props.snapshot,
  (snapshot) => {
    if (!snapshot) return
    if (!snapshot.components.some(item => item.id === selectedComponentId.value)) {
      selectedComponentId.value = snapshot.components[0]?.id || ''
    }
    if (!snapshot.request_flow.some(item => item.id === selectedFlowId.value)) {
      selectedFlowId.value = snapshot.request_flow[0]?.id || ''
    }
    if (!snapshot.zones.some(item => item.id === selectedZoneId.value)) {
      selectedZoneId.value = snapshot.zones[0]?.id || ''
    }
  },
  { immediate: true },
)

const selectedComponent = computed<ProjectMapComponent | null>(() => (
  props.snapshot?.components.find(item => item.id === selectedComponentId.value) || null
))

const selectedFlow = computed<ProjectMapFlowStage | null>(() => (
  props.snapshot?.request_flow.find(item => item.id === selectedFlowId.value) || null
))

const selectedZone = computed<ProjectMapZone | null>(() => (
  props.snapshot?.zones.find(item => item.id === selectedZoneId.value) || null
))

const componentOptions = computed(() => (
  (props.snapshot?.components || []).map(item => ({ label: item.title, value: item.id }))
))

const selectedConnections = computed(() => {
  if (!props.snapshot || !selectedComponent.value) return []
  return props.snapshot.component_bridges
    .filter(item => item.left_id === selectedComponent.value?.id || item.right_id === selectedComponent.value?.id)
    .map((connection) => {
      const neighborId = connection.left_id === selectedComponent.value?.id
        ? connection.right_id
        : connection.left_id
      return {
        ...connection,
        neighbor: props.snapshot?.components.find(item => item.id === neighborId) || null,
      }
    })
    .filter(item => item.neighbor)
})

const reviewTimeline = computed(() => (
  [...(props.snapshot?.components || [])]
    .sort((left, right) => String(right.reviewed.reviewed_at || '').localeCompare(String(left.reviewed.reviewed_at || '')))
))

function zoneFor(id: string): ProjectMapZone | undefined {
  return props.snapshot?.zones.find(zone => zone.id === id)
}

function componentFor(id: string): ProjectMapComponent | undefined {
  return props.snapshot?.components.find(component => component.id === id)
}

function toggleOverview(value: OverviewFocus): void {
  overviewFocus.value = overviewFocus.value === value ? null : value
}

function openComponent(id: string): void {
  selectedComponentId.value = id
  overviewFocus.value = 'components'
}

function statusText(status: ProjectMapComponent['status']): string {
  if (status === 'ok') return '已确认'
  if (status === 'error') return '映射中断'
  return '待复核'
}

function fmtDateTime(value: string | null | undefined): string {
  return (value || '').slice(0, 16).replace('T', ' ')
}

function shortPath(value: string): string {
  const parts = value.split('/')
  return parts.length > 2 ? `${parts[0]}/…/${parts[parts.length - 1]}` : value
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
      <div v-if="snapshot" class="atlas" data-testid="project-map-atlas">
        <header class="atlas-head">
          <div>
            <span class="atlas-kicker">给圆圆的只读地图</span>
            <strong>此刻的家，怎样连在一起</strong>
            <p>从当前版本、现行地图和确认记录现场重画。</p>
          </div>
          <div class="atlas-state" :class="snapshot.summary.status">
            <span class="state-dot"></span>
            <div>
              <strong data-testid="project-map-status">
                {{ snapshot.summary.pending_count ? `${snapshot.summary.pending_count} 处待复核` : '地图与现场一致' }}
              </strong>
              <small>{{ snapshot.live.worktree_dirty ? '工作区有尚未提交的变化' : `版本 ${snapshot.live.commit.slice(0, 9)}` }}</small>
            </div>
          </div>
        </header>

        <NAlert v-for="warning in snapshot.warnings" :key="warning" type="warning" :show-icon="false">
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

        <section v-if="activeView === 'overview'" class="atlas-page overview-page">
          <div class="overview-gates">
            <button
              type="button"
              :class="{ active: overviewFocus === 'components' }"
              data-testid="project-map-overview-components"
              @click="toggleOverview('components')"
            >
              <span>生活这一侧</span>
              <strong>家里的机制</strong>
              <b>{{ snapshot.summary.component_count }}</b>
              <small>{{ snapshot.summary.confirmed_count }} 处已与现场对上</small>
            </button>
            <button
              type="button"
              :class="{ active: overviewFocus === 'zones' }"
              data-testid="project-map-overview-zones"
              @click="toggleOverview('zones')"
            >
              <span>Agent 找路这一侧</span>
              <strong>架构分区</strong>
              <b>{{ snapshot.summary.zone_count }}</b>
              <small>每一块各自守住的边界</small>
            </button>
            <button
              type="button"
              :class="{ active: overviewFocus === 'bridges' }"
              data-testid="project-map-overview-bridges"
              @click="toggleOverview('bridges')"
            >
              <span>一起改动这一侧</span>
              <strong>关键桥梁</strong>
              <b>{{ snapshot.summary.bridge_count }}</b>
              <small>跨区时必须共同确认的地方</small>
            </button>
          </div>

          <div v-if="!overviewFocus" class="overview-rest">
            <div>
              <span>当前版本</span>
              <strong>{{ snapshot.live.commit.slice(0, 12) }}</strong>
            </div>
            <div>
              <span>最近确认</span>
              <strong>{{ fmtDateTime(snapshot.live.last_confirmed_at) || '尚未确认' }}</strong>
            </div>
            <div>
              <span>当前状态</span>
              <strong>{{ snapshot.summary.pending_count ? `${snapshot.summary.pending_count} 处待复核` : '全部已经对上' }}</strong>
            </div>
          </div>

          <template v-if="overviewFocus === 'components'">
            <div class="component-map" aria-label="家的核心机制">
              <button
                v-for="component in snapshot.components"
                :key="component.id"
                type="button"
                class="component-tile"
                :class="[{ active: selectedComponentId === component.id }, component.status]"
                :aria-pressed="selectedComponentId === component.id"
                @click="selectedComponentId = component.id"
              >
                <span class="component-status"></span>
                <strong>{{ component.title }}</strong>
                <small>{{ component.summary }}</small>
              </button>
            </div>

            <article v-if="selectedComponent" class="focus-sheet">
              <div class="focus-copy">
                <span>{{ statusText(selectedComponent.status) }}</span>
                <h3>{{ selectedComponent.title }}</h3>
                <p>{{ selectedComponent.resident_effect }}</p>
              </div>
              <div class="focus-rules">
                <strong>它守住的事</strong>
                <ul>
                  <li v-for="rule in selectedComponent.core" :key="rule">{{ rule }}</li>
                </ul>
              </div>
              <details class="evidence-fold">
                <summary>依据与技术位置</summary>
                <div class="evidence-tags">
                  <span v-for="zoneId in selectedComponent.zone_ids" :key="zoneId">
                    {{ zoneFor(zoneId)?.title }}
                  </span>
                  <code v-for="file in selectedComponent.files" :key="file" :title="file">{{ shortPath(file) }}</code>
                </div>
              </details>
            </article>
          </template>

          <template v-else-if="overviewFocus === 'zones'">
            <div class="zone-index" data-testid="project-map-zone-index">
              <button
                v-for="zone in snapshot.zones"
                :key="zone.id"
                type="button"
                :class="{ active: selectedZoneId === zone.id }"
                @click="selectedZoneId = zone.id"
              >
                <span>区域{{ zone.number }}</span>
                <strong>{{ zone.title }}</strong>
                <p>{{ zone.summary }}</p>
              </button>
            </div>

            <article v-if="selectedZone" class="zone-sheet">
              <div>
                <span>区域{{ selectedZone.number }}</span>
                <h3>{{ selectedZone.title }}</h3>
                <p>{{ selectedZone.summary }}</p>
              </div>
              <div>
                <strong>这里负责</strong>
                <ul>
                  <li v-for="item in selectedZone.responsibilities" :key="item">{{ item }}</li>
                </ul>
              </div>
              <div v-if="selectedZone.component_ids.length" class="zone-components">
                <span>这里经过的生活机制</span>
                <button
                  v-for="componentId in selectedZone.component_ids"
                  :key="componentId"
                  type="button"
                  @click="openComponent(componentId)"
                >
                  {{ componentFor(componentId)?.title }}
                </button>
              </div>
              <details class="evidence-fold">
                <summary>核心技术位置</summary>
                <div class="evidence-tags">
                  <code v-for="file in selectedZone.core_files" :key="file">{{ file }}</code>
                </div>
              </details>
            </article>
          </template>

          <div v-else-if="overviewFocus === 'bridges'" class="overview-bridges" data-testid="project-map-bridge-index">
            <div class="bridge-table">
              <div v-for="bridge in snapshot.bridges" :key="bridge['桥梁']" class="bridge-row">
                <code>{{ bridge['桥梁'] }}</code>
                <strong>{{ bridge['连接区域'] }}</strong>
                <span>{{ bridge['审计重点'] }}</span>
              </div>
            </div>
          </div>
        </section>

        <section v-else-if="activeView === 'flow'" class="atlas-page flow-page">
          <div class="flow-track" data-testid="project-map-flow">
            <button
              v-for="(stage, index) in snapshot.request_flow"
              :key="stage.id"
              type="button"
              class="flow-stop"
              :class="{ active: selectedFlowId === stage.id }"
              :aria-pressed="selectedFlowId === stage.id"
              @click="selectedFlowId = stage.id"
            >
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <strong>{{ stage.label }}</strong>
            </button>
          </div>

          <article v-if="selectedFlow" class="flow-sheet">
            <div class="flow-number">
              {{ String(snapshot.request_flow.findIndex(item => item.id === selectedFlowId) + 1).padStart(2, '0') }}
            </div>
            <div class="flow-copy">
              <span>这一站</span>
              <h3>{{ selectedFlow.label }}</h3>
              <p>{{ selectedFlow.meaning }}</p>
              <div v-if="selectedFlow.zone_ids.length" class="zone-chips">
                <span v-for="zoneId in selectedFlow.zone_ids" :key="zoneId">{{ zoneFor(zoneId)?.title }}</span>
              </div>
            </div>
            <div v-if="selectedFlow.details.length" class="flow-details">
              <strong>这里还会经过</strong>
              <ul>
                <li v-for="detail in selectedFlow.details" :key="detail">{{ detail }}</li>
              </ul>
            </div>
          </article>
        </section>

        <section v-else-if="activeView === 'connections'" class="atlas-page connections-page">
          <div class="connection-heading">
            <div>
              <span>当前中心</span>
              <strong>{{ selectedComponent?.title }}</strong>
            </div>
            <NSelect v-model:value="selectedComponentId" :options="componentOptions" class="component-select" />
          </div>

          <div v-if="selectedComponent" class="connection-board" data-testid="project-map-connections">
            <button type="button" class="connection-source">
              <span>{{ statusText(selectedComponent.status) }}</span>
              <strong>{{ selectedComponent.title }}</strong>
              <small>{{ selectedComponent.summary }}</small>
            </button>
            <div v-if="selectedConnections.length" class="connection-trunk" aria-hidden="true"></div>
            <div v-if="selectedConnections.length" class="neighbor-list">
              <button
                v-for="connection in selectedConnections"
                :key="connection.id"
                type="button"
                class="neighbor-node"
                @click="selectedComponentId = connection.neighbor?.id || selectedComponentId"
              >
                <span>共同经过</span>
                <strong>{{ connection.neighbor?.title }}</strong>
                <small>{{ connection.via_files.map(shortPath).join(' · ') }}</small>
              </button>
            </div>
            <div v-else class="no-neighbor">这一块目前没有从源码映射出直接连接。</div>
          </div>

          <article v-if="selectedComponent" class="connection-note">
            <strong>{{ selectedComponent.title }} 改动时会一起看的地方</strong>
            <p>{{ selectedComponent.resident_effect }}</p>
            <ul v-if="selectedConnections.length">
              <li v-for="connection in selectedConnections" :key="connection.id">
                <button type="button" @click="selectedComponentId = connection.neighbor?.id || selectedComponentId">
                  {{ connection.neighbor?.title }}
                </button>
                <span>{{ connection.meaning }}</span>
              </li>
            </ul>
          </article>

          <details class="bridge-fold">
            <summary>全屋的关键跨区桥梁</summary>
            <div class="bridge-table">
              <div v-for="bridge in snapshot.bridges" :key="bridge['桥梁']" class="bridge-row">
                <code>{{ bridge['桥梁'] }}</code>
                <strong>{{ bridge['连接区域'] }}</strong>
                <span>{{ bridge['审计重点'] }}</span>
              </div>
            </div>
          </details>
        </section>

        <section v-else class="atlas-page changes-page">
          <div class="review-banner" :class="snapshot.summary.status">
            <span class="state-dot"></span>
            <div>
              <strong>{{ snapshot.summary.pending_count ? '还有变化等待确认' : '当前映射都已确认' }}</strong>
              <p>
                {{ snapshot.summary.pending_count
                  ? '源码已经变化，但住户影响还没有被最后确认。'
                  : '当前组件指纹与最近一次人工复核一致。' }}
              </p>
            </div>
          </div>

          <div v-if="snapshot.summary.pending_count" class="pending-list">
            <article v-for="component in snapshot.components.filter(item => item.status !== 'ok')" :key="component.id">
              <span>{{ statusText(component.status) }}</span>
              <strong>{{ component.title }}</strong>
              <p>{{ component.summary }}</p>
            </article>
          </div>

          <div class="change-columns">
            <section>
              <div class="section-label">已经记下的生活变化</div>
              <div v-if="snapshot.changes.length" class="change-timeline">
                <article v-for="change in snapshot.changes" :key="`${change.created_at}-${change.title}`">
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
              <article v-for="document in snapshot.documents" :key="document['文档']">
                <code>{{ document['文档'] }}</code>
                <p>{{ document['职责'] }}</p>
              </article>
            </div>
          </details>
        </section>

        <footer class="atlas-foot">
          <span>读取于 {{ fmtDateTime(snapshot.live.observed_at) }}</span>
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

.atlas-kicker,
.connection-heading span,
.flow-copy > span,
.section-label {
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

.atlas-state,
.review-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 190px;
  padding: 10px 12px;
  border: 1px solid #dce9df;
  border-radius: 6px;
  background: var(--sage-soft);
}

.atlas-state.attention,
.review-banner.attention {
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

.atlas-state strong {
  font-size: 12px;
}

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

.atlas-page {
  flex: 1;
}

.overview-gates {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}

.overview-gates button {
  position: relative;
  min-height: 108px;
  padding: 14px 46px 13px 15px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--paper);
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: border-color 150ms ease, background 150ms ease, transform 150ms ease;
}

.overview-gates button:hover,
.overview-gates button:focus-visible,
.overview-gates button.active {
  border-color: #cc9aaa;
  outline: none;
  background: #fff7f9;
  transform: translateY(-2px);
}

.overview-gates span,
.overview-gates strong,
.overview-gates b,
.overview-gates small {
  display: block;
}

.overview-gates span {
  color: var(--rose);
  font-size: 9px;
}

.overview-gates strong {
  margin-top: 7px;
  font-size: 14px;
}

.overview-gates b {
  position: absolute;
  top: 14px;
  right: 15px;
  color: #c5a2ab;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 25px;
  font-weight: 500;
}

.overview-gates small {
  margin-top: 9px;
  color: var(--muted);
  font-size: 9px;
  line-height: 1.5;
}

.overview-rest {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 14px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: #fcf8f7;
}

.overview-rest > div {
  min-width: 0;
  padding: 13px 15px;
}

.overview-rest > div + div {
  border-left: 1px solid var(--line);
}

.overview-rest span,
.overview-rest strong {
  display: block;
}

.overview-rest span {
  color: var(--muted);
  font-size: 8.5px;
}

.overview-rest strong {
  margin-top: 4px;
  overflow: hidden;
  color: #745660;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.component-map {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.component-tile {
  position: relative;
  min-height: 105px;
  padding: 13px 13px 12px 17px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: border-color 150ms ease, transform 150ms ease, box-shadow 150ms ease;
}

.component-tile:hover,
.component-tile:focus-visible,
.component-tile.active {
  border-color: #cfaab5;
  outline: none;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgb(99 66 74 / 9%);
}

.component-status {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 4px;
  background: var(--sage);
}

.component-tile.review_required .component-status { background: #c28c60; }
.component-tile.error .component-status { background: #b85f64; }

.component-tile strong,
.component-tile small {
  display: block;
}

.component-tile strong {
  font-size: 13px;
}

.component-tile small {
  display: -webkit-box;
  margin-top: 7px;
  overflow: hidden;
  color: var(--muted);
  font-size: 9.5px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.focus-sheet,
.flow-sheet,
.connection-note {
  margin-top: 14px;
  padding: 16px 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: #fcf8f7;
}

.focus-sheet {
  display: grid;
  grid-template-columns: minmax(180px, 0.8fr) minmax(260px, 1.4fr);
  gap: 22px;
}

.focus-copy > span {
  color: var(--sage);
  font-size: 9px;
}

.focus-copy h3,
.flow-copy h3 {
  margin-top: 3px;
  font-size: 17px;
}

.focus-copy p,
.flow-copy p,
.connection-note > p {
  margin-top: 7px;
  color: #7f6a68;
  font-size: 11px;
  line-height: 1.7;
}

.focus-rules > strong,
.flow-details > strong,
.connection-note > strong {
  color: #80656a;
  font-size: 10px;
}

.focus-rules ul,
.flow-details ul {
  margin: 7px 0 0 16px;
  color: #776260;
  font-size: 10px;
  line-height: 1.7;
}

.evidence-fold {
  grid-column: 1 / -1;
}

.evidence-fold,
.bridge-fold,
.document-fold {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}

.bridge-fold,
.document-fold {
  margin-top: 14px;
}

.evidence-fold summary,
.bridge-fold summary,
.document-fold summary {
  padding: 10px 12px;
  color: #90787a;
  cursor: pointer;
  font-size: 10px;
}

.evidence-tags,
.zone-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 0 12px 12px;
}

.evidence-tags span,
.evidence-tags code,
.zone-chips span {
  padding: 4px 7px;
  border-radius: 4px;
  background: var(--rose-soft);
  color: #8a6570;
  font-family: inherit;
  font-size: 9px;
}

.evidence-tags code {
  background: #f3f1ef;
  color: #817675;
}

.zone-index {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin-top: 14px;
  padding: 1px;
  background: var(--line);
}

.zone-index button {
  min-width: 0;
  padding: 11px 12px;
  border: 0;
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
}

.zone-index button:hover,
.zone-index button:focus-visible,
.zone-index button.active {
  position: relative;
  z-index: 1;
  outline: 1px solid #cfa0ad;
  background: #fff8fa;
}

.zone-index span,
.zone-index strong {
  display: block;
}

.zone-index span {
  color: var(--rose);
  font-size: 8.5px;
}

.zone-index strong {
  margin-top: 2px;
  font-size: 11px;
}

.zone-index p {
  margin-top: 5px;
  color: var(--muted);
  font-size: 9.5px;
  line-height: 1.55;
}

.zone-sheet {
  display: grid;
  grid-template-columns: minmax(180px, 0.8fr) minmax(260px, 1.2fr);
  gap: 18px;
  margin-top: 14px;
  padding: 16px 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: #fcf8f7;
}

.zone-sheet > div:first-child > span,
.zone-components > span {
  display: block;
  color: var(--rose);
  font-size: 9px;
}

.zone-sheet h3 {
  margin-top: 3px;
  font-size: 17px;
}

.zone-sheet p {
  margin-top: 7px;
  color: #7f6a68;
  font-size: 11px;
  line-height: 1.7;
}

.zone-sheet > div:nth-child(2) > strong {
  color: #80656a;
  font-size: 10px;
}

.zone-sheet ul {
  margin: 7px 0 0 16px;
  color: #776260;
  font-size: 10px;
  line-height: 1.7;
}

.zone-components {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.zone-components > span {
  margin-right: 4px;
}

.zone-components button {
  padding: 4px 7px;
  border: 0;
  border-radius: 4px;
  background: var(--rose-soft);
  color: #8a6570;
  cursor: pointer;
  font-family: inherit;
  font-size: 9px;
}

.overview-bridges {
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
}

.flow-track {
  display: flex;
  align-items: stretch;
  padding: 18px 12px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: #fffdfb;
}

.flow-stop {
  position: relative;
  flex: 0 0 122px;
  min-height: 74px;
  padding: 11px 10px;
  border: 1px solid #e6d8d7;
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
}

.flow-stop + .flow-stop {
  margin-left: 24px;
}

.flow-stop + .flow-stop::before {
  position: absolute;
  top: 50%;
  left: -25px;
  width: 24px;
  height: 1px;
  background: #d7b7bf;
  content: '';
}

.flow-stop + .flow-stop::after {
  position: absolute;
  top: calc(50% - 3px);
  left: -6px;
  width: 6px;
  height: 6px;
  border-top: 1px solid #b98c98;
  border-right: 1px solid #b98c98;
  content: '';
  transform: rotate(45deg);
}

.flow-stop.active {
  border-color: #c995a4;
  background: var(--rose-soft);
  box-shadow: 0 5px 14px rgb(102 64 74 / 8%);
}

.flow-stop span,
.flow-stop strong {
  display: block;
}

.flow-stop span {
  color: var(--rose);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 9px;
}

.flow-stop strong {
  margin-top: 8px;
  overflow-wrap: anywhere;
  font-size: 10.5px;
  line-height: 1.5;
}

.flow-sheet {
  display: grid;
  grid-template-columns: 64px minmax(200px, 0.8fr) minmax(240px, 1fr);
  align-items: center;
  gap: 18px;
}

.flow-number {
  color: #d5b4bd;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 38px;
}

.zone-chips {
  margin-top: 9px;
  padding: 0;
}

.connection-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.connection-heading strong {
  display: block;
  margin-top: 3px;
  font-size: 16px;
}

.component-select {
  width: 190px;
}

.connection-board {
  display: grid;
  grid-template-columns: minmax(180px, 0.75fr) 74px minmax(260px, 1.25fr);
  align-items: center;
  min-height: 310px;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background:
    linear-gradient(90deg, rgb(185 126 145 / 5%) 1px, transparent 1px) 0 0 / 28px 28px,
    linear-gradient(rgb(185 126 145 / 5%) 1px, transparent 1px) 0 0 / 28px 28px,
    #fffdfb;
}

.connection-source,
.neighbor-node {
  position: relative;
  z-index: 1;
  padding: 15px;
  border: 1px solid #cf9faf;
  border-radius: 7px;
  background: #fff;
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  box-shadow: 0 7px 20px rgb(89 53 63 / 9%);
}

.connection-source {
  min-height: 150px;
  background: linear-gradient(145deg, #fff, #faeef1);
}

.connection-source span,
.connection-source strong,
.connection-source small,
.neighbor-node span,
.neighbor-node strong,
.neighbor-node small {
  display: block;
}

.connection-source span,
.neighbor-node span {
  color: var(--rose);
  font-size: 9px;
}

.connection-source strong {
  margin-top: 13px;
  font-size: 19px;
}

.connection-source small {
  margin-top: 8px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.6;
}

.connection-trunk {
  position: relative;
  height: calc(100% - 70px);
  border-right: 1px solid #d5acb7;
}

.connection-trunk::before {
  position: absolute;
  top: 50%;
  right: 0;
  width: 74px;
  height: 1px;
  background: #d5acb7;
  content: '';
}

.neighbor-list {
  display: grid;
  gap: 8px;
}

.neighbor-node {
  min-height: 62px;
  border-color: #e5d6d8;
  box-shadow: 0 4px 12px rgb(89 53 63 / 6%);
}

.neighbor-node::before {
  position: absolute;
  top: 50%;
  left: -75px;
  width: 74px;
  height: 1px;
  background: #d5acb7;
  content: '';
}

.neighbor-node:hover,
.neighbor-node:focus-visible {
  border-color: #c995a4;
  outline: none;
}

.neighbor-node strong {
  margin-top: 3px;
  font-size: 12px;
}

.neighbor-node small {
  margin-top: 4px;
  overflow-wrap: anywhere;
  color: var(--muted);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 8.5px;
}

.no-neighbor {
  grid-column: 2 / -1;
  color: var(--muted);
  font-size: 11px;
}

.connection-note ul {
  display: grid;
  gap: 6px;
  margin-top: 10px;
  list-style: none;
}

.connection-note li {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  color: var(--muted);
  font-size: 9.5px;
  line-height: 1.55;
}

.connection-note li button {
  border: 0;
  background: transparent;
  color: #8e6270;
  cursor: pointer;
  font-family: inherit;
  font-size: 10px;
  text-align: left;
}

.bridge-table {
  display: grid;
  gap: 1px;
  padding: 1px;
  background: var(--line);
}

.bridge-row {
  display: grid;
  grid-template-columns: 150px 1fr 1.3fr;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  background: #fff;
  font-size: 9.5px;
}

.bridge-row code {
  overflow-wrap: anywhere;
  color: #8e6270;
}

.bridge-row strong {
  font-size: 9.5px;
}

.bridge-row span {
  color: var(--muted);
  line-height: 1.5;
}

.review-banner {
  min-width: 0;
}

.review-banner strong,
.review-banner p {
  display: block;
}

.review-banner strong {
  font-size: 12px;
}

.review-banner p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 9.5px;
}

.pending-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.pending-list article {
  padding: 12px 14px;
  border-left: 3px solid #c28c60;
  border-radius: 4px;
  background: #fff8ef;
}

.pending-list span,
.pending-list strong {
  display: block;
}

.pending-list span {
  color: #b27a4d;
  font-size: 8.5px;
}

.pending-list strong {
  margin-top: 3px;
  font-size: 11px;
}

.pending-list p {
  margin-top: 5px;
  color: var(--muted);
  font-size: 9.5px;
  line-height: 1.55;
}

.change-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(260px, 0.8fr);
  gap: 24px;
  margin-top: 18px;
}

.section-label {
  margin-bottom: 10px;
}

.change-timeline {
  border-left: 1px solid #d8b7c0;
}

.change-timeline article {
  position: relative;
  padding: 0 0 17px 17px;
}

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
.change-timeline p {
  display: block;
}

.change-timeline time {
  color: var(--muted);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 8.5px;
}

.change-timeline strong {
  margin-top: 3px;
  font-size: 10.5px;
}

.change-timeline p {
  margin-top: 4px;
  color: #8f7775;
  font-size: 9.5px;
  line-height: 1.55;
}

.review-list {
  display: grid;
  gap: 6px;
}

.review-list article {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: #fff;
}

.review-list article > span {
  flex: 0 0 7px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--sage);
}

.review-list article > span.review_required { background: #c28c60; }
.review-list article > span.error { background: #b85f64; }

.review-list strong,
.review-list small {
  display: block;
}

.review-list strong {
  font-size: 10px;
}

.review-list small {
  margin-top: 2px;
  color: var(--muted);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 8.5px;
}

.empty-note {
  color: var(--muted);
  font-size: 10px;
}

.document-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  padding: 1px;
  background: var(--line);
}

.document-list article {
  min-width: 0;
  padding: 10px 12px;
  background: #fff;
}

.document-list code {
  overflow-wrap: anywhere;
  color: #8e6270;
  font-size: 9px;
}

.document-list p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 9px;
  line-height: 1.5;
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
  .atlas-head {
    align-items: flex-start;
  }

  .atlas-head > div:first-child > strong {
    font-size: 17px;
  }

  .atlas-head p {
    max-width: 210px;
  }

  .atlas-state {
    min-width: 0;
    padding: 8px;
  }

  .atlas-state small {
    display: none;
  }

  .atlas-tabs {
    overflow-x: auto;
  }

  .atlas-tabs button {
    min-width: 76px;
    padding: 0 6px;
  }

  .overview-gates,
  .overview-rest {
    grid-template-columns: 1fr;
  }

  .overview-gates button {
    min-height: 88px;
  }

  .overview-rest > div + div {
    border-top: 1px solid var(--line);
    border-left: 0;
  }

  .component-map,
  .zone-index,
  .document-list,
  .pending-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .component-tile {
    min-height: 112px;
  }

  .focus-sheet,
  .zone-sheet,
  .flow-sheet,
  .change-columns {
    grid-template-columns: 1fr;
  }

  .flow-track {
    display: grid;
    overflow: visible;
  }

  .flow-stop {
    width: 100%;
    min-height: 58px;
  }

  .flow-stop + .flow-stop {
    margin-top: 20px;
    margin-left: 0;
  }

  .flow-stop + .flow-stop::before {
    top: -21px;
    left: 24px;
    width: 1px;
    height: 20px;
  }

  .flow-stop + .flow-stop::after {
    top: -7px;
    left: 21px;
    transform: rotate(135deg);
  }

  .flow-number {
    display: none;
  }

  .connection-heading {
    align-items: flex-end;
  }

  .component-select {
    width: 150px;
  }

  .connection-board {
    grid-template-columns: 1fr;
    gap: 24px;
    min-height: 0;
    padding: 14px;
  }

  .connection-source {
    min-height: 110px;
  }

  .connection-trunk {
    display: none;
  }

  .neighbor-node::before {
    top: -25px;
    left: 24px;
    width: 1px;
    height: 24px;
  }

  .neighbor-node + .neighbor-node::after {
    position: absolute;
    top: -9px;
    left: 21px;
    width: 6px;
    height: 6px;
    border-right: 1px solid #d5acb7;
    border-bottom: 1px solid #d5acb7;
    content: '';
    transform: rotate(45deg);
  }

  .connection-note li {
    grid-template-columns: 78px minmax(0, 1fr);
  }

  .bridge-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .atlas-foot {
    display: grid;
    gap: 4px;
  }
}
</style>
