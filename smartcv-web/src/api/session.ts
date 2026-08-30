/**
 * agent 会话 id（UUID7）
 *
 * 一个浏览器会话只生成一次（存 localStorage，刷新不丢），所有后端请求都
 * 通过 X-Agent-Session-Id 头带上（见 api/http.ts）。后端用它做 agent 会话
 * 上下文的主键：上传解析 / 润色 / 对话 同一次会话共用同一个 id，方便后端
 * 把同一用户的多次调用串成一次会话（见 smartcv-api/main.py 的中间件）。
 */
const STORAGE_KEY = 'smartcv-agent-session-id'
const SESSION_HEADER = 'X-Agent-Session-Id'

/** 取（必要时先生成）当前 agent 会话 id。 */
export function getAgentSessionId(): string {
  let id = localStorage.getItem(STORAGE_KEY)
  if (!id) {
    id = uuidv7()
    localStorage.setItem(STORAGE_KEY, id)
  }
  return id
}

/** 生成并保存一个新的 agent 会话 id（清空旧会话，开始一段新会话，返回新 id）。 */
export function resetAgentSessionId(): string {
  const id = uuidv7()
  localStorage.setItem(STORAGE_KEY, id)
  return id
}

/** 附带 agent 会话 id 的请求头。 */
export function agentSessionHeaders(): Record<string, string> {
  return { [SESSION_HEADER]: getAgentSessionId() }
}

/**
 * 最小可用的 UUIDv7 实现（RFC 9562）：
 *   48bit 毫秒时间戳 + 版本号 7 + 变体 10 + 随机位。
 * 浏览器没有内置 UUID 生成器，正确实现十几行，不值得为这一个函数引依赖。
 */
function uuidv7(): string {
  const now = Date.now()
  const b = new Uint8Array(16)
  // 48bit 大端毫秒时间戳 → b[0..5]
  b[0] = (now / 0x10000000000) & 0xff
  b[1] = (now / 0x100000000) & 0xff
  b[2] = (now / 0x1000000) & 0xff
  b[3] = (now / 0x10000) & 0xff
  b[4] = (now / 0x100) & 0xff
  b[5] = now & 0xff
  const r = crypto.getRandomValues(new Uint8Array(10))
  b[6] = 0x70 | (r[0] & 0x0f) // 高 4 位 = 版本号 7
  b[7] = r[1]
  b[8] = 0x80 | (r[2] & 0x3f) // 高 2 位 = 变体 10
  for (let i = 0; i < 8; i++) b[9 + i] = r[3 + i]
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
