<script setup lang="ts">
import { computed } from 'vue'
import { paperFamily, sourceLabel, sourceSeal } from './sourceDisplay'

const props = defineProps<{
  sourceType: string
  title?: string
  dateLabel?: string
  content: string
  complete?: boolean
  badge?: string
}>()

const family = computed(() => paperFamily(props.sourceType))
const seal = computed(() => sourceSeal(props.sourceType))
const label = computed(() => sourceLabel(props.sourceType))
</script>

<template>
  <article class="paper" :class="`paper--${family}`">
    <span class="paper-pin" aria-hidden="true"></span>
    <header class="paper-head">
      <span class="paper-seal" aria-hidden="true">{{ seal }}</span>
      <div class="paper-heading">
        <b class="paper-title">{{ title || label }}</b>
        <span class="paper-meta">{{ label }}<template v-if="dateLabel"> · {{ dateLabel }}</template></span>
      </div>
      <em v-if="badge" class="paper-badge">{{ badge }}</em>
    </header>
    <div class="paper-content">{{ content }}</div>
    <p v-if="complete === false" class="paper-incomplete">这张原件暂时没能完整取出来，上面是已经取到的部分。</p>
    <footer v-if="$slots.footer" class="paper-foot">
      <slot name="footer" />
    </footer>
  </article>
</template>

<style scoped>
.paper {
  --paper-bg: var(--sy-paper, #fffdf8);
  --paper-ink: var(--sy-ink, #3c322b);
  --paper-muted: var(--sy-mute, #7e6e5f);
  --paper-line: var(--sy-hair-2, #e9decd);
  --paper-gilt: var(--sy-gilt, #c79748);
  --paper-gilt-d: var(--sy-gilt-d, #9a7320);
  position: relative;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  background: var(--paper-bg);
  color: var(--paper-ink);
  box-shadow: var(--sy-shadow-paper, 0 10px 28px rgba(60, 50, 43, 0.16));
  padding: 18px 22px 14px;
  min-height: 260px;
}

.paper-pin {
  position: absolute;
  top: -7px;
  left: 50%;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  transform: translateX(-50%);
  background: radial-gradient(circle at 35% 30%, #e6c98a, var(--paper-gilt) 60%, var(--paper-gilt-d));
  box-shadow: 0 2px 4px rgba(60, 50, 43, 0.35);
}

.paper-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--paper-line);
}

.paper-seal {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1.5px solid var(--paper-gilt);
  border-radius: 50%;
  color: var(--paper-gilt);
  font-family: var(--sy-serif, 'Cormorant Garamond', 'Noto Serif SC', serif);
  font-size: 15px;
  transform: rotate(-4deg);
  opacity: 0.9;
  box-shadow: inset 0 0 0 2.5px var(--paper-bg), inset 0 0 0 3.5px var(--paper-gilt);
}

.paper-heading {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.paper-title {
  font-family: 'Cormorant Garamond', 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 17px;
  font-weight: 600;
}

.paper-meta {
  color: var(--paper-muted);
  font-size: 11.5px;
  letter-spacing: 0.04em;
}

.paper-badge {
  margin-left: auto;
  color: #b2552f;
  font-size: 11px;
  font-style: normal;
  border: 1px solid rgba(178, 85, 47, 0.4);
  border-radius: 999px;
  padding: 1px 8px;
}

.paper-content {
  flex: 1;
  padding: 12px 2px 6px;
  font-size: 14px;
  line-height: 1.9;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
}

.paper-incomplete {
  margin: 6px 0 0;
  color: #a8703f;
  font-size: 12px;
  font-style: italic;
}

.paper-foot {
  border-top: 1px dashed var(--paper-line);
  padding-top: 10px;
  margin-top: 6px;
}

/* ---------- journal: ruled letter paper with a torn deckle edge ---------- */
.paper--letter {
  --paper-bg: #fdf8ec;
  border-radius: 3px;
}

[data-theme='night'] .paper--letter {
  --paper-bg: #2b241c;
}

.paper--letter .paper-content {
  font-family: var(--sy-serif, 'Cormorant Garamond', 'Noto Serif SC', serif);
  font-size: 15px;
  background-image: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent calc(1.9em - 1px),
    rgba(126, 110, 95, 0.18) calc(1.9em - 1px),
    rgba(126, 110, 95, 0.18) 1.9em
  );
}

/* ---------- mem note: goose-yellow sticky note, tape on top ---------- */
.paper--sticky {
  --paper-bg: #fbf0c3;
  --paper-line: #e3d194;
  border-radius: 3px;
  transform: rotate(-0.5deg);
}

[data-theme='night'] .paper--sticky {
  --paper-bg: #4a4030;
  --paper-line: #5d5240;
}

.paper--sticky::before {
  content: '';
  position: absolute;
  top: -10px;
  left: 50%;
  width: 74px;
  height: 20px;
  transform: translateX(-50%) rotate(-1.5deg);
  background: rgba(233, 222, 205, 0.75);
  box-shadow: 0 1px 2px rgba(60, 50, 43, 0.12);
}

.paper--sticky .paper-pin {
  display: none;
}

/* ---------- windowsill / board: little card with a gilt hairline frame ---------- */
.paper--card {
  --paper-bg: var(--sy-paper, #fffdfa);
  border: 1px solid var(--paper-gilt);
  border-radius: 12px;
  box-shadow: var(--sy-shadow-paper, 0 10px 28px rgba(60, 50, 43, 0.16)), inset 0 0 0 3px var(--paper-bg), inset 0 0 0 4px var(--sy-hair-gilt, rgba(199, 151, 72, 0.4));
}

/* ---------- heartbeat: narrow slip with a double gilt rule on top ---------- */
.paper--slip {
  --paper-bg: #f7f3ea;
  border-radius: 2px;
  border-top: 3px double var(--paper-gilt);
}

[data-theme='night'] .paper--slip {
  --paper-bg: #251f18;
}

.paper--slip .paper-content {
  font-size: 13px;
  letter-spacing: 0.02em;
}

@media (max-width: 640px) {
  .paper {
    padding: 14px 14px 10px;
    min-height: 200px;
  }
}
</style>
