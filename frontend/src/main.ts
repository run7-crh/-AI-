import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useAuthStore } from './stores/auth'
import './style.css'
import 'highlight.js/styles/github.css'

const pinia = createPinia()
window.addEventListener('auth-expired', () => {
  useAuthStore(pinia).clear()
  if (router.currentRoute.value.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})
createApp(App).use(pinia).use(router).mount('#app')
