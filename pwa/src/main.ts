import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'

createApp(App).mount('#app')

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  const hadController = Boolean(navigator.serviceWorker.controller)
  if (hadController) {
    // An installed PWA can keep the old app alive after the new worker claims it.
    // Reload once on takeover so the current page actually uses the new bundle.
    navigator.serviceWorker.addEventListener('controllerchange', () => window.location.reload(), { once: true })
  }
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => undefined)
  })
}
