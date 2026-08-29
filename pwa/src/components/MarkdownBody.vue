<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../markdown'

// 正文渲染的唯一落点。流式期间也走 Markdown（收尾时不再整段重排），但跳过语法
// 高亮——highlightAuto 3.28ms/块进 chunk 循环会让流式发抖。收尾这一帧补上高亮。
const props = defineProps<{ content: string; streaming?: boolean }>()

const html = computed(() => renderMarkdown(props.content, { highlight: !props.streaming }))
</script>

<template>
  <div class="markdown-content" v-html="html" />
</template>
