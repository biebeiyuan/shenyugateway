<script setup lang="ts">
import { computed, ref } from 'vue'
import { NSelect } from 'naive-ui'
import type { ProjectMapComponent, ProjectMapSnapshot } from '@/api/books'

const props = defineProps<{ snapshot: ProjectMapSnapshot }>()
const selectedComponentId = ref(props.snapshot.components[0]?.id || '')

const selectedComponent = computed<ProjectMapComponent | null>(() => (
  props.snapshot.components.find(item => item.id === selectedComponentId.value) || null
))

const componentOptions = computed(() => (
  props.snapshot.components.map(item => ({ label: item.title, value: item.id }))
))

const selectedConnections = computed(() => {
  if (!selectedComponent.value) return []
  return props.snapshot.component_bridges
    .filter(item => item.left_id === selectedComponent.value?.id || item.right_id === selectedComponent.value?.id)
    .map((connection) => {
      const neighborId = connection.left_id === selectedComponent.value?.id
        ? connection.right_id
        : connection.left_id
      return {
        ...connection,
        neighbor: props.snapshot.components.find(item => item.id === neighborId) || null,
      }
    })
    .filter(item => item.neighbor)
})

function statusText(status: ProjectMapComponent['status']): string {
  if (status === 'ok') return '已确认'
  if (status === 'error') return '映射中断'
  return '待复核'
}

function shortPath(value: string): string {
  const parts = value.split('/')
  return parts.length > 2 ? `${parts[0]}/…/${parts[parts.length - 1]}` : value
}
</script>

<template>
  <section class="connections-page">
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
        <div v-for="bridge in props.snapshot.bridges" :key="bridge['桥梁']" class="bridge-row">
          <code>{{ bridge['桥梁'] }}</code>
          <strong>{{ bridge['连接区域'] }}</strong>
          <span>{{ bridge['审计重点'] }}</span>
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.connection-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.connection-heading span { display: block; color: var(--rose); font-size: 10px; }
.connection-heading strong { display: block; margin-top: 3px; font-size: 16px; }
.component-select { width: 190px; }

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
    var(--sy-paper, #fff);
}

.connection-source,
.neighbor-node {
  position: relative;
  z-index: 1;
  padding: 15px;
  border: 1px solid #cf9faf;
  border-radius: 7px;
  background: var(--sy-paper, #fff);
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  box-shadow: 0 7px 20px rgb(89 53 63 / 9%);
}

.connection-source { min-height: 150px; background: linear-gradient(145deg, #fff, #faeef1); }
.connection-source span,
.connection-source strong,
.connection-source small,
.neighbor-node span,
.neighbor-node strong,
.neighbor-node small { display: block; }
.connection-source span,
.neighbor-node span { color: var(--rose); font-size: 9px; }
.connection-source strong { margin-top: 13px; font-size: 19px; }
.connection-source small { margin-top: 8px; color: var(--muted); font-size: 10px; line-height: 1.6; }

.connection-trunk { position: relative; height: calc(100% - 70px); border-right: 1px solid var(--sy-accent); }
.connection-trunk::before { position: absolute; top: 50%; right: 0; width: 74px; height: 1px; background: var(--sy-accent); content: ''; }
.neighbor-list { display: grid; gap: 8px; }
.neighbor-node { min-height: 62px; border-color: #e5d6d8; box-shadow: 0 4px 12px rgb(89 53 63 / 6%); }
.neighbor-node::before { position: absolute; top: 50%; left: -75px; width: 74px; height: 1px; background: var(--sy-accent); content: ''; }
.neighbor-node:hover,
.neighbor-node:focus-visible { border-color: #c995a4; outline: none; }
.neighbor-node strong { margin-top: 3px; font-size: 12px; }

.neighbor-node small {
  margin-top: 4px;
  overflow-wrap: anywhere;
  color: var(--muted);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 8.5px;
}

.no-neighbor { grid-column: 2 / -1; color: var(--muted); font-size: 11px; }

.connection-note {
  margin-top: 14px;
  padding: 16px 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--sy-paper, #fff);
}

.connection-note > strong { color: #80656a; font-size: 10px; }
.connection-note > p { margin-top: 7px; color: #7f6a68; font-size: 11px; line-height: 1.7; }
.connection-note ul { display: grid; gap: 6px; margin-top: 10px; list-style: none; }

.connection-note li {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  color: var(--muted);
  font-size: 9.5px;
  line-height: 1.55;
}

.connection-note li button { border: 0; background: transparent; color: #8e6270; cursor: pointer; font-family: inherit; font-size: 10px; text-align: left; }
.bridge-fold { margin-top: 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--sy-paper, #fff); }
.bridge-fold summary { padding: 10px 12px; color: #90787a; cursor: pointer; font-size: 10px; }
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
  .connection-heading { align-items: flex-end; }
  .component-select { width: 150px; }
  .connection-board { grid-template-columns: 1fr; gap: 24px; min-height: 0; padding: 14px; }
  .connection-source { min-height: 110px; }
  .connection-trunk { display: none; }
  .neighbor-node::before { top: -25px; left: 24px; width: 1px; height: 24px; }

  .neighbor-node + .neighbor-node::after {
    position: absolute;
    top: -9px;
    left: 21px;
    width: 6px;
    height: 6px;
    border-right: 1px solid var(--sy-accent);
    border-bottom: 1px solid var(--sy-accent);
    content: '';
    transform: rotate(45deg);
  }

  .connection-note li { grid-template-columns: 78px minmax(0, 1fr); }
  .bridge-row { grid-template-columns: 1fr; gap: 4px; }
}
</style>
