import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

export interface AgentMdFile {
  name: string
  path: string
  content: string
}

export interface AgentMdPayload {
  prompts: AgentMdFile[]
  skills: AgentMdFile[]
}

export async function getAgentMd(): Promise<AgentMdPayload> {
  const res = await apiFetch('/api/agent/md')
  return unwrap<AgentMdPayload>(res, '加载 agent 文档失败')
}
