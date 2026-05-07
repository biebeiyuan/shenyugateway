<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

const health = ref({ supabase: false, protocol: '', upstream: '', models: [] as string[] })
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
      <h1>沈予网关</h1>
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
      <RouterLink to="/" class="tab" active-class="active">配置管理</RouterLink>
      <RouterLink to="/sessions" class="tab" active-class="active">线程管理</RouterLink>
      <RouterLink to="/logs" class="tab" active-class="active">请求日志</RouterLink>
      <RouterLink to="/calendar" class="tab" active-class="active">日历记忆</RouterLink>
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
  background: #f5f5f5;
  color: #1f1f1f;
}

/* naive-ui global overrides: light clean */
:root {
  --n-color: #fff !important;
  --n-color-modal: #fff !important;
  --n-action-color: #fafafa !important;
}

.n-card {
  --n-color: #fff !important;
  --n-border-color: #e8e8e8 !important;
  --n-title-text-color: #1f1f1f !important;
  --n-action-color: #fafafa !important;
  --n-embedded-color: #fafafa !important;
}

.n-card-header {
  border-bottom: 1px solid #e8e8e8 !important;
}

.n-form-item-label {
  --n-label-text-color: #666 !important;
}

.n-input {
  --n-color: #fff !important;
  --n-border: 1px solid #e0e0e0 !important;
  --n-text-color: #1f1f1f !important;
  --n-caret-color: #4f46e5 !important;
  --n-color-focus: #fff !important;
  --n-border-focus: 1px solid #4f46e5 !important;
  --n-color-disabled: #f5f5f5 !important;
}

.n-input-number {
  --n-color: #fff !important;
  --n-border: 1px solid #e0e0e0 !important;
  --n-text-color: #1f1f1f !important;
}

.n-select {
  --n-color: #fff !important;
  --n-border: 1px solid #e0e0e0 !important;
  --n-text-color: #1f1f1f !important;
}

.n-select .n-base-selection {
  background: #fff !important;
}

.n-switch {
  --n-color: #d0d0d0 !important;
  --n-color-active: #4f46e5 !important;
}

.n-popconfirm {
  --n-color: #fff !important;
  --n-border-color: #e0e0e0 !important;
}

.n-tag {
  --n-color: #f0f0f0 !important;
  --n-text-color: #666 !important;
  --n-border: none !important;
}

.n-data-table {
  --n-color: #fff !important;
  --n-border-color: #e8e8e8 !important;
  --n-th-color: #fafafa !important;
  --n-td-color: #fff !important;
  --n-th-text-color: #666 !important;
  --n-td-text-color: #1f1f1f !important;
  --n-action-color: #fafafa !important;
}

.n-data-table .n-data-table-tr--striped {
  --n-td-color: #fafafa !important;
}

.n-data-table .n-data-table-th {
  border-bottom: 1px solid #e8e8e8 !important;
}

.n-descriptions {
  --n-color: #fff !important;
  --n-border-color: #e8e8e8 !important;
  --n-th-color: #fafafa !important;
  --n-td-color: #fff !important;
  --n-th-text-color: #666 !important;
  --n-td-text-color: #1f1f1f !important;
}

.n-button--default-type {
  --n-color: #fff !important;
  --n-border: 1px solid #e0e0e0 !important;
  --n-text-color: #1f1f1f !important;
  --n-color-hover: #f5f5f5 !important;
  --n-border-hover: 1px solid #4f46e5 !important;
}

.n-button--primary-type {
  --n-color: #4f46e5 !important;
  --n-text-color: #fff !important;
  --n-color-hover: #4338ca !important;
}

.n-button--error-type {
  --n-color: #fff !important;
  --n-border: 1px solid #e53e3e !important;
  --n-text-color: #e53e3e !important;
}

.n-button--warning-type {
  --n-color: #fff !important;
  --n-border: 1px solid #d97706 !important;
  --n-text-color: #d97706 !important;
}

.n-button--quaternary {
  --n-color: transparent !important;
  --n-text-color: #666 !important;
}

.n-layout-footer {
  --n-color: #fafafa !important;
  --n-border-color: #e8e8e8 !important;
  --n-text-color: #999 !important;
}

.n-popover {
  --n-color: #fff !important;
  --n-border-color: #e0e0e0 !important;
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f5f5f5;
}

::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: #b0b0b0;
}
</style>

<style scoped>
.header {
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  gap: 16px;
}

.header h1 {
  font-size: 17px;
  color: #4f46e5;
}

.live-indicator {
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 4px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot.live {
  background: #22c55e;
  animation: pulse 2s infinite;
}

.dot.off {
  background: #e53e3e;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
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
  font-size: 11px;
  background: #f0f0f0;
  color: #666;
}

.ht.ok {
  background: #dcfce7;
  color: #16a34a;
}

.ht.err {
  background: #fef2f2;
  color: #e53e3e;
}

.tabs {
  display: flex;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  padding: 0 24px;
  gap: 0;
}

.tab {
  padding: 10px 20px;
  font-size: 13px;
  color: #999;
  cursor: pointer;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: 0.2s;
}

.tab:hover {
  color: #1f1f1f;
}

.tab.active {
  color: #4f46e5;
  border-bottom-color: #4f46e5;
}

.main {
  padding: 16px 24px;
}
</style>
