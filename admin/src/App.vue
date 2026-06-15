<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NNotificationProvider } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppShell from '@/components/AppShell.vue'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#c094a8',
    primaryColorHover: '#b08898',
    primaryColorPressed: '#a07888',
    primaryColorSuppl: '#c094a8',
    successColor: '#a8c4a0',
    successColorHover: '#98b490',
    successColorPressed: '#88a480',
    warningColor: '#c8956a',
    warningColorHover: '#b8855a',
    errorColor: '#d4726a',
    errorColorHover: '#c4625a',
    borderColor: '#f2ddd8',
    borderRadius: '10px',
  },
}
</script>

<template>
  <NConfigProvider :locale="null" :theme-overrides="themeOverrides">
    <NNotificationProvider>
      <NMessageProvider>
        <AppShell>
          <router-view />
        </AppShell>
      </NMessageProvider>
    </NNotificationProvider>
  </NConfigProvider>
</template>
