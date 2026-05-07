<script setup lang="ts">
import { NConfigProvider, NMessageProvider } from 'naive-ui'
import AppShell from '@/components/AppShell.vue'
</script>

<template>
  <NConfigProvider :locale="null">
    <NMessageProvider>
      <AppShell>
        <router-view />
      </AppShell>
    </NMessageProvider>
  </NConfigProvider>
</template>
