import { createRouter, createWebHistory } from 'vue-router'
import ExpenseListView from '../views/ExpenseListView.vue'
import LoginView from '../views/LoginView.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { public: true },
  },
  {
    path: '/',
    name: 'ExpenseList',
    component: ExpenseListView,
  },
  {
    path: '/roster',
    name: 'roster',
    component: () => import('@/views/RosterView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Navigation Guard：未登入則導向 /login
router.beforeEach((to) => {
  const isPublic = to.meta.public === true
  const hasToken = !!localStorage.getItem('acctassist_token')
  if (!isPublic && !hasToken) return { name: 'Login' }
})

export default router
