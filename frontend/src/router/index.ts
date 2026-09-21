// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import { useAuthStore } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/chat', name: 'chat', component: ChatView, meta: { requiresAuth: true } },
    { path: '/chat/:id', name: 'chat-with-id', component: ChatView, meta: { requiresAuth: true } },
    // 知识图谱：懒加载（echarts ~1MB，避免拖慢聊天首屏）
    { path: '/graph', name: 'graph', component: () => import('@/views/GraphView.vue'), meta: { requiresAuth: true } },
    { path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.ensureLoaded()
  if (to.meta.requiresAuth && !auth.user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) return { name: 'chat' }
  if (to.name === 'login' && auth.user) return { name: 'chat' }
  return true
})
