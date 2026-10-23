import { http } from './client'
import { setToken, clearToken } from './token'

export async function login(username, password) {
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
