/**
 * "优化简历"对话接口（SSE 流式）
 *
 * 后端：POST /api/chat（见 smartcv-api/main.py）
 *   入参：{ resume: Section[], message: string, jd?: string, provider: {...} }
 *   出参：SSE 事件流（text/event-stream），每条事件 = { type, ... }：
 *     - { type: "status",      stage, text }         阶段开始（convert）
 *     - { type: "agent_start", agent, label }        进入 agent（诊断/优化/摘要）
 *     - { type: "agent_end",   agent, label }        结束 agent
 *     - { type: "tool_call",   tool, args }          优化 agent 调用工具（patch_content 等）
 *     - { type: "tool_result", tool, result }        工具返回
 *     - { type: "delta",       stage, text }         阶段内逐 token 流式（打字机）
 *     - { type: "resume",      resume, summary, diagnosis }  最终改好的简历 JSON
 *     - { type: "done" }                             流水线完成
 *     - { type: "error",       message }             失败（前端直接抛错）
 *
 * EventSource 只支持 GET，这里用 fetch 的 ReadableStream 逐块读响应体，
 * 按空行 \n\n 切出事件块、解析 id:/data: 行，再按 type 分发回调。
 */
import { apiErrorMessage } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { ProviderSettings } from '@/api/provider'

export interface ChatResumePayload {
  resume: unknown
  summary: string
  diagnosis: string
}

export interface ChatHandlers {
  /** 阶段开始（"正在诊断简历…"等提示文案） */
  onStatus?: (stage: string, text: string) => void
  /** 阶段内逐 token 追加；kind = thinking(思考) | answer(回答) */
  onDelta?: (stage: string, text: string, kind?: string) => void
  /** 进入 agent（诊断/优化/摘要） */
  onAgentStart?: (agent: string, label: string) => void
  /** 优化 agent 调用工具（patch_content 等） */
  onToolCall?: (tool: string, args: Record<string, unknown>) => void
  /** 工具执行返回 */
  onToolResult?: (tool: string, result: string) => void
  /** 结束 agent */
  onAgentEnd?: (agent: string, label: string) => void
  /** 最终改好的简历 JSON（前端据此重绘） */
  onResume?: (payload: ChatResumePayload) => void
  /** 流水线完成 */
  onDone?: () => void
}

/**
 * 发送一条对话消息：SSE 流式消费，逐事件调 handlers。
 * 出错（非 2xx / 后端 error 事件）直接抛 Error；正常返回主 agent 的修改说明。
 */
export async function sendChatMessage(
  message: string,
  jd: string,
  resume: unknown,
  provider: ProviderSettings,
  handlers?: ChatHandlers,
): Promise<string> {
  const res = await apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume, message, jd, provider }),
  })
  if (!res.ok || !res.body) {
    throw new Error(await apiErrorMessage(res, '对话失败'))
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let summary = ''

  // 解析单条 SSE 事件块（"id: N\ndata: {...}\n\n"），按 type 分发回调
  const dispatch = (block: string) => {
    let data = ''
    for (const line of block.split('\n')) {
      const t = line.trim()
      if (t.startsWith('data:')) data += t.slice(5).trim()
    }
    if (!data) return
    let ev: Record<string, unknown>
    try {
      ev = JSON.parse(data) as Record<string, unknown>
    } catch {
      return
    }
    switch (ev.type) {
      case 'status':
        handlers?.onStatus?.(String(ev.stage), String(ev.text ?? ''))
        break
      case 'agent_start':
        handlers?.onAgentStart?.(String(ev.agent), String(ev.label ?? ev.agent))
        break
      case 'delta':
        handlers?.onDelta?.(
          String(ev.stage),
          String(ev.text ?? ''),
          String(ev.kind ?? 'answer'),
        )
        break
      case 'tool_call':
        handlers?.onToolCall?.(
          String(ev.tool),
          (ev.args ?? {}) as Record<string, unknown>,
        )
        break
      case 'tool_result':
        handlers?.onToolResult?.(String(ev.tool), String(ev.result ?? ''))
        break
      case 'agent_end':
        handlers?.onAgentEnd?.(String(ev.agent), String(ev.label ?? ev.agent))
        break
      case 'resume':
        summary = String(ev.summary ?? '')
        handlers?.onResume?.({
          resume: ev.resume,
          summary,
          diagnosis: String(ev.diagnosis ?? ''),
        })
        break
      case 'done':
        handlers?.onDone?.()
        break
      case 'error':
        throw new Error(String(ev.message ?? '对话失败'))
    }
  }

  // 逐块读流，按空行切事件块；尾部没有空行残留的也补处理一次
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep = buffer.indexOf('\n\n')
    while (sep >= 0) {
      dispatch(buffer.slice(0, sep))
      buffer = buffer.slice(sep + 2)
      sep = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) dispatch(buffer)
  return summary
}
