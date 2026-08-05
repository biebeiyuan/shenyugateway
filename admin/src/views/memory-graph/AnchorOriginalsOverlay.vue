<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NSpin, useMessage } from 'naive-ui'
import {
  addMemoryEntityAlias,
  deleteMemoryEntityAlias,
  type MemoryEntity,
  type MemoryGraphNameCandidate,
} from '@/api/memoryGraph'
import OriginalPaper from './OriginalPaper.vue'
import AttachAnchors from './AttachAnchors.vue'

export interface OverlayPaper {
  key: string
  sourceType: string
  sourceTable?: string
  sourceId?: string
  title?: string
  dateLabel?: string
  content: string
  complete?: boolean
  badge?: string
}

const props = defineProps<{
  open: boolean
  anchor: MemoryEntity | null
  ghost: MemoryGraphNameCandidate | null
  papers: OverlayPaper[]
  loading: boolean
  anchorOptions: { label: string; value: string }[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'pin'): void
  (e: 'entity-mutated'): void
}>()

const message = useMessage()
const index = ref(0)
const aliasDraft = ref('')
const aliasSaving = ref(false)

const current = computed(() => props.papers[index.value] || null)
const aliases = computed(() => props.anchor?.aliases || [])

watch(
  () => [props.open, props.anchor?.id, props.ghost?.name],
  () => {
    index.value = 0
    aliasDraft.value = ''
  },
)

watch(
  () => props.papers,
  () => {
    if (index.value >= props.papers.length) index.value = Math.max(0, props.papers.length - 1)
  },
)

async function addAlias() {
  const anchor = props.anchor
  const value = aliasDraft.value.trim()
  if (!anchor || !value || aliasSaving.value) return
  aliasSaving.value = true
  try {
    await addMemoryEntityAlias(anchor.id, value)
    aliasDraft.value = ''
    message.success('叫法已加上')
    emit('entity-mutated')
  } catch {
    message.error('添加叫法失败')
  } finally {
    aliasSaving.value = false
  }
}

async function removeAlias(aliasId: string) {
  if (!props.anchor || aliasSaving.value) return
  aliasSaving.value = true
  try {
    await deleteMemoryEntityAlias(aliasId)
    message.success('叫法已去掉')
    emit('entity-mutated')
  } catch {
    message.error('去掉叫法失败')
  } finally {
    aliasSaving.value = false
  }
}

function flip(delta: number) {
  const next = index.value + delta
  if (next < 0 || next >= props.papers.length) return
  index.value = next
}

function onKeydown(event: KeyboardEvent) {
  if (!props.open) return
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) {
    if (event.key !== 'Escape') return
  }
  if (event.key === 'Escape') emit('close')
  else if (event.key === 'ArrowLeft') flip(-1)
  else if (event.key === 'ArrowRight') flip(1)
}

window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div
        v-if="open"
        class="mg-overlay"
        data-testid="memory-graph-originals-overlay"
        @click.self="emit('close')"
      >
        <div class="mg-sheet" role="dialog" aria-modal="true" :aria-label="anchor?.canonical_name || ghost?.name || '原件'">
          <header class="sheet-head">
            <div class="sheet-title">
              <h3>{{ anchor?.canonical_name || ghost?.name }}</h3>
              <span v-if="anchor" class="sheet-meta">{{ anchor.mention_count }} 张纸 · {{ anchor.relation_count }} 条红线</span>
              <span v-else-if="ghost" class="sheet-meta">还没钉 · 沈予提过 {{ ghost.count }} 次</span>
            </div>
            <div class="sheet-actions">
              <NButton v-if="ghost" size="small" type="primary" @click="emit('pin')">钉住它</NButton>
              <NButton size="small" quaternary @click="emit('close')">放回去</NButton>
            </div>
          </header>

          <div v-if="anchor" class="alias-row">
            <span class="alias-label">命中词</span>
            <span
              v-for="alias in aliases"
              :key="alias.id"
              class="alias-chip"
              :class="{ primary: alias.is_primary }"
            >
              {{ alias.alias }}
              <button
                v-if="!alias.is_primary"
                class="alias-remove"
                :disabled="aliasSaving"
                :aria-label="`去掉叫法 ${alias.alias}`"
                @click="removeAlias(alias.id)"
              >×</button>
            </span>
            <span class="alias-add">
              <input
                v-model="aliasDraft"
                placeholder="加个叫法，比如：老妹"
                :disabled="aliasSaving"
                @keyup.enter="addAlias"
              />
              <button :disabled="aliasSaving || !aliasDraft.trim()" aria-label="添加叫法" @click="addAlias">＋</button>
            </span>
          </div>

          <div class="paper-stage">
            <NSpin :show="loading">
              <Transition name="paper-flip" mode="out-in">
                <OriginalPaper
                  v-if="current"
                  :key="current.key"
                  :source-type="current.sourceType"
                  :title="current.title"
                  :date-label="current.dateLabel"
                  :content="current.content"
                  :complete="current.complete"
                  :badge="current.badge"
                >
                  <template v-if="anchor && current.sourceTable" #footer>
                    <AttachAnchors
                      :key="current.key"
                      :source-table="current.sourceTable"
                      :source-type="current.sourceType"
                      :source-id="current.sourceId"
                      :anchor-options="anchorOptions"
                      @saved="emit('entity-mutated')"
                    />
                  </template>
                </OriginalPaper>
                <p v-else-if="!loading" key="empty" class="stage-empty">还没有原件提到这个名字</p>
              </Transition>
            </NSpin>
          </div>

          <footer v-if="papers.length > 1" class="sheet-foot">
            <button class="flip-btn" :disabled="index === 0" aria-label="上一张" @click="flip(-1)">← 上一张</button>
            <span class="flip-pos">{{ index + 1 }} / {{ papers.length }}</span>
            <button class="flip-btn" :disabled="index === papers.length - 1" aria-label="下一张" @click="flip(1)">下一张 →</button>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>



<style scoped>
.mg-overlay {
  /* Teleport 到 body，继承不到 .graph-page，桥接同一批设计 token（不再自带色）。 */
  --mg-paper: var(--sy-paper);
  --mg-panel: var(--sy-panel);
  --mg-ink: var(--sy-ink);
  --mg-ink-2: var(--sy-ink-2);
  --mg-ink-3: var(--sy-mute);
  --mg-hairline: var(--sy-hair-2);
  --mg-accent: var(--sy-resident);
  --mg-serif: var(--sy-serif);
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(44, 44, 44, 0.42);
  backdrop-filter: blur(2px);
}

.mg-sheet {
  display: flex;
  flex-direction: column;
  width: min(720px, 94vw);
  max-height: min(86vh, 860px);
  border: 1px solid var(--mg-hairline);
  border-radius: 18px;
  background: radial-gradient(circle at 18% 12%, rgba(199, 151, 72, 0.06), transparent 42%), var(--mg-paper);
  box-shadow: var(--sy-shadow-lift);
  padding: 18px 22px 16px;
}

.sheet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.sheet-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.sheet-title h3 {
  font-family: var(--mg-serif);
  font-size: 26px;
  font-weight: 600;
  color: var(--mg-ink);
}

.sheet-meta {
  color: var(--mg-ink-3);
  font-size: 12px;
}

.sheet-actions {
  display: flex;
  gap: 8px;
}

.alias-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px dashed var(--mg-hairline);
  border-radius: 12px;
  background: var(--mg-panel);
}

.alias-label {
  color: var(--mg-ink-3);
  font-size: 12px;
  margin-right: 2px;
}

.alias-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--mg-hairline);
  border-radius: 999px;
  background: var(--mg-paper);
  color: var(--mg-ink-2);
  font-size: 12.5px;
  padding: 2px 10px;
}

.alias-chip.primary {
  border-style: dashed;
  color: var(--mg-ink-3);
}

.alias-remove {
  border: 0;
  background: none;
  color: var(--mg-ink-3);
  cursor: pointer;
  font-size: 13px;
  padding: 0 0 0 2px;
  line-height: 1;
}

.alias-remove:hover {
  color: var(--mg-accent);
}

.alias-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.alias-add input {
  width: 170px;
  border: 0;
  border-bottom: 1px dashed var(--mg-hairline);
  background: none;
  color: var(--mg-ink);
  font-size: 12.5px;
  padding: 3px 4px;
  outline: none;
}

.alias-add input:focus {
  border-bottom-color: var(--mg-accent);
}

.alias-add button {
  border: 1px solid var(--mg-hairline);
  border-radius: 50%;
  width: 22px;
  height: 22px;
  background: var(--mg-paper);
  color: var(--mg-ink-2);
  cursor: pointer;
  line-height: 1;
}

.alias-add button:disabled {
  opacity: 0.4;
  cursor: default;
}

.paper-stage {
  flex: 1;
  min-height: 300px;
  margin-top: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.paper-stage :deep(.n-spin-container),
.paper-stage :deep(.n-spin-content) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.paper-stage :deep(.paper) {
  flex: 1;
  min-height: 0;
}

.paper-stage :deep(.paper-content) {
  max-height: calc(min(86vh, 860px) - 330px);
}

.stage-empty {
  margin: auto;
  color: var(--mg-ink-3);
  font-size: 13px;
  font-style: italic;
}

.sheet-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  margin-top: 12px;
}

.flip-btn {
  border: 1px solid var(--mg-hairline);
  border-radius: 999px;
  background: var(--mg-panel);
  color: var(--mg-ink-2);
  font-size: 12.5px;
  padding: 5px 16px;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}

.flip-btn:hover:not(:disabled) {
  border-color: var(--mg-accent);
  color: var(--mg-accent);
}

.flip-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.flip-pos {
  color: var(--mg-ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.overlay-fade-enter-active,
.overlay-fade-leave-active {
  transition: opacity 0.22s ease;
}

.overlay-fade-enter-from,
.overlay-fade-leave-to {
  opacity: 0;
}

.overlay-fade-enter-active .mg-sheet {
  animation: sheet-lift 0.26s cubic-bezier(0.2, 0.9, 0.3, 1.2);
}

@keyframes sheet-lift {
  from {
    transform: translateY(14px) rotate(0.6deg) scale(0.97);
    box-shadow: 0 6px 18px rgba(44, 44, 44, 0.2);
  }
  to {
    transform: none;
    box-shadow: var(--sy-shadow-lift);
  }
}

.paper-flip-enter-active,
.paper-flip-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.paper-flip-enter-from {
  opacity: 0;
  transform: translateX(26px) rotate(0.8deg);
}

.paper-flip-leave-to {
  opacity: 0;
  transform: translateX(-26px) rotate(-0.8deg);
}

@media (max-width: 640px) {
  .mg-overlay {
    padding: 10px;
    align-items: flex-end;
  }

  .mg-sheet {
    width: 100%;
    max-height: 92vh;
    border-radius: 16px 16px 0 0;
    padding: 14px 14px 12px;
  }

  .alias-add input {
    width: 120px;
  }
}
</style>
