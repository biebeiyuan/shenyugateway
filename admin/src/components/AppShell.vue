<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from '@/theme/theme'
import { isDemoMode } from '@/demo'

const route = useRoute()
const isHome = computed(() => route.path === '/')
const { theme, toggle: toggleTheme } = useTheme()
const demo = isDemoMode()

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
        <h1>沈予的家</h1>
      </RouterLink>
      <RouterLink v-if="!isHome" to="/" class="back-link">&larr; 返回</RouterLink>
      <button
        class="theme-toggle"
        :title="theme === 'night' ? '切到白天' : '切到黑夜'"
        :aria-label="theme === 'night' ? '切到白天' : '切到黑夜'"
        @click="toggleTheme"
      >{{ theme === 'night' ? '☾' : '☀' }}</button>
      <span class="live-indicator">
        <span class="dot" :class="live ? 'live' : 'off'"></span>
        {{ live ? '在线' : '离线' }}
      </span>
      <span v-if="demo" class="demo-badge" title="当前展示的是编造的演示数据，不会改动真实内容">演示数据</span>
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
/* 全局 naive-ui 昼场皮肤：只在昼生效（夜由 darkTheme + themeOverrides 接管），
   颜色一律引用设计 token，不再写死。字体改在 index.html 里加载。 */

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--sy-cjk, 'Noto Serif SC', 'Georgia', serif);
  background: var(--sy-void, #fbf4ef);
  background-image: var(--sy-bg, none);
  background-attachment: fixed;
  background-size: cover;
  color: var(--sy-ink, #4a2c2c);
  transition: background-color 0.3s, color 0.3s;
}

html:not([data-theme='night']) {
  --n-color: #fffdf8 !important;
  --n-color-modal: #fffdf8 !important;
  --n-action-color: var(--sy-void) !important;
}

html:not([data-theme='night']) .n-card {
  --n-color: #fffdf8 !important;
  --n-border-color: var(--sy-hair) !important;
  --n-title-text-color: var(--sy-ink) !important;
  --n-action-color: var(--sy-void) !important;
  --n-embedded-color: var(--sy-void) !important;
  border-radius: 18px !important;
}

html:not([data-theme='night']) .n-card-header {
  border-bottom: 1px solid var(--sy-hair) !important;
}

html:not([data-theme='night']) .n-form-item-label {
  --n-label-text-color: var(--sy-mute) !important;
}

html:not([data-theme='night']) .n-input {
  --n-color: #fffdf8 !important;
  --n-border: 1px solid var(--sy-hair) !important;
  --n-text-color: var(--sy-ink) !important;
  --n-caret-color: var(--sy-accent) !important;
  --n-color-focus: #fffdf8 !important;
  --n-border-focus: 1px solid var(--sy-accent) !important;
  --n-color-disabled: var(--sy-void) !important;
}

html:not([data-theme='night']) .n-input-number {
  --n-color: #fffdf8 !important;
  --n-border: 1px solid var(--sy-hair) !important;
  --n-text-color: var(--sy-ink) !important;
}

html:not([data-theme='night']) .n-select {
  --n-color: #fffdf8 !important;
  --n-border: 1px solid var(--sy-hair) !important;
  --n-text-color: var(--sy-ink) !important;
}

html:not([data-theme='night']) .n-select .n-base-selection {
  background: #fffdf8 !important;
}

html:not([data-theme='night']) .n-switch {
  --n-color: var(--sy-hair) !important;
  --n-color-active: var(--sy-accent) !important;
}

html:not([data-theme='night']) .n-popconfirm {
  --n-color: #fffdf8 !important;
  --n-border-color: var(--sy-hair) !important;
}

html:not([data-theme='night']) .n-tag {
  --n-color: var(--sy-rose-soft) !important;
  --n-text-color: var(--sy-mute) !important;
  --n-border: none !important;
}

html:not([data-theme='night']) .n-data-table {
  --n-color: #fffdf8 !important;
  --n-border-color: var(--sy-hair) !important;
  --n-th-color: var(--sy-void) !important;
  --n-td-color: #fffdf8 !important;
  --n-th-text-color: var(--sy-mute) !important;
  --n-td-text-color: var(--sy-ink) !important;
  --n-action-color: var(--sy-void) !important;
}

html:not([data-theme='night']) .n-data-table .n-data-table-tr--striped {
  --n-td-color: var(--sy-void) !important;
}

html:not([data-theme='night']) .n-data-table .n-data-table-th {
  border-bottom: 1px solid var(--sy-hair) !important;
}

html:not([data-theme='night']) .n-descriptions {
  --n-color: #fffdf8 !important;
  --n-border-color: var(--sy-hair) !important;
  --n-th-color: var(--sy-void) !important;
  --n-td-color: #fffdf8 !important;
  --n-th-text-color: var(--sy-mute) !important;
  --n-td-text-color: var(--sy-ink) !important;
}

html:not([data-theme='night']) .n-button--default-type {
  --n-color: #fffdf8 !important;
  --n-border: 1px solid var(--sy-hair) !important;
  --n-text-color: var(--sy-ink) !important;
  --n-color-hover: var(--sy-void) !important;
  --n-border-hover: 1px solid var(--sy-accent) !important;
}

html:not([data-theme='night']) .n-button--primary-type {
  --n-color: var(--sy-accent) !important;
  --n-text-color: #fff !important;
  --n-color-hover: var(--sy-accent-d) !important;
}

html:not([data-theme='night']) .n-button--error-type {
  --n-color: #fffdf8 !important;
  --n-border: 1px solid #d4726a !important;
  --n-text-color: #d4726a !important;
}

html:not([data-theme='night']) .n-button--warning-type {
  --n-color: #fffdf8 !important;
  --n-border: 1px solid #c8956a !important;
  --n-text-color: #c8956a !important;
}

html:not([data-theme='night']) .n-button--quaternary {
  --n-color: transparent !important;
  --n-text-color: var(--sy-mute) !important;
}

html:not([data-theme='night']) .n-layout-footer {
  --n-color: var(--sy-void) !important;
  --n-border-color: var(--sy-hair) !important;
  --n-text-color: var(--sy-faint) !important;
}

html:not([data-theme='night']) .n-popover {
  --n-color: #fffdf8 !important;
  --n-border-color: var(--sy-hair) !important;
}

::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--sy-hair, #e8d8d4);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--sy-accent, #d4c0bb);
}
</style>

<style scoped>
.header {
  padding: 14px 24px;
  background: var(--sy-paper, #fff);
  border-bottom: 0.6px solid var(--sy-hair, #f0e0dc);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  row-gap: 8px;
  transition: background-color 0.3s, border-color 0.3s;
}

.theme-toggle {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 0.6px solid var(--sy-hair, #f0e0dc);
  background: transparent;
  color: var(--sy-mute, rgba(74, 53, 53, 0.55));
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: 0.25s;
}

.theme-toggle:hover {
  background: var(--sy-rose-soft, #faf0ee);
  transform: rotate(-12deg);
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
  font-family: var(--sy-serif, 'Cormorant Garamond', 'Georgia', serif);
  font-size: 18px;
  color: var(--sy-self-d, #a07888);
  font-weight: 500;
  letter-spacing: 0.5px;
  font-style: italic;
}

.back-link {
  font-size: 12.5px;
  color: var(--sy-mute, rgba(74, 44, 44, 0.55));
  text-decoration: none;
  transition: 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}

.back-link:hover {
  color: var(--sy-accent, #c094a8);
}

.live-indicator {
  font-size: 12px;
  color: var(--sy-mute, rgba(74, 44, 44, 0.55));
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot.live {
  background: var(--sy-sage, #6f8a55);
  animation: pulse 2.5s infinite;
}

.dot.off {
  background: #d4726a;
}

.demo-badge {
  flex-shrink: 0;
  font-size: 11px;
  line-height: 1;
  padding: 4px 9px;
  border-radius: 999px;
  color: var(--sy-accent-d, #a07888);
  background: var(--sy-rose-soft, #faf0ee);
  border: 1px solid var(--sy-hair, #f0e0dc);
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
  background: var(--sy-sys-surface, #e8e4e0);
  color: var(--sy-sys-ink, #2c2c2c);
  letter-spacing: 0.3px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .header {
    padding: 10px 14px;
    gap: 10px;
  }

  .health-tags .ht:last-child {
    display: none;
  }

  .main {
    padding: 14px;
  }
}

.ht.ok {
  background: var(--sy-resident-soft, rgba(44, 74, 68, 0.1));
  color: var(--sy-resident, #2c4a44);
}

.ht.err {
  background: rgba(212, 114, 106, 0.12);
  color: #d4726a;
}

.main {
  padding: 20px 24px;
}

.main-home {
  padding: 0 16px 20px;
}
</style>
