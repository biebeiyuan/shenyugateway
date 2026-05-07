<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NNotificationProvider } from 'naive-ui'
import AppShell from '@/components/AppShell.vue'
</script>

<template>
  <NConfigProvider :locale="null">
    <NNotificationProvider>
      <NMessageProvider>
        <AppShell>
          <router-view />
        </AppShell>
      </NMessageProvider>
    </NNotificationProvider>
  </NConfigProvider>
</template>
