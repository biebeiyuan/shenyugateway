<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ProjectMapFlowStage, ProjectMapSnapshot } from '@/api/books'

const props = defineProps<{ snapshot: ProjectMapSnapshot }>()
const selectedFlowId = ref(props.snapshot.request_flow[0]?.id || '')

const selectedFlow = computed<ProjectMapFlowStage | null>(() => (
  props.snapshot.request_flow.find(item => item.id === selectedFlowId.value) || null
))
</script>

<template>
  <section class="flow-page">
    <div class="flow-track" data-testid="project-map-flow">
      <button
        v-for="(stage, index) in props.snapshot.request_flow"
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
        {{ String(props.snapshot.request_flow.findIndex(item => item.id === selectedFlowId) + 1).padStart(2, '0') }}
      </div>
      <div class="flow-copy">
        <span>这一站</span>
        <h3>{{ selectedFlow.label }}</h3>
        <p>{{ selectedFlow.meaning }}</p>
        <div v-if="selectedFlow.zone_ids.length" class="zone-chips">
          <span v-for="zoneId in selectedFlow.zone_ids" :key="zoneId">
            {{ props.snapshot.zones.find(zone => zone.id === zoneId)?.title }}
          </span>
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
</template>

<style scoped>
.flow-track {
  display: flex;
  align-items: stretch;
  padding: 18px 12px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--sy-paper, #fff);
}

.flow-stop {
  position: relative;
  flex: 0 0 122px;
  min-height: 74px;
  padding: 11px 10px;
  border: 1px solid #e6d8d7;
  border-radius: 6px;
  background: var(--sy-paper, #fff);
  color: var(--ink);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
}

.flow-stop + .flow-stop { margin-left: 24px; }

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

.flow-stop.active { border-color: #c995a4; background: var(--rose-soft); box-shadow: 0 5px 14px rgb(102 64 74 / 8%); }
.flow-stop span,
.flow-stop strong { display: block; }
.flow-stop span { color: var(--rose); font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 9px; }
.flow-stop strong { margin-top: 8px; overflow-wrap: anywhere; font-size: 10.5px; line-height: 1.5; }

.flow-sheet {
  display: grid;
  grid-template-columns: 64px minmax(200px, 0.8fr) minmax(240px, 1fr);
  align-items: center;
  gap: 18px;
  margin-top: 14px;
  padding: 16px 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--sy-paper, #fff);
}

.flow-number { color: #d5b4bd; font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 38px; }
.flow-copy > span { display: block; color: var(--rose); font-size: 10px; }
.flow-copy h3 { margin-top: 3px; font-size: 17px; }
.flow-copy p { margin-top: 7px; color: #7f6a68; font-size: 11px; line-height: 1.7; }
.flow-details > strong { color: #80656a; font-size: 10px; }
.flow-details ul { margin: 7px 0 0 16px; color: #776260; font-size: 10px; line-height: 1.7; }
.zone-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.zone-chips span { padding: 4px 7px; border-radius: 4px; background: var(--rose-soft); color: #8a6570; font-size: 9px; }

@media (max-width: 760px) {
  .flow-track { display: grid; overflow: visible; }
  .flow-stop { width: 100%; min-height: 58px; }
  .flow-stop + .flow-stop { margin-top: 20px; margin-left: 0; }
  .flow-stop + .flow-stop::before { top: -21px; left: 24px; width: 1px; height: 20px; }
  .flow-stop + .flow-stop::after { top: -7px; left: 21px; transform: rotate(135deg); }
  .flow-sheet { grid-template-columns: 1fr; }
  .flow-number { display: none; }
}
</style>
