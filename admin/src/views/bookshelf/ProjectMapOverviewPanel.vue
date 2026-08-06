<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ProjectMapComponent, ProjectMapSnapshot, ProjectMapZone } from '@/api/books'

const props = defineProps<{ snapshot: ProjectMapSnapshot }>()
const emit = defineEmits<{ 'open-deliveries': [] }>()

type OverviewFocus = 'components' | 'zones' | 'bridges'

const overviewFocus = ref<OverviewFocus | null>(null)
const selectedComponentId = ref(props.snapshot.components[0]?.id || '')
const selectedZoneId = ref(props.snapshot.zones[0]?.id || '')

const selectedComponent = computed<ProjectMapComponent | null>(() => (
  props.snapshot.components.find(item => item.id === selectedComponentId.value) || null
))

const selectedZone = computed<ProjectMapZone | null>(() => (
  props.snapshot.zones.find(item => item.id === selectedZoneId.value) || null
))

const latestDelivery = computed(() => props.snapshot.deliveries[0] || null)

function zoneFor(id: string): ProjectMapZone | undefined {
  return props.snapshot.zones.find(zone => zone.id === id)
}

function componentFor(id: string): ProjectMapComponent | undefined {
  return props.snapshot.components.find(component => component.id === id)
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
  <section class="overview-page">
    <div class="overview-gates">
      <button
        type="button"
        :class="{ active: overviewFocus === 'components' }"
        data-testid="project-map-overview-components"
        @click="toggleOverview('components')"
      >
        <span>生活这一侧</span>
        <strong>家里的机制</strong>
        <b>{{ props.snapshot.summary.component_count }}</b>
        <small>{{ props.snapshot.summary.confirmed_count }} 处已与现场对上</small>
      </button>
      <button
        type="button"
        :class="{ active: overviewFocus === 'zones' }"
        data-testid="project-map-overview-zones"
        @click="toggleOverview('zones')"
      >
        <span>Agent 找路这一侧</span>
        <strong>架构分区</strong>
        <b>{{ props.snapshot.summary.zone_count }}</b>
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
        <b>{{ props.snapshot.summary.bridge_count }}</b>
        <small>跨区时必须共同确认的地方</small>
      </button>
    </div>

    <div v-if="!overviewFocus" class="overview-rest">
      <div>
        <span>当前版本</span>
        <strong>{{ props.snapshot.live.commit.slice(0, 12) }}</strong>
      </div>
      <div>
        <span>机制最近确认</span>
        <strong>{{ fmtDateTime(props.snapshot.live.last_confirmed_at) || '尚未确认' }}</strong>
      </div>
      <div>
        <span>机制状态</span>
        <strong>
          {{ props.snapshot.summary.pending_count
            ? `${props.snapshot.summary.pending_count} 处待复核`
            : '生活机制已对上' }}
        </strong>
      </div>
    </div>

    <button
      v-if="!overviewFocus && latestDelivery"
      type="button"
      class="delivery-peek"
      data-testid="project-map-delivery-peek"
      @click="emit('open-deliveries')"
    >
      <span>
        <small>近期完成</small>
        <strong>{{ latestDelivery.title }}</strong>
      </span>
      <span>
        <b>{{ props.snapshot.summary.delivery_count }} 项</b>
        <small>{{ props.snapshot.summary.delivery_product_count }} 个产品入口</small>
      </span>
    </button>

    <template v-if="overviewFocus === 'components'">
      <div class="component-map" aria-label="家的核心机制">
        <button
          v-for="component in props.snapshot.components"
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
          v-for="zone in props.snapshot.zones"
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
        <div v-for="bridge in props.snapshot.bridges" :key="bridge['桥梁']" class="bridge-row">
          <code>{{ bridge['桥梁'] }}</code>
          <strong>{{ bridge['连接区域'] }}</strong>
          <span>{{ bridge['审计重点'] }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.overview-gates {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}

.delivery-peek { display: flex; align-items: center; justify-content: space-between; gap: 20px; width: 100%; margin-top: 10px; padding: 11px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--sy-paper, #fff); color: var(--ink); font-family: inherit; text-align: left; }
.delivery-peek:hover,
.delivery-peek:focus-visible { border-color: #cc9aaa; outline: none; background: #fffafb; }
.delivery-peek > span { min-width: 0; }
.delivery-peek > span:last-child { flex: none; text-align: right; }
.delivery-peek small,
.delivery-peek strong,
.delivery-peek b { display: block; }
.delivery-peek small { color: var(--muted); font-size: 8.5px; }
.delivery-peek strong { margin-top: 3px; overflow: hidden; font-size: 10.5px; text-overflow: ellipsis; white-space: nowrap; }
.delivery-peek b { color: var(--rose); font-size: 11px; }

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
.overview-gates small,
.overview-rest span,
.overview-rest strong,
.component-tile strong,
.component-tile small,
.zone-index span,
.zone-index strong {
  display: block;
}

.overview-gates span { color: var(--rose); font-size: 9px; }
.overview-gates strong { margin-top: 7px; font-size: 14px; }
.overview-gates small { margin-top: 9px; color: var(--muted); font-size: 9px; line-height: 1.5; }

.overview-gates b {
  position: absolute;
  top: 14px;
  right: 15px;
  color: #c5a2ab;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 25px;
  font-weight: 500;
}

.overview-rest {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 14px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--sy-paper, #fff);
}

.overview-rest > div { min-width: 0; padding: 13px 15px; }
.overview-rest > div + div { border-left: 1px solid var(--line); }
.overview-rest span { color: var(--muted); font-size: 8.5px; }

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
  background: var(--sy-paper, #fff);
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

.component-status { position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--sage); }
.component-tile.review_required .component-status { background: #c28c60; }
.component-tile.error .component-status { background: #b85f64; }
.component-tile strong { font-size: 13px; }

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
.zone-sheet {
  display: grid;
  grid-template-columns: minmax(180px, 0.8fr) minmax(260px, 1.4fr);
  gap: 22px;
  margin-top: 14px;
  padding: 16px 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--sy-paper, #fff);
}

.focus-copy > span,
.zone-sheet > div:first-child > span,
.zone-components > span { display: block; color: var(--sage); font-size: 9px; }

.focus-copy h3,
.zone-sheet h3 { margin-top: 3px; font-size: 17px; }

.focus-copy p,
.zone-sheet p { margin-top: 7px; color: #7f6a68; font-size: 11px; line-height: 1.7; }

.focus-rules > strong,
.zone-sheet > div:nth-child(2) > strong { color: #80656a; font-size: 10px; }

.focus-rules ul,
.zone-sheet ul { margin: 7px 0 0 16px; color: #776260; font-size: 10px; line-height: 1.7; }

.evidence-fold {
  grid-column: 1 / -1;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--sy-paper, #fff);
}

.evidence-fold summary { padding: 10px 12px; color: #90787a; cursor: pointer; font-size: 10px; }
.evidence-tags { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 12px 12px; }

.evidence-tags span,
.evidence-tags code,
.zone-components button {
  padding: 4px 7px;
  border: 0;
  border-radius: 4px;
  background: var(--rose-soft);
  color: #8a6570;
  font-family: inherit;
  font-size: 9px;
}

.evidence-tags code { background: #f3f1ef; color: #817675; }

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
  background: var(--sy-paper, #fff);
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
}

.zone-index button:hover,
.zone-index button:focus-visible,
.zone-index button.active { position: relative; z-index: 1; outline: 1px solid #cfa0ad; background: #fff8fa; }
.zone-index span { color: var(--rose); font-size: 8.5px; }
.zone-index strong { margin-top: 2px; font-size: 11px; }
.zone-index p { margin-top: 5px; color: var(--muted); font-size: 9.5px; line-height: 1.55; }

.zone-components {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.zone-components > span { margin-right: 4px; color: var(--rose); }
.zone-components button { cursor: pointer; }

.overview-bridges { margin-top: 14px; overflow: hidden; border: 1px solid var(--line); border-radius: 6px; }
.bridge-table { display: grid; gap: 1px; padding: 1px; background: var(--line); }

.bridge-row {
  display: grid;
  grid-template-columns: 150px 1fr 1.3fr;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  background: var(--sy-paper, #fff);
  font-size: 9.5px;
}

.bridge-row code { overflow-wrap: anywhere; color: #8e6270; }
.bridge-row strong { font-size: 9.5px; }
.bridge-row span { color: var(--muted); line-height: 1.5; }

@media (max-width: 760px) {
  .delivery-peek { align-items: flex-start; }
  .overview-gates,
  .overview-rest { grid-template-columns: 1fr; }
  .overview-gates button { min-height: 88px; }
  .overview-rest > div + div { border-top: 1px solid var(--line); border-left: 0; }
  .component-map,
  .zone-index { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .component-tile { min-height: 112px; }
  .focus-sheet,
  .zone-sheet { grid-template-columns: 1fr; }
  .bridge-row { grid-template-columns: 1fr; gap: 4px; }
}
</style>
