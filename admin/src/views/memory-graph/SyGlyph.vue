<script setup lang="ts">
// 渲染沈予的手绘小画（botanical.ts）。透出一个内联 SVG。
import { computed } from 'vue'
import { BEGONIA, SOURCE_GLYPHS, type SourceGlyph } from './botanical'

const props = withDefaults(defineProps<{
  /** 来源类型（journal/mem_note/windowsill/heartbeat），或 'begonia' 海棠。 */
  name: string
  size?: number
}>(), { size: 24 })

const glyph = computed<SourceGlyph>(() => {
  if (props.name === 'begonia') return BEGONIA
  return SOURCE_GLYPHS[props.name] || BEGONIA
})
</script>

<template>
  <svg
    class="sy-glyph"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    fill="none"
    aria-hidden="true"
    v-html="glyph.body"
  />
</template>

<style scoped>
.sy-glyph {
  display: inline-block;
  flex: none;
}
</style>
