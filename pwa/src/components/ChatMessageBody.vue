<script setup lang="ts">
import { computed } from 'vue'
import { photoSource } from '../session/media'
import {
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Clock3,
  Pencil,
  RotateCcw,
  Sparkles,
} from 'lucide-vue-next'
import ChatNestSprite from '../ChatNestSprite.vue'
import MarkdownBody from './MarkdownBody.vue'
import PhotoStackCard from './PhotoStackCard.vue'
import { CHATNEST_STATUS_SPRITES } from '../chatnestSprite'
import { assistantParts, groupHasEcho, groupHasThinking, processSummary, traceRows } from '../stream/timeline'
import { canSwitchMessageVariant, selectedVariantIndex, variantCount } from '../session/variants'
import { splitStatusSuffix } from '../meta/statusSuffix'
import type { ProcessGroup, UiMessage } from '../types'

// 一条消息的实际内容。它刻意是 ChatMessageRow 的子组件而不是同一个组件：
// onErrorCaptured 只捕获后代的异常，捕不住自己 render 里抛的——两者合一时
// 渲染异常仍会往上冒，最终卸载整棵树。分开才是真的保险丝。

type SpriteMode = keyof typeof CHATNEST_STATUS_SPRITES

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
  openPhoto: [position: number]
  retryPhoto: [id: string]
}>()

// Display availability is independent of whether a photo enters model context.
const livePhotos = computed(() => props.message.attachments.filter((a) => photoSource(a) && a.photoState !== 'error'))
const unavailablePhotos = computed(() => props.message.attachments.filter((a) => !photoSource(a) || a.photoState === 'error'))

// 堆叠卡点的是「可看的那几张」里的第几张，换算回全部附件里的下标。
function onStackTap(stackIndex: number) {
  const target = livePhotos.value[stackIndex]
  const position = props.message.attachments.findIndex((attachment) => attachment.id === target?.id)
  emit('openPhoto', Math.max(0, position))
}

function bubbleBody(): string {
  return splitStatusSuffix(props.message.content).body
}

function bubbleSuffix(): string {
  // 展示层去掉机器锚点【】，消息数据本身保持跨端契约不变。
  return splitStatusSuffix(props.message.content).suffix.replace(/^【|】$/gu, '')
}

function spriteMode(): SpriteMode {
  const message = props.message
  const hasActiveTool = traceRows(message).some((event) => event.phase === 'tool_start' || event.ok === undefined)
  if (hasActiveTool) return 'shimmer'
  if (message.thinking && !message.content) return 'thinking'
  if (message.content) return 'writing'
  return 'entrance'
}
</script>

<template>
  <div v-if="message.role === 'assistant'" class="assistant-avatar"><Sparkles :size="15" /></div>
  <div class="message-column">
    <div v-if="message.attachments.length" class="message-images">
      <PhotoStackCard
        v-if="livePhotos.length > 1"
        :key="livePhotos.map(a => a.id).join(':')"
        :urls="livePhotos.map(photoSource)"
        @tap="onStackTap"
        @image-error="livePhotos[$event] && (livePhotos[$event].photoState = 'error')"
      />
      <template v-else v-for="(attachment, position) in message.attachments" :key="attachment.id">
        <img
          v-if="photoSource(attachment) && attachment.photoState !== 'error'"
          :src="photoSource(attachment)"
          :data-photo-id="attachment.photoId"
          :alt="attachment.title || attachment.name"
          loading="lazy"
          @error="attachment.photoState = 'error'"
          @click="emit('openPhoto', position)"
        />
      </template>
      <template v-for="attachment in unavailablePhotos" :key="`status:${attachment.id}`">
        <button v-if="attachment.photoState === 'error'" class="message-image-expired message-image-retry" type="button" @click="emit('retryPhoto', attachment.id)">
          照片暂时加载不了，点此重试
        </button>
        <span v-else-if="attachment.photoState === 'loading' || attachment.photoId" class="message-image-expired" role="status">照片正在加载…</span>
        <span v-else class="message-image-expired">本机图片已清理</span>
      </template>
    </div>
    <div v-if="message.role === 'user'" class="user-bubble">
      <template v-if="bubbleBody()">{{ bubbleBody() }}</template>
      <template v-else-if="!bubbleSuffix()">{{ '（一张图片）' }}</template>
      <span v-if="bubbleSuffix()" class="msg-suffix">{{ bubbleSuffix() }}</span>
    </div>
    <div v-else class="assistant-body">
      <template v-for="part in assistantParts(message)" :key="part.key">
        <button v-if="part.kind === 'process'" class="process-strip" :class="{ thinking: groupHasThinking(part.group), echo: groupHasEcho(part.group) }" type="button" @click="emit('openProcess', part.group)">
          <span class="process-icon">
            <Clock3 v-if="groupHasThinking(part.group)" :size="16" />
            <Sparkles v-else :size="15" />
          </span>
          <span class="process-copy">{{ processSummary(part.group) }}</span>
          <ChevronRight :size="16" />
        </button>
        <MarkdownBody v-else-if="part.content" :content="part.content" :streaming="message.streaming" />
      </template>
      <ChatNestSprite v-if="message.streaming" :mode="spriteMode()" />
      <div v-if="message.error" class="message-error">这次没有顺利接上：{{ message.error }}</div>
      <div v-if="!message.streaming && (message.content || message.echo || message.error || message.attachments.length)" class="message-actions">
        <button title="复制" aria-label="复制" @click="emit('copy', message.content || message.echo)"><Clipboard :size="15" /></button>
        <button title="重新生成" aria-label="重新生成" @click="emit('retry')"><RotateCcw :size="15" /></button>
        <span v-if="variantCount(message) > 1" class="variant-switcher">
          <button title="上一版回答" aria-label="上一版回答" :disabled="!canSwitchMessageVariant(message, -1)" @click="emit('switchVariant', -1)"><ChevronLeft :size="15" /></button>
          <span>{{ selectedVariantIndex(message) + 1 }} / {{ variantCount(message) }}</span>
          <button title="下一版回答" aria-label="下一版回答" :disabled="!canSwitchMessageVariant(message, 1)" @click="emit('switchVariant', 1)"><ChevronRight :size="15" /></button>
        </span>
      </div>
      <div v-if="!message.streaming && metaLabel" class="assistant-meta">{{ metaLabel }}</div>
    </div>
    <div v-if="message.role === 'user'" class="user-actions">
      <button title="编辑这条消息" aria-label="编辑这条消息" @click="emit('edit')"><Pencil :size="14" /></button>
      <button title="复制" aria-label="复制" @click="emit('copy', message.content)"><Clipboard :size="14" /></button>
    </div>
  </div>
</template>
