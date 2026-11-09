import { agentSessionHeaders } from '@/api/session'

export function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  for (const [name, value] of Object.entries(agentSessionHeaders())) {
    headers.set(name, value)
  }
  return fetch(input, { ...init, headers })
}
