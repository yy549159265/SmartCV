/**
 * 优化对话接口（SSE）：POST /api/chat，事件类型见下方 ChatHandlers 的字段注释。
 * EventSource 只支持 GET，这里用 fetch 的 ReadableStream 按空行切块、解析 data: 行后按 type 分发。
 */

import { apiErrorMessage } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { ProviderSettings } from '@/api/provider'

export type RewriteMode = 'standard' | 'bold'

export type DiagnosisStatus = 'pending' | 'change' | 'skip' | 'done' | 'failed'

export type DiagnosisDisposition = 'must' | 'suggest' | 'keep' | 'insufficient'

export interface DiagnosisItem {
  disposition?: DiagnosisDisposition
  s?: number | null
  r?: number | null
  c?: number | null
  i?: number | null
  quote: string
  reason: string
  evidence: string
  suggestion: string
  reference?: string
  section?: string
  sectionIndex?: number
  location?: string
  status?: DiagnosisStatus
  note?: string
}

export interface ReferenceExampleItem {
  id: string
  direction: string
  description: string
}

export interface WebSearchResult {
  title: string
  url: string
  content: string
}

export interface WebSearchItem {
  query: string
  results: WebSearchResult[]
  error?: string
}

export interface ChatResumePayload {
  resume: unknown
  summary: string
  diagnosis: DiagnosisItem[]
}

export interface AskOption {
  label: string
  description?: string
}

export interface AskQuestion {
  id: string
  header: string
  question: string
  multiSelect: boolean
  options: AskOption[]
  allowCustom?: boolean
}

export interface AskQuestionPayload {
  questionId: string
  title: string
  questions: AskQuestion[]
  timeoutSeconds?: number
}

export interface ChatAnswer {
  id: string
  selected: string[]
  custom: string
}

export interface ChatHandlers {
  onStatus?: (stage: string, text: string) => void
  onDelta?: (stage: string, text: string, kind?: string) => void
  onAgentStart?: (agent: string, label: string) => void
  onResumeMarkdown?: (text: string) => void
  onReferenceExamples?: (items: ReferenceExampleItem[]) => void
  onWebSearch?: (item: WebSearchItem) => void
  onToolCall?: (tool: string, args: Record<string, unknown>) => void
  onToolResult?: (tool: string, result: string) => void
  onAgentEnd?: (agent: string, label: string) => void
  onAskQuestion?: (payload: AskQuestionPayload) => void
  onAskQuestionClosed?: (questionId: string, reason: string) => void
  onDiagnosis?: (items: DiagnosisItem[], styleNotes: string[]) => void
  onDiagnosisStatus?: (payload: {
    index: number
    status: DiagnosisStatus
    reason: string
  }) => void
  onResume?: (payload: ChatResumePayload) => void
  onDone?: () => void
}

export async function sendChatMessage(
  message: string,
  jd: string,
  resume: unknown,
  provider: ProviderSettings,
  referenceIds: string[] = [],
  rewriteMode: RewriteMode = 'standard',
  handlers?: ChatHandlers,
): Promise<string> {
  const res = await apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume, message, jd, provider, referenceIds, rewriteMode }),
  })
  if (!res.ok || !res.body) {
    throw new Error(await apiErrorMessage(res, '对话失败'))
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let summary = ''

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
      case 'reference_examples':
        handlers?.onReferenceExamples?.(
          Array.isArray(ev.items) ? (ev.items as ReferenceExampleItem[]) : [],
        )
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
          Array.isArray(ev.styleNotes)
            ? ev.styleNotes.filter((note): note is string => typeof note === 'string')
            : [],
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
