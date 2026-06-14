<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isHome = computed(() => route.path === '/')

const health = ref({ supabase: false, protocol: '', upstream: '' })
const live = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await checkHealth()
  timer = setInterval(checkHealth, 15000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function checkHealth() {
  try {
    const r = await fetch('/health')
    const h = await r.json()
    health.value = h
    live.value = true
  } catch {
    live.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <header class="header" :class="{ 'header-minimal': isHome }">
      <RouterLink to="/" class="header-home">
        <h1>UwU</h1>
      </RouterLink>
      <RouterLink v-if="!isHome" to="/" class="back-link">&larr; 返回</RouterLink>
      <span class="live-indicator">
        <span class="dot" :class="live ? 'live' : 'off'"></span>
        {{ live ? '在线' : '离线' }}
      </span>
      <div v-if="!isHome" class="health-tags">
        <span class="ht" :class="health.supabase ? 'ok' : 'err'">
          Supabase {{ health.supabase ? '正常' : '异常' }}
        </span>
        <span class="ht ok">{{ health.protocol }}</span>
        <span class="ht">{{ health.upstream }}</span>
      </div>
    </header>

    <main class="main" :class="{ 'main-home': isHome }">
      <slot />
    </main>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,400;1,500&display=swap');

body {
  font-family: 'Georgia', 'Noto Serif SC', -apple-system, 'Segoe UI', serif;
  background: #fdf6f4;
  color: #4a3535;
}

:root {
  --n-color: #fff !important;
  --n-color-modal: #fff !important;
  --n-action-color: #fdf6f4 !important;
}

.n-card {
  --n-color: #fff !important;
  --n-border-color: #f2ddd8 !important;
  --n-title-text-color: #4a3535 !important;
  --n-action-color: #fdf6f4 !important;
  --n-embedded-color: #fdf6f4 !important;
  border-radius: 18px !important;
}

.n-card-header {
  border-bottom: 1px solid #f2ddd8 !important;
}

.n-form-item-label {
  --n-label-text-color: #b8a8a3 !important;
}

.n-input {
  --n-color: #fff !important;
  --n-border: 1px solid #f2ddd8 !important;
  --n-text-color: #4a3535 !important;
  --n-caret-color: #c094a8 !important;
  --n-color-focus: #fff !important;
  --n-border-focus: 1px solid #c094a8 !important;
  --n-color-disabled: #fdf6f4 !important;
}

.n-input-number {
  --n-color: #fff !important;
  --n-border: 1px solid #f2ddd8 !important;
  --n-text-color: #4a3535 !important;
}

.n-select {
  --n-color: #fff !important;
  --n-border: 1px solid #f2ddd8 !important;
  --n-text-color: #4a3535 !important;
}

.n-select .n-base-selection {
  background: #fff !important;
}

.n-switch {
  --n-color: #e8d8d4 !important;
  --n-color-active: #c094a8 !important;
}

.n-popconfirm {
  --n-color: #fff !important;
  --n-border-color: #f2ddd8 !important;
}

.n-tag {
  --n-color: #fdf0ed !important;
  --n-text-color: #b8a8a3 !important;
  --n-border: none !important;
}

.n-data-table {
  --n-color: #fff !important;
  --n-border-color: #f2ddd8 !important;
  --n-th-color: #fdf6f4 !important;
  --n-td-color: #fff !important;
  --n-th-text-color: #b8a8a3 !important;
  --n-td-text-color: #4a3535 !important;
  --n-action-color: #fdf6f4 !important;
}

.n-data-table .n-data-table-tr--striped {
  --n-td-color: #fdf6f4 !important;
}

.n-data-table .n-data-table-th {
  border-bottom: 1px solid #f2ddd8 !important;
}

.n-descriptions {
  --n-color: #fff !important;
  --n-border-color: #f2ddd8 !important;
  --n-th-color: #fdf6f4 !important;
  --n-td-color: #fff !important;
  --n-th-text-color: #b8a8a3 !important;
  --n-td-text-color: #4a3535 !important;
}

.n-button--default-type {
  --n-color: #fff !important;
  --n-border: 1px solid #f2ddd8 !important;
  --n-text-color: #4a3535 !important;
  --n-color-hover: #fdf6f4 !important;
  --n-border-hover: 1px solid #c094a8 !important;
}

.n-button--primary-type {
  --n-color: #c094a8 !important;
  --n-text-color: #fff !important;
  --n-color-hover: #b08898 !important;
}

.n-button--error-type {
  --n-color: #fff !important;
  --n-border: 1px solid #d4726a !important;
  --n-text-color: #d4726a !important;
}

.n-button--warning-type {
  --n-color: #fff !important;
  --n-border: 1px solid #c8956a !important;
  --n-text-color: #c8956a !important;
}

.n-button--quaternary {
  --n-color: transparent !important;
  --n-text-color: #b8a8a3 !important;
}

.n-layout-footer {
  --n-color: #fdf6f4 !important;
  --n-border-color: #f2ddd8 !important;
  --n-text-color: #cbb !important;
}

.n-popover {
  --n-color: #fff !important;
  --n-border-color: #f2ddd8 !important;
}

::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: #e8d8d4;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: #d4c0bb;
}
</style>

<style scoped>
.header {
  padding: 14px 24px;
  background: #fff;
  border-bottom: 1px solid #f0e0dc;
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-minimal {
  background: transparent;
  border-bottom: none;
  padding: 10px 24px;
}

.header-home {
  text-decoration: none;
}

.header h1 {
  font-family: 'Cormorant Garamond', 'Georgia', serif;
  font-size: 18px;
  color: #a08090;
  font-weight: 500;
  letter-spacing: 0.5px;
  font-style: italic;
}

.back-link {
  font-size: 12.5px;
  color: #c4b0ab;
  text-decoration: none;
  transition: 0.2s;
}

.back-link:hover {
  color: #c094a8;
}

.live-indicator {
  font-size: 12px;
  color: #c4b0ab;
  display: flex;
  align-items: center;
  gap: 4px;
}

.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot.live {
  background: #a8c4a0;
  animation: pulse 2.5s infinite;
}

.dot.off {
  background: #d4726a;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.health-tags {
  display: flex;
  gap: 6px;
  margin-left: auto;
  flex-wrap: wrap;
}

.ht {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 10px;
  background: #fdf0ed;
  color: #c4b0ab;
  letter-spacing: 0.3px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
}

.ht.ok {
  background: #eef6f0;
  color: #5a9a6a;
}

.ht.err {
  background: #fdf2f0;
  color: #d4726a;
}

.main {
  padding: 20px 24px;
}

.main-home {
  padding: 0 16px 20px;
}
</style>
