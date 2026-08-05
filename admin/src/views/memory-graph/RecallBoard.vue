<script setup lang="ts">
// 描金线索板 · 想起的一瞬间
//
// 空间骨架是侦探软木板（钉、连线、胶带），皮肤是 rose-gothic Mucha（古金
// 发丝线、宽字距眉题、老式数字）。一次「想起」把结果钉上板：中心是被想起
// 的词，三圈纸按与它的远近排开——脱口而出（金钉 + 实金线连到中心）、
// 由此及彼（细金线 + 路径牌）、浮想（胶带粘在板边，不连线）。
// 点一张纸，它从板上取下来放大读全文。

import { computed, ref } from 'vue'
import { NButton, NEmpty, NSelect, NSpin, NTag } from 'naive-ui'
import type { MemoryGraphRecallPreviewItem } from '@/api/memoryGraph'
import { paperFamily, sourceLabel } from './sourceDisplay'
import SyGlyph from './SyGlyph.vue'

interface PaperPosition {
  item: MemoryGraphRecallPreviewItem
  x: number
  y: number
  rotate: number
  group: 'direct' | 'related' | 'other'
}

const props = defineProps<{
  query: string
  items: MemoryGraphRecallPreviewItem[]
  loading: boolean
  error: string
  hasRun: boolean
  /** 当前词若是确认过的锚点，父级传入以便显示「管理这个名字」。 */
  manageAnchorName?: string
  /** 词命中高亮（父级算好 segment）。 */
  highlight: (item: MemoryGraphRecallPreviewItem) => { text: string; hit: boolean }[]
  sourceDate: (item: MemoryGraphRecallPreviewItem) => string
  /** 关联锚点编辑（保留现有手动确认入口）。 */
  anchorOptions: { label: string; value: string }[]
  manualAnchorIds: Record<string, string[]>
  sourceMentionsLoaded: Record<string, boolean>
  autoAnchorNames: (item: MemoryGraphRecallPreviewItem) => string[]
  savingKey: string
  runId: number
}>()

const emit = defineEmits<{
  (e: 'update:manualAnchorIds', value: Record<string, string[]>): void
  (e: 'save-anchors', item: MemoryGraphRecallPreviewItem): void
  (e: 'manage'): void
}>()

const BOARD_W = 960
const BOARD_H = 620
const CX = BOARD_W / 2
const CY = BOARD_H / 2

const flippedKey = ref<string | null>(null)

function sourceKey(item: Pick<MemoryGraphRecallPreviewItem, 'source_table' | 'source_id'>): string {
  return `${item.source_table} ${item.source_id}`
}

const groups = computed(() => ({
  direct: props.items.filter((item) => item.recall_match?.group === 'direct'),
  related: props.items.filter((item) => item.recall_match?.group === 'related'),
  other: props.items.filter((item) => item.recall_match?.group === 'other'),
}))

// 用 source key 做种子，同一次想起刷新不跳，换一批才换布局。
function seed(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0
  return h
}

function layoutRing(items: MemoryGraphRecallPreviewItem[], radius: number, startAngle: number, group: PaperPosition['group']): PaperPosition[] {
  const n = items.length
  if (!n) return []
  return items.map((item, i) => {
    const s = seed(sourceKey(item))
    const angle = startAngle + (i / n) * Math.PI * 2 + ((s % 40) - 20) * (Math.PI / 180)
    const r = radius + ((s >> 3) % 26) - 13
    const rotate = ((s >> 5) % 9) - 4
    return {
      item,
      group,
      x: CX + r * Math.cos(angle),
      y: CY + r * Math.sin(angle) * 0.78,
      rotate: group === 'other' ? rotate * 1.8 : rotate,
    }
  })
}

const papers = computed<PaperPosition[]>(() => [
  ...layoutRing(groups.value.direct, 150, -Math.PI / 2, 'direct'),
  ...layoutRing(groups.value.related, 242, -Math.PI / 2 + 0.6, 'related'),
  ...layoutRing(groups.value.other, 318, -Math.PI / 2 + 1.2, 'other'),
])

const strings = computed(() =>
  papers.value
    .filter((p) => p.group !== 'other')
    .map((p) => {
      const sag = Math.min(38, Math.hypot(p.x - CX, p.y - CY) * 0.16)
      const mx = (CX + p.x) / 2
      const my = (CY + p.y) / 2 + sag
      return { key: sourceKey(p.item), d: `M ${CX} ${CY} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`, strong: p.group === 'direct' }
    }),
)

const flipped = computed(() => papers.value.find((p) => sourceKey(p.item) === flippedKey.value) || null)

function flip(p: PaperPosition) {
  flippedKey.value = sourceKey(p.item)
}
function closePaper() {
  flippedKey.value = null
}

function pathLine(item: MemoryGraphRecallPreviewItem): string {
  const path = item.recall_match?.path
  if (!path?.relation_type) return ''
  const from = path.from?.name || ''
  const to = path.to?.name || ''
  return `${from} —${path.relation_type}→ ${to}`
}

function directAnchor(item: MemoryGraphRecallPreviewItem): string {
  return item.recall_match?.anchor?.name || ''
}

function onManualChange(key: string, value: string[]) {
  emit('update:manualAnchorIds', { ...props.manualAnchorIds, [key]: value })
}
</script>


<template>
  <div class="board-zone">
    <div v-if="error" class="board-error">{{ error }}</div>
    <NEmpty v-else-if="hasRun && !loading && !items.length" description="还没有找到相连的原件" />

    <div v-if="items.length" :key="runId" class="board" role="img" :aria-label="`想起：${query}`">
      <span class="board-grain" aria-hidden="true"></span>
      <span class="board-corner tl" aria-hidden="true"></span>
      <span class="board-corner tr" aria-hidden="true"></span>
      <span class="board-corner bl" aria-hidden="true"></span>
      <span class="board-corner br" aria-hidden="true"></span>

      <!-- 金线（先画线，纸压在线上） -->
      <svg class="board-strings" :viewBox="`0 0 ${BOARD_W} ${BOARD_H}`" aria-hidden="true">
        <path
          v-for="s in strings"
          :key="s.key"
          class="string"
          :class="{ strong: s.strong }"
          :d="s.d"
        />
      </svg>

      <!-- 中心：被想起的词 -->
      <div class="board-hub">
        <span class="hub-pin" aria-hidden="true"></span>
        <SyGlyph name="begonia" :size="34" class="hub-flower" />
        <p class="hub-eyebrow">想起了 · recalled</p>
        <p class="hub-word">「{{ query }}」</p>
        <p class="hub-count">{{ items.length }} 件原件</p>
        <button v-if="manageAnchorName" class="hub-manage" @click="emit('manage')">管理这个名字</button>
      </div>

      <!-- 三圈纸 -->
      <button
        v-for="(p, pi) in papers"
        :key="runId + sourceKey(p.item)"
        class="board-paper"
        :class="[`g-${p.group}`, `fam-${paperFamily(p.item.source_type)}`]"
        :style="{ left: `${(p.x / BOARD_W) * 100}%`, top: `${(p.y / BOARD_H) * 100}%`, '--rot': `${p.rotate}deg`, '--arrive-delay': `${pi * 70}ms` }"
        :aria-label="`原件：${p.item.title || sourceLabel(p.item.source_type)}`"
        @click="flip(p)"
      >
        <span v-if="p.group !== 'other'" class="pin" aria-hidden="true"></span>
        <span v-else class="tape" aria-hidden="true"></span>
        <span class="bp-seal" aria-hidden="true"><SyGlyph :name="p.item.source_type" :size="22" /></span>
        <span class="bp-title">{{ p.item.title || sourceLabel(p.item.source_type) }}</span>
        <span v-if="directAnchor(p.item)" class="bp-why">提到了「{{ directAnchor(p.item) }}」</span>
        <span v-else-if="pathLine(p.item)" class="bp-path">{{ pathLine(p.item) }}</span>
        <span class="bp-excerpt">
          <template v-for="(seg, i) in highlight(p.item).slice(0, 6)" :key="i"><mark v-if="seg.hit">{{ seg.text }}</mark><template v-else>{{ seg.text }}</template></template>
        </span>
        <span v-if="sourceDate(p.item)" class="bp-date">{{ sourceDate(p.item) }}</span>
      </button>
    </div>

    <!-- 取下来读的纸 -->
    <Teleport to="body">
      <Transition name="paper-zoom">
        <div v-if="flipped" class="paper-overlay" @click.self="closePaper">
          <div class="paper-read" :class="`fam-${paperFamily(flipped.item.source_type)}`" role="dialog" aria-modal="true">
            <span class="paper-read-pin" aria-hidden="true"></span>
            <header class="paper-read-head">
              <span class="bp-seal lg" aria-hidden="true"><SyGlyph :name="flipped.item.source_type" :size="32" /></span>
              <div class="paper-read-heading">
                <b>{{ flipped.item.title || sourceLabel(flipped.item.source_type) }}</b>
                <span>{{ sourceLabel(flipped.item.source_type) }}<template v-if="sourceDate(flipped.item)"> · {{ sourceDate(flipped.item) }}</template></span>
              </div>
              <NButton size="small" quaternary @click="closePaper">放回板上</NButton>
            </header>
            <p v-if="directAnchor(flipped.item)" class="paper-read-why">提到了「{{ directAnchor(flipped.item) }}」</p>
            <p v-else-if="pathLine(flipped.item)" class="paper-read-path">{{ pathLine(flipped.item) }}</p>
            <div class="paper-read-content">
              <template v-for="(seg, i) in highlight(flipped.item)" :key="i"><mark v-if="seg.hit">{{ seg.text }}</mark><template v-else>{{ seg.text }}</template></template>
            </div>
            <p v-if="flipped.item.content_complete === false" class="paper-read-incomplete">这张原件暂时没能完整取出来：{{ flipped.item.content_error }}</p>

            <footer class="paper-read-attach">
              <span class="attach-label">挂着</span>
              <NSelect
                :value="manualAnchorIds[sourceKey(flipped.item)] || []"
                multiple
                filterable
                clearable
                size="small"
                :options="anchorOptions"
                :disabled="!sourceMentionsLoaded[sourceKey(flipped.item)]"
                placeholder="关联锚点"
                class="attach-select"
                @update:value="(v: string[]) => onManualChange(sourceKey(flipped!.item), v)"
              />
              <NButton
                size="small"
                :disabled="!sourceMentionsLoaded[sourceKey(flipped.item)]"
                :loading="savingKey === sourceKey(flipped.item)"
                @click="emit('save-anchors', flipped.item)"
              >保存关联</NButton>
              <div v-if="autoAnchorNames(flipped.item).length" class="attach-auto">
                <span class="attach-label">自动连上的</span>
                <NTag v-for="name in autoAnchorNames(flipped.item)" :key="name" size="small" :bordered="false">{{ name }}</NTag>
              </div>
            </footer>
          </div>
        </div>
      </Transition>
    </Teleport>

    <NSpin v-if="loading" class="board-loading" />
  </div>
</template>

<style scoped>
.board-zone { position: relative; margin-top: 18px; }

.board-error {
  color: var(--sy-rose-d, #a4472f);
  font-size: 13px;
  padding: 10px 14px;
  border-left: 3px solid var(--sy-accent, #c8956a);
  background: var(--sy-panel, #fff8f1);
}

.board-loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }

/* ---------- 板 ---------- */
.board {
  position: relative;
  width: 100%;
  aspect-ratio: 960 / 620;
  border-radius: 18px;
  border: 1px solid var(--sy-hair-gilt, #d8c2a8);
  background:
    radial-gradient(ellipse at 30% 20%, rgba(255, 252, 246, 0.5), transparent 55%),
    linear-gradient(160deg, var(--sy-board, #e9d9c8), var(--sy-board-deep, #dcc6ae));
  box-shadow: var(--sy-shadow-paper, 0 10px 28px rgba(74, 44, 44, 0.16)), inset 0 0 60px rgba(74, 44, 44, 0.08);
  overflow: hidden;
}

.board-grain {
  position: absolute; inset: 0; pointer-events: none; opacity: 0.06; mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

.board-corner { position: absolute; width: 54px; height: 54px; pointer-events: none; opacity: 0.5; border: 0 solid var(--sy-gilt, #c79748); }
.board-corner.tl { top: 10px; left: 10px; border-top-width: 1.5px; border-left-width: 1.5px; border-top-left-radius: 8px; }
.board-corner.tr { top: 10px; right: 10px; border-top-width: 1.5px; border-right-width: 1.5px; border-top-right-radius: 8px; }
.board-corner.bl { bottom: 10px; left: 10px; border-bottom-width: 1.5px; border-left-width: 1.5px; border-bottom-left-radius: 8px; }
.board-corner.br { bottom: 10px; right: 10px; border-bottom-width: 1.5px; border-right-width: 1.5px; border-bottom-right-radius: 8px; }

/* ---------- 金线 ---------- */
.board-strings { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.string { fill: none; stroke: var(--sy-gilt, #c79748); stroke-width: 1.1; opacity: 0.5; }
.string.strong { stroke: var(--sy-accent, #a8505e); stroke-width: 2; opacity: 0.75; }

/* ---------- 中心词 ---------- */
.board-hub {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  text-align: center; padding: 18px 26px 16px;
  background: var(--sy-paper, rgba(255, 252, 250, 0.9));
  border: 1px solid var(--sy-hair-gilt, #d8c2a8); border-radius: 6px;
  box-shadow: var(--sy-shadow-paper, 0 10px 28px rgba(74, 44, 44, 0.2));
  max-width: 300px; z-index: 3;
}
.hub-pin {
  position: absolute; top: -8px; left: 50%; transform: translateX(-50%);
  width: 16px; height: 16px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #e6c98a, var(--sy-gilt, #c79748) 60%, var(--sy-gilt-d, #9a7320));
  box-shadow: 0 2px 5px rgba(74, 44, 44, 0.4);
}
.hub-eyebrow { font-family: var(--sy-serif, serif); font-size: 10px; letter-spacing: 0.42em; text-transform: uppercase; color: var(--sy-gilt, #c79748); margin: 0 0 4px; }
.hub-word { font-family: var(--sy-serif, serif); font-style: italic; font-size: 30px; font-weight: 500; color: var(--sy-ink, #4a2c2c); line-height: 1.2; margin: 0; font-variant-numeric: oldstyle-nums; }
.hub-count { font-family: var(--sy-cjk, serif); font-size: 12px; color: var(--sy-mute, rgba(74, 44, 44, 0.55)); margin: 6px 0 0; }
.hub-flower { display: block; margin: 0 auto 2px; }
.hub-manage {
  margin-top: 10px; border: 0.6px solid var(--sy-hair-gilt, #d8c2a8); border-radius: 999px;
  background: none; color: var(--sy-gilt, #c79748); font-family: var(--sy-cjk, serif);
  font-size: 11.5px; padding: 3px 14px; cursor: pointer; transition: 0.2s;
}
.hub-manage:hover { background: var(--sy-hair-gilt-2, rgba(199, 151, 72, 0.12)); }

/* ---------- 板上的纸 ---------- */
.board-paper {
  position: absolute; transform: translate(-50%, -50%) rotate(var(--rot, 0deg));
  width: 148px; padding: 12px 12px 10px;
  border: 1px solid var(--sy-hair, rgba(168, 80, 94, 0.25)); border-radius: 4px;
  background: var(--sy-paper, rgba(255, 252, 250, 0.94));
  box-shadow: 0 6px 16px rgba(74, 44, 44, 0.18);
  cursor: pointer; text-align: left; display: flex; flex-direction: column; gap: 3px;
  transition: transform 0.22s, box-shadow 0.22s; z-index: 2;
  animation: paper-arrive 0.5s cubic-bezier(0.2, 0.8, 0.3, 1.1) both;
  animation-delay: var(--arrive-delay, 0ms);
}

@keyframes paper-arrive {
  from { opacity: 0; transform: translate(-50%, -38%) rotate(var(--rot, 0deg)) scale(0.9); }
  to { opacity: 1; transform: translate(-50%, -50%) rotate(var(--rot, 0deg)) scale(1); }
}
.board-paper:hover { transform: translate(-50%, -50%) rotate(0deg) scale(1.06); box-shadow: var(--sy-shadow-lift, 0 24px 64px rgba(74, 44, 44, 0.3)); z-index: 5; }
.board-paper.g-direct { width: 168px; border-color: var(--sy-hair-gilt, #d8c2a8); }
.board-paper.g-related { width: 152px; }
.board-paper.g-other { width: 132px; opacity: 0.82; background: var(--sy-panel, rgba(255, 251, 248, 0.8)); }

.pin {
  position: absolute; top: -7px; left: 50%; transform: translateX(-50%);
  width: 13px; height: 13px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #e6c98a, var(--sy-gilt, #c79748) 60%, var(--sy-gilt-d, #9a7320));
  box-shadow: 0 2px 4px rgba(74, 44, 44, 0.35);
}
.g-direct .pin { background: radial-gradient(circle at 35% 30%, #d98a96, var(--sy-accent, #a8505e) 60%, var(--sy-accent-d, #8a3a48)); }

.tape {
  position: absolute; top: -9px; left: 50%; transform: translateX(-50%) rotate(-2deg);
  width: 62px; height: 18px; background: rgba(233, 222, 205, 0.72);
  box-shadow: 0 1px 2px rgba(74, 44, 44, 0.12);
}

.bp-seal {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; opacity: 0.95; margin-bottom: 2px;
}
.bp-title { font-family: var(--sy-serif, serif); font-size: 14px; font-weight: 600; color: var(--sy-ink, #4a2c2c); line-height: 1.25; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; }
.bp-why, .bp-path { font-family: var(--sy-serif, serif); font-style: italic; font-size: 11.5px; color: var(--sy-accent, #a8505e); line-height: 1.3; }
.bp-excerpt { font-family: var(--sy-cjk, serif); font-size: 11.5px; line-height: 1.5; color: var(--sy-ink-2, #5a3636); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.bp-excerpt mark { background: none; color: var(--sy-accent-d, #8a3a48); border-bottom: 1px solid var(--sy-accent, #a8505e); font-weight: 600; padding: 0; }
.bp-date { font-size: 9.5px; color: var(--sy-faint, rgba(74, 44, 44, 0.4)); letter-spacing: 0.04em; font-variant-numeric: oldstyle-nums; }
</style>

<style scoped>
/* ---------- 取下来读的纸 ---------- */
.paper-overlay {
  position: fixed; inset: 0; z-index: 1200;
  display: flex; align-items: center; justify-content: center; padding: 24px;
  background: rgba(40, 26, 26, 0.4); backdrop-filter: blur(3px);
}
.paper-read {
  position: relative; width: min(680px, 94vw); max-height: min(84vh, 820px); overflow-y: auto;
  background: var(--sy-paper, #fffdf8); border: 1px solid var(--sy-hair-gilt, #d8c2a8);
  border-radius: 10px; box-shadow: var(--sy-shadow-lift, 0 24px 64px rgba(0, 0, 0, 0.4));
  padding: 22px 26px 18px;
}
.paper-read-pin {
  position: absolute; top: -8px; left: 50%; transform: translateX(-50%);
  width: 16px; height: 16px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #e6c98a, var(--sy-gilt, #c79748) 60%, var(--sy-gilt-d, #9a7320));
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.35);
}
.paper-read-head { display: flex; align-items: center; gap: 12px; padding-bottom: 12px; border-bottom: 0.6px dashed var(--sy-hair, rgba(168, 80, 94, 0.3)); }
.bp-seal.lg { width: 34px; height: 34px; }
.paper-read-heading { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }
.paper-read-heading b { font-family: var(--sy-serif, serif); font-size: 19px; font-weight: 600; color: var(--sy-ink, #4a2c2c); }
.paper-read-heading span { font-size: 11.5px; color: var(--sy-mute, rgba(74, 44, 44, 0.55)); letter-spacing: 0.04em; }
.paper-read-why, .paper-read-path { margin: 10px 0 0; font-family: var(--sy-serif, serif); font-style: italic; font-size: 14px; color: var(--sy-accent, #a8505e); }
.paper-read-content { margin-top: 12px; font-family: var(--sy-cjk, serif); font-size: 14.5px; line-height: 1.95; color: var(--sy-ink, #4a2c2c); white-space: pre-wrap; word-break: break-word; }
.paper-read-content mark { background: none; color: var(--sy-accent-d, #8a3a48); border-bottom: 1.5px solid var(--sy-accent, #a8505e); font-weight: 600; padding: 0; }
.paper-read-incomplete { margin-top: 10px; font-size: 12px; color: var(--sy-rose-d, #a4472f); font-style: italic; }
.paper-read-attach { margin-top: 14px; border-top: 0.6px dashed var(--sy-hair, rgba(168, 80, 94, 0.3)); padding-top: 12px; display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; }
.attach-label { font-family: var(--sy-cjk, serif); font-size: 12px; color: var(--sy-mute, rgba(74, 44, 44, 0.55)); }
.attach-auto { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

/* ---------- 动效 ---------- */
.paper-zoom-enter-active, .paper-zoom-leave-active { transition: opacity 0.22s ease; }
.paper-zoom-enter-from, .paper-zoom-leave-to { opacity: 0; }
.paper-zoom-enter-active .paper-read { transition: transform 0.24s cubic-bezier(0.2, 0.9, 0.3, 1.2); }
.paper-zoom-enter-from .paper-read { transform: scale(0.92) translateY(10px); }
@media (prefers-reduced-motion: reduce) {
  .board-paper, .paper-zoom-enter-active, .paper-zoom-leave-active, .paper-zoom-enter-active .paper-read { transition: none; }
}

/* ---------- 手机：纸条流 ---------- */
@media (max-width: 720px) {
  .board { aspect-ratio: auto; min-height: 0; padding: 18px 14px; display: flex; flex-direction: column; gap: 12px; }
  .board-strings, .board-corner { display: none; }
  .board-hub { position: static; transform: none; margin: 0 auto 6px; }
  .board-paper { position: static; transform: none; width: 100% !important; }
  .board-paper:hover { transform: none; }
  .pin, .tape { display: none; }
}
</style>
