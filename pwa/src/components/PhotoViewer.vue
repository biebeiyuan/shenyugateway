<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import {
  IDENTITY,
  MIN_SCALE,
  type ViewState,
  clampView,
  dismissProgress,
  doubleTapView,
  pageOffset,
  pinchDistance,
  scaleAround,
  settleDuration,
  swipeIntent,
} from '../viewer/gestures'

// 点开看大图。手势数学全在 viewer/gestures.ts（纯函数、可测），这里只管 DOM
// 与事件。放大、双击、左右滑切换、下拖关闭。

const props = defineProps<{
  urls: string[]
  index: number
  captions?: (string | undefined)[]
}>()

const emit = defineEmits<{ close: []; change: [index: number] }>()

const current = ref(props.index)
const view = ref<ViewState>({ ...IDENTITY })
const drag = ref({ x: 0, y: 0 })
const dragging = ref(false)
const stage = ref<HTMLElement | null>(null)
const imageSize = ref({ width: 0, height: 0 })
// 翻页动画：整条轨道横移一屏，落位后再换图。null = 没有在翻。
const paging = ref<{ direction: -1 | 1; progress: number } | null>(null)

const containerSize = () => ({
  width: stage.value?.clientWidth || window.innerWidth,
  height: stage.value?.clientHeight || window.innerHeight,
})

const zoomed = computed(() => view.value.scale > MIN_SCALE + 0.01)
const scrim = computed(() => 1 - dismissProgress(drag.value.y, containerSize()) * 0.75)
const caption = computed(() => props.captions?.[current.value] || '')

const canGo = (direction: -1 | 1) =>
  direction < 0 ? current.value < props.urls.length - 1 : current.value > 0

// 轨道位移：拖拽时跟手（翻不动的方向带阻尼），翻页动画时插值到一屏之外。
const trackX = computed(() => {
  const width = containerSize().width
  if (paging.value) {
    // direction=-1 表示翻向下一张，图往左滑出（负位移）。
    return paging.value.direction * width * paging.value.progress
  }
  if (zoomed.value) return 0
  const dx = drag.value.x
  if (Math.abs(dx) <= Math.abs(drag.value.y)) return 0
  return pageOffset(dx, canGo(dx < 0 ? -1 : 1), containerSize())
})

const transform = computed(() => {
  const { scale, x, y } = view.value
  // 未放大时的下拖是「关闭意图」的预览，跟着手指走但不改缩放。
  const dy = zoomed.value || paging.value ? 0 : Math.max(0, drag.value.y)
  return `translate3d(${x + trackX.value}px, ${y + dy}px, 0) scale(${scale})`
})

function reset() {
  view.value = { ...IDENTITY }
  drag.value = { x: 0, y: 0 }
}

let pageFrame = 0

/** 翻页：先把当前图滑出一屏，落位后换图并从另一侧回到中间——不再是硬切。 */
function go(next: number, fromOffset = 0) {
  if (next < 0 || next >= props.urls.length) return
  cancelAnimationFrame(pageFrame)
  const direction: -1 | 1 = next > current.value ? -1 : 1
  const width = containerSize().width
  const startProgress = Math.min(0.9, Math.abs(fromOffset) / Math.max(1, width))
  const duration = settleDuration(width * (1 - startProgress), containerSize())
  const started = performance.now()
  drag.value = { x: 0, y: 0 }

  const step = (now: number) => {
    const k = Math.min(1, (now - started) / duration)
    // 与 PhotoStack 的完成动画同一条缓动：剩余行程一次走完，不跳终态。
    const eased = startProgress + (1 - startProgress) * (1 - (1 - k) ** 2)
    paging.value = { direction, progress: eased }
    if (k < 1) {
      pageFrame = requestAnimationFrame(step)
      return
    }
    paging.value = null
    current.value = next
    reset()
    emit('change', next)
  }
  pageFrame = requestAnimationFrame(step)
}

function onImageLoad(event: Event) {
  const element = event.target as HTMLImageElement
  imageSize.value = { width: element.naturalWidth, height: element.naturalHeight }
}

// ── 指针 ────────────────────────────────────────────────────────────
type Point = { x: number; y: number }
const pointers = new Map<number, Point>()
let startPointers: Point[] = []
let startView: ViewState = { ...IDENTITY }
let startDistance = 0
let lastTapAt = 0
// 这一次手势里出现过第二根手指。捏合结束时最后那根手指几乎没位移，若不记住这件事
// 就会被判成轻点——而捏回原大小之后 zoomed 又是 false，于是直接把看图器关了。
let wasPinch = false

function relativeToCenter(point: Point): Point {
  const box = stage.value?.getBoundingClientRect()
  if (!box) return { x: 0, y: 0 }
  return { x: point.x - (box.left + box.width / 2), y: point.y - (box.top + box.height / 2) }
}

function onPointerDown(event: PointerEvent) {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  startPointers = [...pointers.values()]
  startView = { ...view.value }
  dragging.value = true
  if (startPointers.length === 1) wasPinch = false
  if (startPointers.length === 2) {
    wasPinch = true
    startDistance = pinchDistance(startPointers[0], startPointers[1])
  }
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!pointers.has(event.pointerId)) return
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  const active = [...pointers.values()]

  if (active.length >= 2 && startDistance > 0) {
    const distance = pinchDistance(active[0], active[1])
    const origin = relativeToCenter({
      x: (active[0].x + active[1].x) / 2,
      y: (active[0].y + active[1].y) / 2,
    })
    view.value = scaleAround(startView, startView.scale * (distance / startDistance), origin, imageSize.value, containerSize())
    return
  }

  const dx = active[0].x - startPointers[0].x
  const dy = active[0].y - startPointers[0].y
  if (zoomed.value) {
    // 放大状态下单指是平移，边界由 clampView 管住。
    view.value = clampView({ scale: startView.scale, x: startView.x + dx, y: startView.y + dy }, imageSize.value, containerSize())
  } else {
    drag.value = { x: dx, y: dy }
  }
}

function onPointerUp(event: PointerEvent) {
  pointers.delete(event.pointerId)
  if (pointers.size >= 2) return
  if (pointers.size === 1) {
    // 一根手指离开捏合：把剩下那根当成新的拖拽起点，避免图突然跳。
    startPointers = [...pointers.values()]
    startView = { ...view.value }
    startDistance = 0
    return
  }

  dragging.value = false
  startDistance = 0
  const moved = Math.hypot(drag.value.x, drag.value.y)
  const pinched = wasPinch
  wasPinch = false

  // 捏合刚结束：既不是滑动也不是轻点，什么都别做。
  if (pinched) {
    drag.value = { x: 0, y: 0 }
    lastTapAt = 0
    return
  }

  if (!zoomed.value && moved > 8) {
    const intent = swipeIntent(drag.value.x, drag.value.y, containerSize())
    if (intent === 'next') return go(current.value + 1, drag.value.x)
    if (intent === 'prev') return go(current.value - 1, drag.value.x)
    if (intent === 'dismiss') return emit('close')
    drag.value = { x: 0, y: 0 }
    return
  }
  drag.value = { x: 0, y: 0 }

  if (moved <= 8) {
    const now = Date.now()
    if (now - lastTapAt < 280) {
      lastTapAt = 0
      view.value = doubleTapView(view.value, relativeToCenter({ x: event.clientX, y: event.clientY }), imageSize.value, containerSize())
      return
    }
    lastTapAt = now
    // 单击关闭：等双击窗口过去再决定，否则双击的第一下就把看图器关了。
    window.setTimeout(() => {
      if (lastTapAt && Date.now() - lastTapAt >= 280 && !zoomed.value) emit('close')
    }, 300)
  }
}

function onPointerCancel(event: PointerEvent) {
  pointers.delete(event.pointerId)
  if (!pointers.size) wasPinch = false
  dragging.value = false
  drag.value = { x: 0, y: 0 }
  startDistance = 0
  void event
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
  if (event.key === 'ArrowRight') go(current.value + 1)
  if (event.key === 'ArrowLeft') go(current.value - 1)
}

// 看图器打开时锁掉页面缩放：它自己要处理双击放大和双指捏合，两套手势会打架。
// 聊天页面本身不禁缩放（那是无障碍功能）。
let restoreViewport = ''
const VIEWPORT_LOCKED = 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover'

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  const meta = document.querySelector('meta[name="viewport"]')
  if (meta) {
    restoreViewport = meta.getAttribute('content') || ''
    meta.setAttribute('content', VIEWPORT_LOCKED)
  }
})

onBeforeUnmount(() => {
  cancelAnimationFrame(pageFrame)
  window.removeEventListener('keydown', onKeydown)
  const meta = document.querySelector('meta[name="viewport"]')
  if (meta && restoreViewport) meta.setAttribute('content', restoreViewport)
})

watch(() => props.index, (next) => { current.value = next; reset() })
</script>

<template>
  <div class="photo-viewer" :style="{ backgroundColor: `rgba(0, 0, 0, ${scrim})` }">
    <button class="photo-viewer-close" aria-label="关闭" title="关闭" @click="emit('close')">
      <X :size="20" />
    </button>
    <span v-if="urls.length > 1" class="photo-viewer-count">{{ current + 1 }} / {{ urls.length }}</span>

    <div
      ref="stage"
      class="photo-viewer-stage"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
    >
      <img
        :key="urls[current]"
        class="photo-viewer-image"
        :class="{ dragging: dragging || paging !== null }"
        :src="urls[current]"
        :style="{ transform }"
        alt=""
        draggable="false"
        @load="onImageLoad"
      />
    </div>

    <p v-if="caption" class="photo-viewer-caption">{{ caption }}</p>
  </div>
</template>
