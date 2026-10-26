/**
 * "优化简历"对话接口（SSE 流式）
 *
 * 后端：POST /api/chat（见 smartcv-api/routers/agent.py）
 *   入参：{ resume: Section[], message: string, jd?: string, provider: {...} }
 *   出参：SSE 事件流（text/event-stream），每条事件 = { type, ... }：
 *     - { type: "status",      stage, text }         阶段开始（convert）
 *     - { type: "agent_start", agent, label }        进入 agent（诊断/优化/摘要）
 *     - { type: "agent_end",   agent, label }        结束 agent
 *     - { type: "resume_markdown", text }           诊断 agent 的输入：带位置编号的简历文本
 *     - { type: "tool_call",   tool, args }          优化 agent 调用工具（patch_content 等）
 *     - { type: "tool_result", tool, result }        工具返回
 *     - { type: "web_search",  query, results, error }  诊断 agent 联网搜索的结果
 *     - { type: "delta",       stage, text }         阶段内逐 token 流式（打字机）
 *     - { type: "ask_question", questionId, title, questions }  诊断 agent 反问，等用户回答
 *     - { type: "ask_question_closed", questionId, reason }     问题被关闭（超时）
 *     - { type: "diagnosis",   count, items }        诊断完成后的结构化诊断项
 *     - { type: "diagnosis_status", index, status, reason }  优化 agent 审查/执行单条诊断的状态
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

/** 诊断项的审查/执行状态（由优化 agent 的 diagnosis_status 事件更新） */
export type DiagnosisStatus = 'pending' | 'change' | 'skip' | 'done' | 'failed'

/**
 * 一条结构化诊断。
 *
 * s/r/c/i 是后端定位用的坐标，只在数据里存在，不展示给用户；
 * 前端只渲染 quote / reason / evidence / suggestion 这些文字信息。
 */
export interface DiagnosisItem {
  kind: 'text' | 'structure'
  s?: number | null
  r?: number | null
  c?: number | null
  i?: number | null
  /** 该位置当前正文的开头片段（≤60 字），structure 类为空 */
  quote: string
  /** 为什么这个位置的内容需要改动 */
  reason: string
  /** 事实依据（简历原文 / JD 要求 / 用户回答） */
  evidence: string
  /** 修改方向 */
  suggestion: string
  /** 前端状态：默认待分析；优化 agent 审查/执行后更新 */
  status?: DiagnosisStatus
  /** 判定理由（change/skip）或失败原因（failed） */
  note?: string
}

/** 一条联网搜索结果（诊断 agent 的 web_search 工具返回） */
export interface WebSearchResult {
  title: string
  url: string
  content: string
}

/** 诊断 agent 的一次联网搜索 */
export interface WebSearchItem {
  query: string
  results: WebSearchResult[]
  /** 搜索失败时的错误信息；成功时为空 */
  error?: string
}

export interface ChatResumePayload {
  resume: unknown
  summary: string
  diagnosis: DiagnosisItem[]
}

/** 反问的一个预设选项（第 4 项「其他」由前端补，不在这里） */
export interface AskOption {
  label: string
  description?: string
}

/** 反问的一个问题 */
export interface AskQuestion {
  id: string
  header: string
  question: string
  /** true = 多选，false = 单选 */
  multiSelect: boolean
  options: AskOption[]
  /** 固定为 true：前端在选项后追加「其他（自定义输入）」 */
  allowCustom?: boolean
}

/** 一整套反问（诊断 agent 暂停时下发） */
export interface AskQuestionPayload {
  questionId: string
  title: string
  questions: AskQuestion[]
  /** 后端等待回答的秒数（用于前端倒计时），缺省按 300 处理 */
  timeoutSeconds?: number
}

/** 前端提交的单题答案 */
export interface ChatAnswer {
  id: string
  selected: string[]
  custom: string
}

export interface ChatHandlers {
  /** 阶段开始（"正在诊断简历…"等提示文案） */
  onStatus?: (stage: string, text: string) => void
  /** 阶段内逐 token 追加；kind = thinking(思考) | answer(回答) */
  onDelta?: (stage: string, text: string, kind?: string) => void
  /** 进入 agent（诊断/优化/摘要） */
  onAgentStart?: (agent: string, label: string) => void
  /** 诊断 agent 的输入：带位置编号的简历 Markdown */
  onResumeMarkdown?: (text: string) => void
  /** 诊断 agent 联网搜索：query + 结果（前端在「Web 搜索」区单独展示） */
  onWebSearch?: (item: WebSearchItem) => void
  /** 优化 agent 调用工具（patch_content 等） */
  onToolCall?: (tool: string, args: Record<string, unknown>) => void
  /** 工具执行返回 */
  onToolResult?: (tool: string, result: string) => void
  /** 结束 agent */
  onAgentEnd?: (agent: string, label: string) => void
  /** 诊断 agent 反问：前端展示选择题，答完 POST /api/chat/answer */
  onAskQuestion?: (payload: AskQuestionPayload) => void
  /** 问题已关闭（等待超时等），前端把卡片置为失效 */
  onAskQuestionClosed?: (questionId: string, reason: string) => void
  /** 诊断完成：结构化诊断项（前端只展示文字，不展示坐标） */
  onDiagnosis?: (items: DiagnosisItem[]) => void
  /** 优化 agent 审查/执行诊断后，更新对应诊断项的状态 */
  onDiagnosisStatus?: (payload: {
    index: number
    status: DiagnosisStatus
    reason: string
  }) => void
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
      case 'resume_markdown':
        handlers?.onResumeMarkdown?.(String(ev.text ?? ''))
        break
      case 'web_search':
        handlers?.onWebSearch?.({
          query: String(ev.query ?? ''),
          results: Array.isArray(ev.results) ? (ev.results as WebSearchResult[]) : [],
          error: ev.error ? String(ev.error) : undefined,
        })
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
      case 'ask_question':
        handlers?.onAskQuestion?.({
          questionId: String(ev.questionId ?? ''),
          title: String(ev.title ?? ''),
          questions: Array.isArray(ev.questions) ? (ev.questions as AskQuestion[]) : [],
          timeoutSeconds:
            typeof ev.timeoutSeconds === 'number' ? ev.timeoutSeconds : undefined,
        })
        break
      case 'ask_question_closed':
        handlers?.onAskQuestionClosed?.(
          String(ev.questionId ?? ''),
          String(ev.reason ?? 'closed'),
        )
        break
      case 'diagnosis':
        handlers?.onDiagnosis?.(
          Array.isArray(ev.items) ? (ev.items as DiagnosisItem[]) : [],
        )
        break
      case 'diagnosis_status':
        handlers?.onDiagnosisStatus?.({
          index: Number(ev.index ?? -1),
          status: String(ev.status ?? 'pending') as DiagnosisStatus,
          reason: String(ev.reason ?? ''),
        })
        break
      case 'resume':
        summary = String(ev.summary ?? '')
        handlers?.onResume?.({
          resume: ev.resume,
          summary,
          diagnosis: Array.isArray(ev.diagnosis)
            ? (ev.diagnosis as DiagnosisItem[])
            : [],
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

/**
 * 回答诊断 agent 的反问。
 *
 * 答案不会另开一条 SSE 流：后端正拿着原来的 /api/chat 连接暂停等待，
 * 这里 POST 成功后，原流会继续往下输出诊断 → 优化 → 总结。
 * 空数组 = 跳过回答，诊断按现有信息继续。
 */
export async function sendChatAnswers(questionId: string, answers: ChatAnswer[]): Promise<void> {
  const res = await apiFetch('/api/chat/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ questionId, answers }),
  })
  if (!res.ok) {
    throw new Error(await apiErrorMessage(res, '提交回答失败'))
  }
}
