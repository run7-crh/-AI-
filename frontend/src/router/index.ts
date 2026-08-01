// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', name: 'chat', component: ChatView },
    { path: '/chat/:id', name: 'chat-with-id', component: ChatView },
  ],
})
