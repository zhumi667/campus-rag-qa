import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getToken, clearToken } from './token'

// 后端基地址（固定 8000，前端 5173；后端 CORS 已允许 5173）
export const API_BASE = 'http://127.0.0.1:8000'

export const http = axios.create({ baseURL: API_BASE, timeout: 15000 })

// 请求拦截器：自动加 Authorization
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401 清 token 跳登录；403 提示无权限
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    // ★ 登录接口自身的 401 表示"用户名或密码错误"，属于预期内的业务错误，
    //   交给调用方展示提示即可。若走下面的清 token + 跳转逻辑，
    //   会额外触发一次页面跳转，把错误提示冲掉。
    const isLoginRequest = url.includes('/api/auth/login')

    if (status === 401 && !isLoginRequest) {
      clearToken()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    } else if (status === 403) {
      ElMessage.warning('无权限访问该资源')
    }
    return Promise.reject(error)
  },
)

export async function fetchHealth() {
  const { data } = await http.get('/api/health')
  return data
}

export async function listSessions() {
  const { data } = await http.get('/api/sessions')
  return data
}

export async function createSession(title = '') {
  const { data } = await http.post('/api/sessions', { title })
  return data
}

export async function getMessages(sessionId) {
  const { data } = await http.get(`/api/sessions/${sessionId}/messages`)
  return data
}

export async function deleteSession(sessionId) {
  await http.delete(`/api/sessions/${sessionId}`)
}

/** 已收录取材清单（学生可见，只返回标题/版本/生效日期/字数） */
export async function fetchCorpusDocs() {
  const { data } = await http.get('/api/corpus/docs')
  return data
}
