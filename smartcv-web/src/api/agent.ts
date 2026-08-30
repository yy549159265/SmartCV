/**
 * "Agent 设置"页接口
 *
 * 后端：GET /api/agent/md（见 smartcv-api/main.py）
 *   出参：统一响应 { code, message, data }，data = { prompts, skills }：
 *     - prompts：后端 agent 用的提示词（system_prompt 开头的 md）
 *     - skills：技能文档（agents/skill 目录下的 md）
 *   两组分开返回，前端在「md预览」里分组只读查看。
 */
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

export interface AgentMdFile {
  /** 可读名，如 optimize/main、md2md/SKILL */
  name: string
  /** 相对路径，如 optimize/system_prompt_main.md */
  path: string
  content: string
}

export interface AgentMdPayload {
  prompts: AgentMdFile[]
  skills: AgentMdFile[]
}

/** 拉取后端 agent 的提示词与技能 md（只读展示用）。 */
export async function getAgentMd(): Promise<AgentMdPayload> {
  const res = await apiFetch('/api/agent/md')
  return unwrap<AgentMdPayload>(res, '加载 agent 文档失败')
}
