import { http } from './client'
import { setToken, clearToken } from './token'

export async function login(username, password) {
  // ★ 登录前先清掉可能残留的旧令牌：
  //   ① 否则这次登录请求会带上一个已失效的 Authorization 头；
  //   ② 残留令牌会让路由守卫误判"已登录"，跳进首页后立刻被 401 踢回登录页，
  //      表现为"第一次登录进不去，第二次才成功"。
  clearToken()
  const { data } = await http.post('/api/auth/login', { username, password })
  setToken(data.token)
  return data
}

export async function logout() {
  try {
    await http.post('/api/auth/logout')
  } finally {
    clearToken()
  }
}

export async function fetchMe() {
  const { data } = await http.get('/api/auth/me')
  return data
}
