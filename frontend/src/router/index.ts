// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', name: 'chat', component: ChatView },
    { path: '/chat/:id', name: 'chat-with-id', component: ChatView },
    // 知识图谱：懒加载（echarts ~1MB，避免拖慢聊天首屏）
    { path: '/graph', name: 'graph', component: () => import('@/views/GraphView.vue') },
  ],
})
