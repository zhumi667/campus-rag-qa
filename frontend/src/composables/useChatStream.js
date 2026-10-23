import { ref } from 'vue'
import { API_BASE } from '../api/client'
import { getToken } from '../api/token'

/**
 * SSE 流式问答（核心逻辑）。
 * 后端是 POST 接口，故用 fetch + ReadableStream 手工解析，不用 EventSource。
 *
 * 关键：SSE 帧可能在任意字节处被 TCP/网络切断，必须用缓冲区累积，
 * 按 "\n\n" 分割出【完整帧】后再解析，否则长回答会丢字或 JSON.parse 报错。
 */
export function useChatStream() {
  const streaming = ref(false)
  const answer = ref('')
  const sources = ref([])
  const retrieved = ref([])
  const refused = ref(false)
  const judge = ref(null)
  const timing = ref({ retrieve: 0, judge: 0, generate: 0, total: 0 })
  const error = ref('')

  let controller = null

  function reset() {
    answer.value = ''
    sources.value = []
    retrieved.value = []
    refused.value = false
    judge.value = null
    timing.value = { retrieve: 0, judge: 0, generate: 0, total: 0 }
    error.value = ''
  }

  /** 找帧分隔符：后端 sse-starlette 用 \r\n\r\n，兼容 \n\n */
  function findSep(s) {
    const a = s.indexOf('\r\n\r\n')
    const b = s.indexOf('\n\n')
    if (a === -1 && b === -1) return null
    if (a === -1) return { index: b, length: 2 }
    if (b === -1) return { index: a, length: 4 }
    return a <= b ? { index: a, length: 4 } : { index: b, length: 2 }
  }

  /** 解析一个完整帧（raw 形如 "event: meta\ndata: {...}"） */
  function handleFrame(raw) {
    let event = ''
    let data = ''
    for (const line of raw.split('\n')) {
      const t = line.trim()
      if (t.startsWith('event:')) {
        event = t.slice(6).trim()
      } else if (t.startsWith('data:')) {
        data = t.slice(5).trim()
      }
    }
    if (!data) return

    let obj
    try {
      obj = JSON.parse(data)
    } catch (e) {
      error.value = `SSE 解析失败: ${e.message}`
      return
    }

    switch (event) {
      case 'meta':
        sources.value = obj.sources || []
        retrieved.value = obj.retrieved || []
        refused.value = !!obj.refused
        judge.value = obj.judge || null
        timing.value = {
          retrieve: obj.timing?.retrieve ?? 0,
          judge: obj.timing?.judge ?? 0,
          generate: obj.timing?.generate ?? 0,
          total: 0,
        }
        break
      case 'token':
        answer.value += obj.text || ''
        break
      case 'refused_override':
        // 判定器放行、但生成模型自己输出了拒答话术 → 后端在流末尾纠正为拒答。
        // 此时已发出的 token 无法撤回，故用后端给的规范话术覆盖，并清空引用
        // （没有答案就没有引用依据）。
        refused.value = true
        answer.value = obj.answer || '知识库中未找到相关依据。建议咨询学校相关部门获取准确信息。'
        sources.value = []
        if (judge.value) judge.value.stage = obj.refuse_stage || 'post_refuse'
        break
      case 'done':
        timing.value = {
          ...timing.value,
          generate: obj.timing?.generate ?? timing.value.generate,
          total: obj.timing?.total ?? timing.value.total,
        }
        break
      case 'error':
        error.value = obj.message || '未知错误'
        break
      default:
        break
    }
  }

  async function ask(question, sessionId = null) {
    reset()
    streaming.value = true
    controller = new AbortController()

    try {
      const token = getToken()
      const resp = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          question,
          session_id: sessionId,
          top_k: null,
          use_llm_check: true,
        }),
        signal: controller.signal,
      })

      if (!resp.ok || !resp.body) {
        throw new Error(`后端返回 HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      // 持续读取，跨 chunk 用 buffer 累积
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 按帧分隔符（\r\n\r\n 或 \n\n）切出完整帧
        let sep
        while ((sep = findSep(buffer)) !== null) {
          const raw = buffer.slice(0, sep.index)
          buffer = buffer.slice(sep.index + sep.length)
          handleFrame(raw)
        }
      }

      // 处理末尾可能残留的、没有以分隔符结尾的最后一帧
      if (buffer.trim()) {
        handleFrame(buffer)
      }
    } catch (e) {
      if (e && e.name === 'AbortError') {
        // 用户主动"停止生成"，静默
      } else if (e && e.name === 'TypeError' && /fetch|NetworkError/i.test(e.message)) {
        error.value = '无法连接后端服务，请确认后端已启动'
      } else {
        error.value = e.message || String(e)
      }
    } finally {
      streaming.value = false
      controller = null
    }
  }

  function abort() {
    if (controller) {
      controller.abort()
    }
  }

  return {
    streaming,
    answer,
    sources,
    retrieved,
    refused,
    judge,
    timing,
    error,
    ask,
    abort,
    reset,
  }
}
