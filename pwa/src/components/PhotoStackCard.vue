<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  STACK_DEFAULTS,
  type CardState,
  dragProgress,
  restingStates,
  scrubStates,
  shouldTurn,
  smoothVelocity,
} from '../viewer/photoStack'

// 合并照片卡。摆位数学在 viewer/photoStack.ts（移植自 PhotoStack by Wren036,
// PolyForm Noncommercial 1.0.0，署名见该文件头与 STYLE_AND_CRAFT § 风格血统声明）。
// 这里只负责事件与渲染：上游直接写 DOM style，我们把状态交给 Vue。

const props = defineProps<{ urls: string[] }>()
const emit = defineEmits<{ tap: [index: number]; change: [index: number] }>()

const current = ref(0)
const scrub = ref<CardState[] | null>(null)
const animating = ref(false)
const stage = ref<HTMLElement | null>(null)

// 拖拽中逐帧直写（跟手），松手后交给 CSS 过渡回弹——上游的「双模 transition」。
const states = computed(() => scrub.value || restingStates(props.urls.length, current.value))

let startX: number | null = null
let startY = 0
let lastX = 0
let lastT = 0
let velocity = 0
let dragging = false
let swiped = false
let frame = 0
let pendingDirection: -1 | 1 = -1

function stageWidth(): number {
  return stage.value?.offsetWidth || STACK_DEFAULTS.peek * 8
}

function settle(direction: -1 | 1) {
  const total = props.urls.length
  current.value = direction < 0
    ? Math.min(current.value + 1, total - 1)
    : Math.max(current.value - 1, 0)
  // 擦洗 p=1 与结算态数学上相等，所以这一步没有视觉跳变（上游的「结算零跳变」）。
  scrub.value = null
  emit('change', current.value)
}

function finish(direction: -1 | 1, fromProgress: number) {
  cancelAnimationFrame(frame)
  animating.value = true
  pendingDirection = direction
  const duration = Math.max(140, (1 - fromProgress) * 340)
  const started = performance.now()
  const step = (now: number) => {
    const k = Math.min(1, (now - started) / duration)
    // 沿同一条峰形轨迹播完剩余行程，而不是直接跳到终态。
    const eased = fromProgress + (1 - fromProgress) * (1 - (1 - k) ** 2)
    scrub.value = scrubStates(props.urls.length, current.value, direction, eased, stageWidth())
    if (k < 1) {
      frame = requestAnimationFrame(step)
      return
    }
    animating.value = false
    settle(direction)
  }
  frame = requestAnimationFrame(step)
}

function onPointerDown(event: PointerEvent) {
  startX = event.clientX
  startY = event.clientY
  lastX = event.clientX
  lastT = event.timeStamp
  velocity = 0
  dragging = false
  swiped = false
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (startX === null) return
  const dx = event.clientX - startX
  const dy = event.clientY - startY
  if (event.timeStamp > lastT) {
    velocity = smoothVelocity(velocity, event.clientX - lastX, event.timeStamp - lastT)
  }
  lastX = event.clientX
  lastT = event.timeStamp
  // 位移超过 8px 且横向为主才接管，纵向滚动交还页面（配合 touch-action: pan-y）。
  if (!dragging && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) dragging = true
  if (!dragging) return
  event.preventDefault()
  if (animating.value) {
    // 打断进行中的完成动画先结算页码，保证连甩每次翻且仅翻一页。
    cancelAnimationFrame(frame)
    animating.value = false
    settle(pendingDirection)
  }
  scrub.value = scrubStates(props.urls.length, current.value, dx < 0 ? -1 : 1, dragProgress(dx, startX), stageWidth())
}

function onPointerUp(event: PointerEvent) {
  if (startX === null) return
  const dx = event.clientX - startX
  const travel = startX
  startX = null
  if (!dragging) return
  swiped = true
  dragging = false
  const progress = dragProgress(dx, travel)
  if (shouldTurn(dx, progress, velocity, current.value, props.urls.length)) {
    finish(dx < 0 ? -1 : 1, progress)
    return
  }
  // 取消：交给 CSS 过渡回弹归位。
  scrub.value = null
}

function onPointerCancel() {
  // 系统滚动接管时立即回弹，绝不停留在中间态。
  startX = null
  dragging = false
  scrub.value = null
}

function onClick() {
  if (swiped) {
    swiped = false
    return
  }
  emit('tap', current.value)
}

onBeforeUnmount(() => cancelAnimationFrame(frame))
</script>

<template>
  <div
    ref="stage"
    class="photo-stack"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerCancel"
    @click="onClick"
  >
    <div
      v-for="(url, index) in urls"
      :key="url + index"
      class="photo-stack-card"
      :class="{ scrubbing: scrub !== null }"
      :style="{
        transform: `translateX(${states[index].x}px) rotate(${states[index].rotate}deg) scale(${states[index].scale})`,
        zIndex: states[index].zIndex,
        opacity: states[index].opacity,
      }"
    >
      <img :src="url" alt="" draggable="false" />
    </div>
  </div>
</template>
