/**
 * src/api/token.js — 令牌存储（会话级）
 *
 * ★ 为什么用 sessionStorage 而不是 localStorage：
 *   localStorage 是【持久化】的 —— 关闭浏览器、重启电脑后令牌仍在，
 *   在机房、演示机等公共设备上会留下可用的登录凭据。
 *   sessionStorage 的生命周期绑定到【标签页会话】：
 *   关闭标签页或浏览器即自动清空，重新打开需重新登录。
 *
 * ★ 副作用（有意为之）：
 *   sessionStorage 按标签页隔离，因此在新标签页打开系统需要重新登录；
 *   同一标签页内刷新、前进后退不受影响。校园问答场景下这个代价可接受。
 *
 * ★ 令牌本身仍由后端 tokens 表管理（7 天 TTL），
 *   这里的存储策略只决定【浏览器侧保留多久】，两者互相独立。
 */
const KEY = 'campus_rag_token'

export function getToken() {
  return sessionStorage.getItem(KEY)
}

export function setToken(token) {
  sessionStorage.setItem(KEY, token)
}

export function clearToken() {
  sessionStorage.removeItem(KEY)
}

/** 兼容旧版：清理此前残留在 localStorage 里的令牌（切换存储方式后调用一次） */
export function purgeLegacyToken() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略 */
  }
}
