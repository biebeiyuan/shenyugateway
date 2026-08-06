<script setup lang="ts">
// 描金线索板 · 想起的一瞬间
//
// 空间骨架是侦探软木板（钉、连线、胶带），皮肤是 rose-gothic Mucha（古金
// 发丝线、宽字距眉题、老式数字）。中心是被想起的词；三圈纸按远近围着他——
// 脱口而出（松绿钉 + 实线连到中心）、由此及彼（金钉 + 细金线 + 路径牌）、
// 浮想（胶带粘在外圈，不连线）。
// 角度全局均分：第一张纸永远在正上方，之后均匀围满一圈，
// 件数少不再挤到某一侧；词卡收窄，内圈纸从卡外经过，不被压住。
// 点一张纸，它从板上取下来放大读全文，阅读层与锚点阅读卡共用同一套
// OriginalPaper / AttachAnchors。

import { computed, ref } from 'vue'
import { NButton, NEmpty } from 'naive-ui'
import type { MemoryGraphRecallPreviewItem } from '@/api/memoryGraph'
import { paperFamily, sourceLabel } from './sourceDisplay'
import { sourceKey } from './sourceAnchors'
import SyGlyph from './SyGlyph.vue'
import OriginalPaper from './OriginalPaper.vue'
import AttachAnchors from './AttachAnchors.vue'

type RecallGroup = 'direct' | 'related' | 'other'

interface PaperPosition {
  item: MemoryGraphRecallPreviewItem
  x: number
  y: number
  rotate: number
  group: RecallGroup
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
  /** 关联锚点编辑（与阅读卡同一套 AttachAnchors）。 */
  anchorOptions: { label: string; value: string }[]
  runId: number
}>()

const emit = defineEmits<{
  (e: 'manage'): void
  (e: 'saved'): void
}>()

const BOARD_W = 960
const BOARD_H = 620
const CX = BOARD_W / 2
const CY = BOARD_H / 2

const flippedKey = ref<string | null>(null)

function groupOf(item: MemoryGraphRecallPreviewItem): RecallGroup {
  const group = item.recall_match?.group
  return group === 'direct' || group === 'related' ? group : 'other'
}

// 用 source key 做种子，同一次想起刷新不跳，换一批才换布局。
function seed(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0
  return h
}

// 三圈半径（竖向压扁 RY_RATIO）：内圈恰好在词卡外，外圈不出板边。
// 角度全局均分：第一张纸永远在正上方，之后顺时针均匀围住中心——
// 不论几件事、属于哪一组，都不会再挤到某一侧。
const RY_RATIO = 0.66
const RADIUS: Record<RecallGroup, number> = { direct: 225, related: 278, other: 330 }

function groupRank(group: RecallGroup): number {
  return group === 'direct' ? 0 : group === 'related' ? 1 : 2
}

const papers = computed<PaperPosition[]>(() => {
  const ordered = [...props.items].sort((a, b) => groupRank(groupOf(a)) - groupRank(groupOf(b)))
  const n = ordered.length
  if (!n) return []
  return ordered.map((item, k) => {
    const s = seed(sourceKey(item))
    const group = groupOf(item)
    const angle = -Math.PI / 2 + (k / n) * Math.PI * 2 + (((s % 16) - 8) * Math.PI) / 180
    const rx = RADIUS[group]
    return {
      item,
      group,
      x: CX + rx * Math.cos(angle),
      y: CY + rx * RY_RATIO * Math.sin(angle),
      rotate: (((s >> 5) % 9) - 4) * (group === 'other' ? 1.8 : 1),
    }
  })
})

const strings = computed(() =>
  papers.value
    .filter((p) => p.group !== 'other')
    .map((p) => {
      const sag = Math.min(34, Math.hypot(p.x - CX, p.y - CY) * 0.12)
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

function ledeLine(item: MemoryGraphRecallPreviewItem): string {
  const anchor = directAnchor(item)
  if (anchor) return `提到了「${anchor}」`
  return pathLine(item)
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
        <SyGlyph name="begonia" :size="26" class="hub-flower" />
        <p class="hub-eyebrow">想起了 · recalled</p>
        <p class="hub-word">「{{ query }}」</p>
        <p class="hub-count">{{ items.length }} 件原件</p>
        <button v-if="manageAnchorName" class="hub-manage" data-testid="recall-manage-anchor" @click="emit('manage')">管理这个名字</button>
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
        <span v-if="p.group !== 'other'" class="pin" :class="{ pine: p.group === 'direct' }" aria-hidden="true"></span>
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

    <!-- 取下来读的纸：与锚点阅读卡同一套 OriginalPaper -->
    <Teleport to="body">
      <Transition name="paper-zoom">
        <div v-if="flipped" class="paper-overlay" @click.self="closePaper">
          <OriginalPaper
            class="paper-read"
            role="dialog"
            aria-modal="true"
            :source-type="flipped.item.source_type"
            :title="flipped.item.title"
            :date-label="sourceDate(flipped.item)"
            :content="flipped.item.content || ''"
            :complete="flipped.item.content_complete !== false"
            :lede="ledeLine(flipped.item)"
          >
            <template #content>
              <template v-for="(seg, i) in highlight(flipped.item)" :key="i"><mark v-if="seg.hit">{{ seg.text }}</mark><template v-else>{{ seg.text }}</template></template>
            </template>
            <template #footer>
              <div class="read-actions">
                <NButton size="small" quaternary @click="closePaper">放回板上</NButton>
              </div>
              <AttachAnchors
                :source-table="flipped.item.source_table"
                :source-type="flipped.item.source_type"
                :source-id="flipped.item.source_id"
                :anchor-options="anchorOptions"
                @saved="emit('saved')"
              />
            </template>
          </OriginalPaper>
        </div>
      </Transition>
    </Teleport>

    <p v-if="loading" class="board-thinking"><span class="think-dot" aria-hidden="true"></span>想起中…</p>
  </div>
</template>

<style scoped>
.board-zone { position: relative; margin-top: 18px; }

.board-error {
  color: var(--sy-rose-d, #8b7082);
  font-size: 13px;
  padding: 10px 14px;
  border-left: 3px solid var(--sy-accent, #c094a8);
  background: var(--sy-panel, rgba(255, 251, 248, 0.58));
}

/* 想起中：柔和的一点，不转圈 */
.board-thinking {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 12px 0 0;
  font-family: var(--sy-serif, serif);
  font-style: italic;
  font-size: 13px;
  color: var(--sy-mute, rgba(74, 44, 44, 0.55));
}

.think-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--sy-resident, #2c4a44);
  animation: think-pulse 1.6s ease-in-out infinite;
}

@keyframes think-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1); }
}

/* ---------- 板 ---------- */
.board {
  position: relative;
  width: 100%;
  aspect-ratio: 960 / 620;
  border-radius: 18px;
  border: 1px solid var(--sy-hair-gilt, #d8c2a8);
  background:
    radial-gradient(ellipse at 30% 20%, rgba(255, 252, 250, 0.5), transparent 55%),
    linear-gradient(160deg, var(--sy-board, #eed6d0), var(--sy-board-deep, #e3c6bf));
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
.string.strong { stroke: var(--sy-resident, #2c4a44); stroke-width: 2; opacity: 0.75; }

/* ---------- 中心：被想起的词（收窄，让内圈纸从卡外经过） ---------- */
.board-hub {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  text-align: center; padding: 12px 18px 11px;
  background: var(--sy-paper, rgba(255, 252, 252, 0.92));
  border: 1px solid var(--sy-hair-gilt, #d8c2a8); border-radius: 6px;
  box-shadow: var(--sy-shadow-paper, 0 10px 28px rgba(74, 44, 44, 0.2));
  max-width: 200px; z-index: 3;
}
.hub-pin {
  position: absolute; top: -7px; left: 50%; transform: translateX(-50%);
  width: 14px; height: 14px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #e6c98a, var(--sy-gilt, #c79748) 60%, var(--sy-gilt-d, #9a7320));
  box-shadow: 0 2px 5px rgba(74, 44, 44, 0.4);
}
.hub-eyebrow { font-family: var(--sy-serif, serif); font-size: 9px; letter-spacing: 0.38em; text-transform: uppercase; color: var(--sy-gilt, #c79748); margin: 0 0 3px; }
.hub-word { font-family: var(--sy-serif, serif); font-style: italic; font-size: 22px; font-weight: 500; color: var(--sy-ink, #4a2c2c); line-height: 1.2; margin: 0; font-variant-numeric: oldstyle-nums; overflow: hidden; text-overflow: ellipsis; }
.hub-count { font-family: var(--sy-cjk, serif); font-size: 11px; color: var(--sy-mute, rgba(74, 44, 44, 0.55)); margin: 3px 0 0; }
.hub-flower { display: block; margin: 0 auto 1px; }
.hub-manage {
  margin-top: 7px; border: 0; background: none; padding: 0; cursor: pointer;
  color: var(--sy-self, #c094a8); font-family: var(--sy-cjk, serif); font-size: 11.5px;
  text-decoration: underline; text-underline-offset: 3px;
}
.hub-manage:hover { color: var(--sy-self-d, #a07888); }

/* ---------- 板上的纸 ---------- */
.board-paper {
  position: absolute; transform: translate(-50%, -50%) rotate(var(--rot, 0deg));
  width: 176px; padding: 12px 12px 10px;
  border: 1px solid var(--sy-hair, rgba(206, 148, 160, 0.38)); border-radius: 4px;
  background: var(--sy-paper, rgba(255, 252, 252, 0.94));
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
.board-paper.g-direct { width: 208px; border-color: var(--sy-hair-gilt, #d8c2a8); }
.board-paper.g-related { width: 176px; }
.board-paper.g-other { width: 144px; opacity: 0.82; background: var(--sy-panel, rgba(255, 250, 251, 0.8)); }

/* 来源族一眼可辨（与 OriginalPaper 同一种纸） */
.board-paper.fam-letter { border-radius: 3px; }
.board-paper.fam-sticky { background: var(--sy-rose-soft); border-radius: 3px; }
.board-paper.fam-card { border-color: var(--sy-hair-gilt, #d8c2a8); }
.board-paper.fam-slip { border-top: 3px double var(--sy-gilt, #c79748); border-radius: 2px; }
[data-theme='night'] .board-paper.fam-sticky { background: #43303a; }

.pin {
  position: absolute; top: -7px; left: 50%; transform: translateX(-50%);
  width: 13px; height: 13px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #e6c98a, var(--sy-gilt, #c79748) 60%, var(--sy-gilt-d, #9a7320));
  box-shadow: 0 2px 4px rgba(74, 44, 44, 0.35);
}
/* 脱口而出 = 沈予直接想起的 → 松绿钉 */
.pin.pine { background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--sy-resident, #2c4a44) 45%, #fff), var(--sy-resident, #2c4a44) 60%, var(--sy-resident-d, #1f3632)); }

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
.bp-why { font-family: var(--sy-serif, serif); font-style: italic; font-size: 11.5px; color: var(--sy-resident, #2c4a44); line-height: 1.3; }
.bp-path { font-family: var(--sy-serif, serif); font-style: italic; font-size: 11.5px; color: var(--sy-gilt-d, #9a7320); line-height: 1.3; }
.bp-excerpt { font-family: var(--sy-cjk, serif); font-size: 11.5px; line-height: 1.5; color: var(--sy-ink-2, #5a3636); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.bp-excerpt mark { background: none; color: var(--sy-self-d, #a07888); border-bottom: 1px solid var(--sy-self, #c094a8); font-weight: 600; padding: 0; }
.bp-date { font-size: 9.5px; color: var(--sy-faint, rgba(74, 44, 44, 0.4)); letter-spacing: 0.04em; font-variant-numeric: oldstyle-nums; }
</style>

<style scoped>
/* ---------- 取下来读的纸（OriginalPaper 的阅读层） ---------- */
.paper-overlay {
  position: fixed; inset: 0; z-index: 1200;
  display: flex; align-items: center; justify-content: center; padding: 24px;
  background: rgba(44, 44, 44, 0.4); backdrop-filter: blur(3px);
}
.paper-read {
  width: min(680px, 94vw); max-height: min(84vh, 820px); overflow-y: auto;
  box-shadow: var(--sy-shadow-lift, 0 24px 64px rgba(44, 44, 44, 0.4));
}
.paper-read :deep(.paper-content) { max-height: 46vh; }
.read-actions { display: flex; justify-content: flex-end; margin-bottom: 8px; }

/* ---------- 动效 ---------- */
.paper-zoom-enter-active, .paper-zoom-leave-active { transition: opacity 0.22s ease; }
.paper-zoom-enter-from, .paper-zoom-leave-to { opacity: 0; }
.paper-zoom-enter-active .paper-read { transition: transform 0.24s cubic-bezier(0.2, 0.9, 0.3, 1.2); }
.paper-zoom-enter-from .paper-read { transform: scale(0.92) translateY(10px); }
@media (prefers-reduced-motion: reduce) {
  .board-paper, .think-dot, .paper-zoom-enter-active, .paper-zoom-leave-active, .paper-zoom-enter-active .paper-read { transition: none; animation: none; }
}

/* ---------- 手机：纸条流 ---------- */
@media (max-width: 720px) {
  .board { aspect-ratio: auto; min-height: 0; padding: 18px 14px; display: flex; flex-direction: column; gap: 12px; }
  .board-strings, .board-corner { display: none; }
  .board-hub { position: static; transform: none; margin: 0 auto 6px; max-width: none; }
  .board-paper { position: static; transform: none; width: 100% !important; }
  .board-paper:hover { transform: none; }
  .pin, .tape { display: none; }
}
</style>
