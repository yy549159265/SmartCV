/**
 * 统一的后端请求入口：所有接口都经这里，自动带上 agent 会话 id 头
 * （X-Agent-Session-Id，UUID7，见 api/session.ts）。
 * 以后要加公共请求头（trace id 之类）也在这加一处即可。
 */
import { agentSessionHeaders } from '@/api/session'

export function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  for (const [name, value] of Object.entries(agentSessionHeaders())) {
    headers.set(name, value)
  }
  return fetch(input, { ...init, headers })
}
