import { createApp } from 'vue'
import App from './App.vue'
import { activePwaBuildInfo } from './buildInfo'
import './styles.css'

const app = createApp(App)

// 消息行自己带 onErrorCaptured，坏一条不会牵连整棵树；这里兜住剩下的（壳、弹层、
// watcher）。Vue 默认只往 console 打一行然后卸载组件树——装成 PWA 的手机上看不到
// console，界面直接变白，没有任何线索。至少让它留下一句话。
app.config.errorHandler = (error, _instance, info) => {
  console.error(`[PWA] 渲染或逻辑异常（${info}）`, error)
}

app.mount('#app')

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  const hadController = Boolean(navigator.serviceWorker.controller)
  if (hadController) {
    // An installed PWA can keep the old app alive after the new worker claims it.
    // Reload once on takeover so the current page actually uses the new bundle.
    navigator.serviceWorker.addEventListener('controllerchange', () => window.location.reload(), { once: true })
  }
  window.addEventListener('load', () => {
    const workerUrl = `${import.meta.env.BASE_URL}sw.js?build=${encodeURIComponent(activePwaBuildInfo.buildId)}`
    navigator.serviceWorker.register(workerUrl).catch(() => undefined)
  })
}
