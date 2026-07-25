import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/chat/',
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/v1': 'http://localhost:8010',
      '/api': 'http://localhost:8010',
      '/health': 'http://localhost:8010',
      '/admin': 'http://localhost:8010',
    },
  },
})
