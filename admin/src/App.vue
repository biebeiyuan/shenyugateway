<script setup lang="ts">
import { computed } from 'vue'
import { NConfigProvider, NMessageProvider, NNotificationProvider, darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppShell from '@/components/AppShell.vue'
import { useTheme } from '@/theme/theme'

const { theme } = useTheme()
const naiveTheme = computed(() => (theme.value === 'night' ? darkTheme : null))

// 与设计 token 同源（theme/tokens.css）：昼 = 软玫瑰粉主色、金只画线，夜 = 古金。
const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const night = theme.value === 'night'
  return {
    common: {
      primaryColor: night ? '#c19a56' : '#c094a8',
      primaryColorHover: night ? '#d1aa62' : '#b08898',
      primaryColorPressed: night ? '#9b7c45' : '#a07888',
      primaryColorSuppl: night ? '#c19a56' : '#c094a8',
      successColor: night ? '#8a9b6e' : '#a8c4a0',
      successColorHover: night ? '#99ab7d' : '#98b490',
      successColorPressed: night ? '#75875b' : '#88a480',
      warningColor: '#c8956a',
      warningColorHover: '#b8855a',
      errorColor: '#d4726a',
      errorColorHover: '#c4625a',
      borderColor: night ? 'rgba(193,154,86,0.28)' : 'rgba(192,148,168,0.32)',
      borderRadius: '10px',
    },
  }
})
</script>

<template>
  <NConfigProvider :locale="null" :theme="naiveTheme" :theme-overrides="themeOverrides">
    <NNotificationProvider>
      <NMessageProvider>
        <AppShell>
          <router-view />
        </AppShell>
      </NMessageProvider>
    </NNotificationProvider>
  </NConfigProvider>
</template>
