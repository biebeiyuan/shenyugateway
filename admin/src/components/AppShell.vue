<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

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
    <header class="header">
      <h1>UwU</h1>
      <span class="live-indicator">
        <span class="dot" :class="live ? 'live' : 'off'"></span>
        {{ live ? '在线' : '离线' }}
      </span>
      <div class="health-tags">
        <span class="ht" :class="health.supabase ? 'ok' : 'err'">
          Supabase {{ health.supabase ? '正常' : '异常' }}
        </span>
        <span class="ht ok">{{ health.protocol }}</span>
        <span class="ht">{{ health.upstream }}</span>
      </div>
    </header>

    <nav class="tabs">
      <RouterLink to="/" class="tab" active-class="active">配置</RouterLink>
      <RouterLink to="/sessions" class="tab" active-class="active">线程</RouterLink>
      <RouterLink to="/logs" class="tab" active-class="active">日志</RouterLink>
      <RouterLink to="/calendar" class="tab" active-class="active">日历</RouterLink>
      <RouterLink to="/mem0" class="tab" active-class="active">记忆</RouterLink>
      <RouterLink to="/hisense" class="tab" active-class="active">海信</RouterLink>
    </nav>

    <main class="main">
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

body {
  font-family: -apple-system, 'Segoe UI', sans-serif;
  background: #faf8f5;
  color: #3d3535;
}

:root {
  --n-color: #fff !important;
  --n-color-modal: #fff !important;
  --n-action-color: #faf9f7 !important;
}

.n-card {
  --n-color: #fff !important;
  --n-border-color: #f0ece8 !important;
  --n-title-text-color: #3d3535 !important;
  --n-action-color: #faf9f7 !important;
  --n-embedded-color: #faf9f7 !important;
  border-radius: 14px !important;
}

.n-card-header {
  border-bottom: 1px solid #f0ece8 !important;
}

.n-form-item-label {
  --n-label-text-color: #888 !important;
}

.n-input {
  --n-color: #fff !important;
  --n-border: 1px solid #e8e4df !important;
  --n-text-color: #3d3535 !important;
  --n-caret-color: #9b8ec4 !important;
  --n-color-focus: #fff !important;
  --n-border-focus: 1px solid #9b8ec4 !important;
  --n-color-disabled: #faf8f5 !important;
}

.n-input-number {
  --n-color: #fff !important;
  --n-border: 1px solid #e8e4df !important;
  --n-text-color: #3d3535 !important;
}

.n-select {
  --n-color: #fff !important;
  --n-border: 1px solid #e8e4df !important;
  --n-text-color: #3d3535 !important;
}

.n-select .n-base-selection {
  background: #fff !important;
}

.n-switch {
  --n-color: #e0dbd6 !important;
  --n-color-active: #9b8ec4 !important;
}

.n-popconfirm {
  --n-color: #fff !important;
  --n-border-color: #e8e4df !important;
}

.n-tag {
  --n-color: #f5f2ef !important;
  --n-text-color: #888 !important;
  --n-border: none !important;
}

.n-data-table {
  --n-color: #fff !important;
  --n-border-color: #f0ece8 !important;
  --n-th-color: #faf9f7 !important;
  --n-td-color: #fff !important;
  --n-th-text-color: #888 !important;
  --n-td-text-color: #3d3535 !important;
  --n-action-color: #faf9f7 !important;
}

.n-data-table .n-data-table-tr--striped {
  --n-td-color: #faf9f7 !important;
}

.n-data-table .n-data-table-th {
  border-bottom: 1px solid #f0ece8 !important;
}

.n-descriptions {
  --n-color: #fff !important;
  --n-border-color: #f0ece8 !important;
  --n-th-color: #faf9f7 !important;
  --n-td-color: #fff !important;
  --n-th-text-color: #888 !important;
  --n-td-text-color: #3d3535 !important;
}

.n-button--default-type {
  --n-color: #fff !important;
  --n-border: 1px solid #e8e4df !important;
  --n-text-color: #3d3535 !important;
  --n-color-hover: #faf8f5 !important;
  --n-border-hover: 1px solid #9b8ec4 !important;
}

.n-button--primary-type {
  --n-color: #9b8ec4 !important;
  --n-text-color: #fff !important;
  --n-color-hover: #8b7eb8 !important;
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
  --n-text-color: #999 !important;
}

.n-layout-footer {
  --n-color: #faf9f7 !important;
  --n-border-color: #f0ece8 !important;
  --n-text-color: #bbb !important;
}

.n-popover {
  --n-color: #fff !important;
  --n-border-color: #e8e4df !important;
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: #e0dbd6;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: #c8c2bb;
}
</style>

<style scoped>
.header {
  padding: 14px 24px;
  background: #fff;
  border-bottom: 1px solid #f0ece8;
  display: flex;
  align-items: center;
  gap: 16px;
}

.header h1 {
  font-size: 18px;
  color: #9b8ec4;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.live-indicator {
  font-size: 12px;
  color: #b0a8a0;
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
  background: #8bc49b;
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
  background: #f5f2ef;
  color: #b0a8a0;
  letter-spacing: 0.3px;
}

.ht.ok {
  background: #eef6f0;
  color: #5a9a6a;
}

.ht.err {
  background: #fdf2f0;
  color: #d4726a;
}

.tabs {
  display: flex;
  background: #fff;
  border-bottom: 1px solid #f0ece8;
  padding: 0 24px;
  gap: 0;
}

.tab {
  padding: 11px 18px;
  font-size: 12.5px;
  color: #b0a8a0;
  cursor: pointer;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: 0.2s;
  letter-spacing: 0.3px;
}

.tab:hover {
  color: #3d3535;
}

.tab.active {
  color: #9b8ec4;
  border-bottom-color: #9b8ec4;
}

.main {
  padding: 20px 24px;
}
</style>
