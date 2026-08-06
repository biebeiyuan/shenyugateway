<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ProjectMapDelivery, ProjectMapSnapshot } from '@/api/books'

const props = defineProps<{ snapshot: ProjectMapSnapshot }>()
const selectedProduct = ref('all')

const products = computed(() => (
  [...new Set(props.snapshot.deliveries.map(item => item.product))]
))

const visibleDeliveries = computed(() => (
  selectedProduct.value === 'all'
    ? props.snapshot.deliveries
    : props.snapshot.deliveries.filter(item => item.product === selectedProduct.value)
))

const groupedDeliveries = computed(() => {
  const groups: Array<{ day: string; items: ProjectMapDelivery[] }> = []
  for (const delivery of visibleDeliveries.value) {
    const day = delivery.completed_at.slice(0, 10)
    const current = groups[groups.length - 1]
    if (current?.day === day) current.items.push(delivery)
    else groups.push({ day, items: [delivery] })
  }
  return groups
})

const statusLabels: Record<ProjectMapDelivery['status'], string> = {
  verified_local: '本地已验证',
  pushed: '已推送',
  deployed: '已部署',
  device_verified: '设备已实测',
}

const kindLabels: Record<ProjectMapDelivery['kind'], string> = {
  feature: '功能',
  fix: '修复',
  experience: '体验',
  operations: '工作流',
  architecture: '架构',
}

function dayLabel(value: string): string {
  const [, month, day] = value.split('-')
  return `${Number(month)}月${Number(day)}日`
}

function zoneTitle(id: string): string {
  return props.snapshot.zones.find(zone => zone.id === id)?.title || id
}
</script>

<template>
  <section class="delivery-page" data-testid="project-map-deliveries">
    <header class="delivery-head">
      <div>
        <span>近期施工簿</span>
        <strong>{{ props.snapshot.summary.delivery_count }} 项完整成果</strong>
        <p>覆盖 {{ props.snapshot.summary.delivery_product_count }} 个产品入口</p>
      </div>
      <div class="delivery-status-key" aria-label="交付状态层级">
        <span>本地验证</span><i></i><span>推送</span><i></i><span>部署</span><i></i><span>设备实测</span>
      </div>
    </header>

    <nav class="delivery-filters" aria-label="按产品筛选施工记录">
      <button type="button" :class="{ active: selectedProduct === 'all' }" @click="selectedProduct = 'all'">
        全部
      </button>
      <button
        v-for="product in products"
        :key="product"
        type="button"
        :class="{ active: selectedProduct === product }"
        @click="selectedProduct = product"
      >
        {{ product }}
      </button>
    </nav>

    <div class="delivery-timeline">
      <section v-for="group in groupedDeliveries" :key="group.day" class="delivery-day">
        <time :datetime="group.day">{{ dayLabel(group.day) }}</time>
        <div class="delivery-day-entries">
          <details v-for="delivery in group.items" :key="delivery.id" class="delivery-entry">
            <summary>
              <span class="delivery-kind">{{ kindLabels[delivery.kind] }}</span>
              <span class="delivery-title">
                <strong>{{ delivery.title }}</strong>
                <small>{{ delivery.product }} · {{ delivery.touchpoint }}</small>
              </span>
              <span class="delivery-state" :class="delivery.status">{{ statusLabels[delivery.status] }}</span>
              <span class="delivery-toggle" aria-hidden="true"></span>
            </summary>

            <div class="delivery-body">
              <div class="delivery-outcome">
                <span>做成了什么</span>
                <p>{{ delivery.summary }}</p>
              </div>
              <div>
                <span>为什么做</span>
                <p>{{ delivery.why }}</p>
              </div>
              <div>
                <span>怎样确认</span>
                <ul>
                  <li v-for="item in delivery.verification" :key="item">{{ item }}</li>
                </ul>
              </div>
              <div class="delivery-map">
                <span>地图落点</span>
                <div class="delivery-tags">
                  <b>{{ delivery.product }}</b>
                  <b v-for="zoneId in delivery.zone_ids" :key="zoneId">{{ zoneTitle(zoneId) }}</b>
                  <code v-for="path in delivery.paths" :key="path" :title="path">{{ path }}</code>
                  <code v-for="doc in delivery.docs" :key="doc" :title="doc">{{ doc }}</code>
                </div>
              </div>
              <blockquote v-if="delivery.lesson">
                <span>留下的经验</span>
                <p>{{ delivery.lesson }}</p>
              </blockquote>
              <div v-if="delivery.debug_ref" class="delivery-debug">
                <span>Debug 记录</span>
                <code>{{ delivery.debug_ref }}</code>
              </div>
              <footer>
                <code v-if="delivery.commit">{{ delivery.commit.slice(0, 9) }}</code>
                <span v-if="delivery.recorded_by">记录：{{ delivery.recorded_by }}</span>
              </footer>
            </div>
          </details>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.delivery-page { min-width: 0; }
.delivery-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 22px; padding: 4px 2px 15px; border-bottom: 1px solid var(--line); }
.delivery-head > div:first-child span,
.delivery-head > div:first-child strong,
.delivery-head > div:first-child p { display: block; }
.delivery-head > div:first-child span { color: var(--rose); font-size: 9px; }
.delivery-head > div:first-child strong { margin-top: 4px; font-size: 17px; }
.delivery-head > div:first-child p { margin-top: 4px; color: var(--muted); font-size: 9.5px; }
.delivery-status-key { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 8px; white-space: nowrap; }
.delivery-status-key i { width: 14px; height: 1px; background: #d8b7c0; }
.delivery-filters { display: flex; gap: 4px; padding: 12px 0 10px; overflow-x: auto; }
.delivery-filters button { flex: none; padding: 6px 9px; border: 1px solid var(--line); border-radius: 5px; background: var(--sy-paper, #fff); color: var(--muted); font-family: inherit; font-size: 9px; }
.delivery-filters button.active { border-color: #c995a4; background: var(--rose-soft); color: #7f5d67; }
.delivery-timeline { display: grid; gap: 15px; padding-top: 4px; }
.delivery-day { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 12px; }
.delivery-day > time { padding-top: 12px; color: var(--rose); font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 9px; }
.delivery-day-entries { display: grid; gap: 7px; border-left: 1px solid #d8b7c0; padding-left: 14px; }
.delivery-entry { position: relative; border: 1px solid var(--line); border-radius: 7px; background: var(--sy-paper, #fff); }
.delivery-entry::before { position: absolute; top: 18px; left: -19px; width: 7px; height: 7px; border: 2px solid var(--sy-paper, #fff); border-radius: 50%; background: var(--rose); box-shadow: 0 0 0 1px #d8b7c0; content: ''; }
.delivery-entry summary { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto 16px; gap: 10px; align-items: center; padding: 11px 12px; cursor: pointer; list-style: none; }
.delivery-entry summary::-webkit-details-marker { display: none; }
.delivery-kind { color: var(--rose); font-size: 9px; }
.delivery-title { min-width: 0; }
.delivery-title strong,
.delivery-title small { display: block; }
.delivery-title strong { font-size: 11px; }
.delivery-title small { margin-top: 3px; overflow: hidden; color: var(--muted); font-size: 8.5px; text-overflow: ellipsis; white-space: nowrap; }
.delivery-state { padding: 4px 6px; border-radius: 4px; background: #f3eeea; color: #8b7770; font-size: 8px; white-space: nowrap; }
.delivery-state.pushed { background: #eef1f5; color: #6c7683; }
.delivery-state.deployed { background: var(--sage-soft); color: #607869; }
.delivery-state.device_verified { background: #e6f1e9; color: #4d705a; }
.delivery-toggle { width: 7px; height: 7px; border-right: 1px solid var(--muted); border-bottom: 1px solid var(--muted); transform: rotate(45deg); transition: transform 150ms ease; }
.delivery-entry[open] .delivery-toggle { transform: rotate(225deg); }
.delivery-entry[open] { border-color: #d8b7c0; }
.delivery-entry[open] summary { border-bottom: 1px solid var(--line); background: #fffafb; }
.delivery-body { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px 18px; padding: 14px; }
.delivery-body > div > span,
.delivery-body blockquote > span { display: block; color: var(--rose); font-size: 8.5px; }
.delivery-body p,
.delivery-body ul { margin-top: 5px; color: #7f6a68; font-size: 9.5px; line-height: 1.65; }
.delivery-body ul { padding-left: 15px; }
.delivery-outcome { grid-column: 1 / -1; }
.delivery-map { grid-column: 1 / -1; }
.delivery-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.delivery-tags b,
.delivery-tags code { max-width: 100%; padding: 4px 6px; overflow: hidden; border-radius: 4px; background: var(--rose-soft); color: #80606a; font-size: 8px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.delivery-tags code { background: #f4f1ef; color: #786d69; }
.delivery-body blockquote { grid-column: 1 / -1; margin: 0; padding: 10px 12px; border-left: 2px solid var(--sage); background: var(--sage-soft); }
.delivery-body blockquote p { color: #607267; }
.delivery-debug { grid-column: 1 / -1; }
.delivery-debug code { display: block; margin-top: 5px; color: #7b6870; font-size: 8.5px; overflow-wrap: anywhere; }
.delivery-body footer { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 10px; color: var(--muted); font-size: 8px; }
.delivery-body footer code { color: #876d75; }

@media (max-width: 760px) {
  .delivery-head { align-items: flex-start; flex-direction: column; gap: 10px; }
  .delivery-head > div:first-child span { font-size: 10px; }
  .delivery-head > div:first-child strong { font-size: 19px; }
  .delivery-head > div:first-child p,
  .delivery-status-key { font-size: 9px; }
  .delivery-status-key { width: 100%; overflow-x: auto; }
  .delivery-filters button { font-size: 10px; }
  .delivery-day { grid-template-columns: 1fr; gap: 6px; }
  .delivery-day > time { padding: 0; font-size: 10px; }
  .delivery-day-entries { margin-left: 3px; }
  .delivery-entry summary { grid-template-columns: 38px minmax(0, 1fr) 16px; }
  .delivery-kind { font-size: 10px; }
  .delivery-title strong { font-size: 12px; }
  .delivery-title small { font-size: 9.5px; }
  .delivery-state { font-size: 9px; }
  .delivery-state { grid-column: 2; justify-self: start; }
  .delivery-toggle { grid-column: 3; grid-row: 1; }
  .delivery-body { grid-template-columns: 1fr; }
  .delivery-body > * { grid-column: 1 !important; }
  .delivery-body > div > span,
  .delivery-body blockquote > span { font-size: 9.5px; }
  .delivery-body p,
  .delivery-body ul { font-size: 11px; }
  .delivery-tags b,
  .delivery-tags code { font-size: 9px; }
  .delivery-body footer { font-size: 9px; }
}
</style>
