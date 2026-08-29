import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  // 消息行的渲染护栏（坏一条不牵连整棵树）只能挂着真组件测，所以单测也要能编
  // .vue。这个插件已经是 PWA 构建的依赖，不是为测试新引进来的。
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.spec.ts'],
  },
})
