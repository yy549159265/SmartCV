/** agent 会话 id（UUID7）：一个浏览器一个，存 localStorage，经 X-Agent-Session-Id 头带出。 */

const STORAGE_KEY = 'smartcv-agent-session-id'
const SESSION_HEADER = 'X-Agent-Session-Id'

export function getAgentSessionId(): string {
  let id = localStorage.getItem(STORAGE_KEY)
  if (!id) {
    id = uuidv7()
    localStorage.setItem(STORAGE_KEY, id)
  }
  return id
}

export function resetAgentSessionId(): string {
  const id = uuidv7()
  localStorage.setItem(STORAGE_KEY, id)
  return id
}

export function agentSessionHeaders(): Record<string, string> {
  return { [SESSION_HEADER]: getAgentSessionId() }
}

function uuidv7(): string {
  const now = Date.now()
  const b = new Uint8Array(16)
  b[0] = (now / 0x10000000000) & 0xff
  b[1] = (now / 0x100000000) & 0xff
  b[2] = (now / 0x1000000) & 0xff
  b[3] = (now / 0x10000) & 0xff
  b[4] = (now / 0x100) & 0xff
  b[5] = now & 0xff
  const r = crypto.getRandomValues(new Uint8Array(10))
  b[6] = 0x70 | (r[0] & 0x0f)
  b[7] = r[1]
  b[8] = 0x80 | (r[2] & 0x3f)
  for (let i = 0; i < 8; i++) b[9 + i] = r[3 + i]
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
