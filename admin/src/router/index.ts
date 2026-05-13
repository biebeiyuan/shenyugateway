import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'config',
      component: () => import('@/views/ConfigView.vue'),
    },
    {
      path: '/sessions',
      name: 'sessions',
      component: () => import('@/views/SessionsView.vue'),
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('@/views/CalendarView.vue'),
    },
    {
      path: '/mem0',
      name: 'mem0',
      component: () => import('@/views/Mem0View.vue'),
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('@/views/LogsView.vue'),
    },
    {
      path: '/hisense',
      name: 'hisense',
      component: () => import('@/views/HisenseView.vue'),
    },
  ],
})

export default router
