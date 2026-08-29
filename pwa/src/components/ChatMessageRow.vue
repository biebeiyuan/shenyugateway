<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import ChatMessageBody from './ChatMessageBody.vue'
import type { ProcessGroup, UiMessage } from '../types'

// 一条消息一根保险丝。两件事都靠它：
//   1. 打字不再牵动整条历史——父级 ref 变化时 props 没变的行不重渲染。实测拆分
//      前输入框敲一个字会让 40 条消息全部重新渲染 Markdown（约 200ms 阻塞）。
//   2. 坏一条不白屏——单组件结构下任何渲染异常都会让 Vue 卸载整棵树（实测 DOM
//      塌成 <!---->），装成 PWA 的手机上看不到 console，只看到一片白。
// 内容刻意放在子组件 ChatMessageBody 里：onErrorCaptured 捕获不到自己 render
// 抛出的异常，只捕后代的。合成一个组件时保险丝就是空的。
const props = defineProps<{
  message: UiMessage
  metaLabel: string
}>()

const emit = defineEmits<{
  openProcess: [group: ProcessGroup]
  copy: [text: string]
  retry: []
  switchVariant: [direction: -1 | 1]
  edit: []
}>()

const broken = ref(false)
onErrorCaptured((error) => {
  broken.value = true
  console.error('[PWA] 这条消息渲染失败', error)
  return false
})
</script>

<template>
  <article class="message-row" :class="message?.role">
    <p v-if="broken" class="message-error">这条消息没能显示出来，其余对话不受影响。</p>
    <ChatMessageBody
      v-else
      :message="message"
      :meta-label="metaLabel"
      @open-process="emit('openProcess', $event)"
      @copy="emit('copy', $event)"
      @retry="emit('retry')"
      @switch-variant="emit('switchVariant', $event)"
      @edit="emit('edit')"
    />
  </article>
</template>
