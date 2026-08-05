<script setup lang="ts">
import { computed } from 'vue'
import { NConfigProvider, NMessageProvider, NNotificationProvider, darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppShell from '@/components/AppShell.vue'
import { useTheme } from '@/theme/theme'

const { theme } = useTheme()
const naiveTheme = computed(() => (theme.value === 'night' ? darkTheme : null))

// 与设计 token 同源（theme/tokens.css）：昼 = 玫瑰红主色，夜 = 古金主色。
const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const night = theme.value === 'night'
  return {
    common: {
      primaryColor: night ? '#c19a56' : '#a8505e',
      primaryColorHover: night ? '#d1aa62' : '#b8606d',
      primaryColorPressed: night ? '#9b7c45' : '#8a3a48',
      primaryColorSuppl: night ? '#c19a56' : '#a8505e',
      successColor: night ? '#8a9b6e' : '#6f8a55',
      successColorHover: night ? '#99ab7d' : '#7f9b64',
      successColorPressed: night ? '#75875b' : '#5d7749',
      warningColor: '#c8956a',
      warningColorHover: '#b8855a',
      errorColor: '#d4726a',
      errorColorHover: '#c4625a',
      borderColor: night ? 'rgba(193,154,86,0.28)' : 'rgba(168,80,94,0.22)',
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
