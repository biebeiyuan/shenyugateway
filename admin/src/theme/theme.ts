// 昼夜主题切换：给 <html> 换 data-theme，选择存 localStorage。
// 布局不动、只换色（见 tokens.css），naive-ui 组件色与自绘 token 同源。

import { ref, type Ref } from 'vue'

export type SyTheme = 'day' | 'night'

const STORAGE_KEY = 'shenyu-admin-theme'

function readInitial(): SyTheme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'day' || saved === 'night') return saved
  } catch {
    /* localStorage 不可用时退回昼 */
  }
  return 'day'
}

const current: Ref<SyTheme> = ref(readInitial())

function apply(theme: SyTheme) {
  const root = document.documentElement
  if (theme === 'night') root.setAttribute('data-theme', 'night')
  else root.removeAttribute('data-theme')
}

export function useTheme() {
  function set(theme: SyTheme) {
    current.value = theme
    apply(theme)
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* 忽略持久化失败，切换仍然生效 */
    }
  }
  function toggle() {
    set(current.value === 'night' ? 'day' : 'night')
  }
  return { theme: current, set, toggle }
}

// 模块加载时立即应用一次，避免首屏闪烁。
apply(current.value)
