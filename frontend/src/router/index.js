import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getToken } from '../api/token'
import { fetchMe } from '../api/auth'

const routes = [
  { path: '/login', component: () => import('../views/LoginView.vue') },
  { path: '/', component: () => import('../views/ChatView.vue'), meta: { requiresAuth: true } },
  { path: '/admin', component: () => import('../views/AdminView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const token = getToken()

  // 未登录访问受保护路由 → 跳登录并记录 redirect
  if (to.meta.requiresAuth && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 已登录访问登录页 → 跳首页
  if (to.path === '/login' && token) {
    return { path: '/' }
  }

  // 管理页需 admin 角色（接口级校验在后端，这里仅做前端跳转）
  if (to.meta.requiresAdmin) {
    try {
      const user = await fetchMe()
      if (user.role !== 'admin') {
        ElMessage.warning('无权限访问管理后台')
        return { path: '/' }
      }
    } catch (e) {
      return { path: '/login' }
    }
  }

  return true
})

export default router
