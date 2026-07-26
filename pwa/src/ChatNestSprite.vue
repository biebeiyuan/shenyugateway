<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CHATNEST_STATUS_SPRITES } from './chatnestSprite'

type SpriteMode = keyof typeof CHATNEST_STATUS_SPRITES

const props = defineProps<{ mode: SpriteMode }>()

const track = ref<HTMLElement | null>(null)
let animation: Animation | null = null
let activeMode: SpriteMode | null = null
let animationGeneration = 0

function play(mode: SpriteMode, speedOverride?: number) {
  const target = track.value
  const sprite = CHATNEST_STATUS_SPRITES[mode]
  if (!target || !sprite) return

  animationGeneration += 1
  const generation = animationGeneration
  activeMode = mode
  animation?.cancel()
  target.innerHTML = sprite.svg

  if (sprite.frameCount <= 1) return

  const frames = Array.from({ length: sprite.frameCount }, (_, index) => ({
    transform: `translateY(-${index * (100 / sprite.frameCount)}%)`,
  }))
  animation = target.animate(frames, {
    duration: (speedOverride || sprite.speed) * sprite.frameCount,
    iterations: sprite.loop ? Infinity : 1,
    easing: `steps(${sprite.frameCount}, jump-none)`,
  })

  if (!sprite.loop && mode === 'entrance') {
    animation.finished.then(() => {
      if (generation === animationGeneration && activeMode === mode) play('tickle')
    }).catch(() => {})
  }
}

watch(() => props.mode, (mode) => play(mode))
onMounted(() => play(props.mode))
onBeforeUnmount(() => {
  animationGeneration += 1
  animation?.cancel()
})
</script>

<template>
  <div class="assistant-trail" :data-mode="mode">
    <span class="assistant-sprite-viewport">
      <span ref="track" class="assistant-sprite-track" />
    </span>
  </div>
</template>
