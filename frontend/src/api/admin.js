import { http, API_BASE } from './client'
import { getToken } from './token'

// ★ 预览接口要解析 PDF/Word，大文件可能超过全局的 15s 超时，单独放长
const SLOW = { timeout: 120000 }

export async function fetchAdminOverview() {
  const { data } = await http.get('/api/admin/overview')
  return data
}

export async function fetchAdminDocs() {
  const { data } = await http.get('/api/admin/docs')
  return data
}

export async function fetchImports(limit = 30) {
  const { data } = await http.get('/api/admin/imports', { params: { limit } })
  return data
}

export async function fetchStaging() {
  const { data } = await http.get('/api/admin/staging')
  return data
}

export async function discardStaging(stagingId) {
  const { data } = await http.delete(`/api/admin/staging/${stagingId}`)
  return data
}

export async function fetchAdminConfig() {
  const { data } = await http.get('/api/admin/config')
  return data
}

/** 上传语料文件（multipart）。onProgress 收到 0-100 的整数。 */
export function uploadCorpus(file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return http
    .post('/api/admin/upload', form, {
      timeout: 300000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded / e.total) * 100))
        }
      },
    })
    .then((r) => r.data)
}

/**
 * 批量上传语料文件。
 * ★ 该接口只落盘、不解析（一次传几十份时解析会把请求阻塞很久），
 *   解析由前端在"核对"步骤逐份调用 fetchPreview 完成。
 * @param {File[]} files
 * @param {(pct:number)=>void} onProgress
 */
export function uploadCorpusBatch(files, onProgress) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return http
    .post('/api/admin/upload-batch', form, {
      timeout: 600000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded / e.total) * 100))
        }
      },
    })
    .then((r) => r.data)
}

export async function fetchPreview(stagingId) {
  const { data } = await http.get(`/api/admin/preview/${stagingId}`, SLOW)
  return data
}

export async function confirmImport(stagingId, meta) {
  const { data } = await http.post(`/api/admin/confirm/${stagingId}`, meta, SLOW)
  return data
}

/**
 * 执行流水线并订阅 SSE 进度。
 * 用 fetch + ReadableStream（与 useChatStream 同方案），因为 EventSource 不能带 Authorization 头。
 *
 * @returns {Promise<void>} 流结束时 resolve；出错时 reject
 */
export async function runPipelineStream({ importId, onEvent, signal }) {
  const url = `${API_BASE}/api/admin/pipeline/stream${importId ? `?import_id=${importId}` : ''}`
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${getToken()}` },
    signal,
  })
  if (!resp.ok) {
    throw new Error(`流水线请求失败：HTTP ${resp.status}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let eventName = 'message'

  const handleBlock = (block) => {
    let dataLine = ''
    eventName = 'message'
    for (const raw of block.split('\n')) {
      const line = raw.trimEnd()
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLine += line.slice(5).trim()
      }
    }
    if (!dataLine) return
    let payload
    try {
      payload = JSON.parse(dataLine)
    } catch {
      payload = { message: dataLine }
    }
    onEvent?.({ event: eventName, ...payload })
  }

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // 兼容 \n\n 与 \r\n\r\n
    let idx
    while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx).replace(/^\r?\n\r?\n/, '')
      if (block.trim()) handleBlock(block)
    }
  }
  if (buf.trim()) handleBlock(buf)
}

export function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}
