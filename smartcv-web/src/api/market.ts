/**
 * 市场洞察接口：SSE 调研流 + 反问回答。
 *
 * SSE 用 fetch 的 ReadableStream 读取（EventSource 不支持 POST）；
 * 事件类型与后端 agents/resume/marker 一一对应，页面只按 type 分发。
 */

import { apiErrorMessage, unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { ProviderSettings } from '@/api/provider'

/** 用户补充的一条网址：direction 决定它归到哪个调研维度。 */
export interface MarketExtraUrl {
  url: string
  direction: string
  note: string
}

export interface MarketRequestPayload {
  targetRole: string
  resume: unknown[] | null
  provider: ProviderSettings
  city?: string
  experience?: string
  /** 用户希望 AI 回答的内容：自由文本问题/诉求；规划据此生成调研方面，后续阶段围绕它作答。 */
  direction?: string
  timeRange?: string
  /** 按维度类别设置的页数：jobs 招聘矩阵、trend 技术趋势、other 其余动态方向。 */
  pagesPerDim?: Record<string, number>
  /** 每个调研方向最多使用的补充网址条数。 */
  urlsPerDim?: number
  /** 抓取方式：get / crawler；与后端抓取适配器注册表对应。 */
  fetchMode?: string
  /** 采集方式及其设置：{ 方式 id: { 设置键: 值 } }，如 { deepseek: { baseUrl, apiKey } }。 */
  collector?: Record<string, Record<string, string>>
  /** 内置来源及其设置：{ 来源: { 设置键: 值 } }，与后端 sources 一致。 */
  sources?: Record<string, Record<string, string>>
  extraUrls?: MarketExtraUrl[]
}

export interface MarketAskOption {
  label: string
  description?: string
}

export interface MarketAskQuestion {
  id: string
  header: string
  question: string
  multiSelect: boolean
  options: MarketAskOption[]
  allowCustom?: boolean
}

export interface MarketAskPayload {
  questionId: string
  title: string
  questions: MarketAskQuestion[]
  timeoutSeconds?: number
}

export interface MarketAnswer {
  id: string
  selected: string[]
  custom: string
}

export interface MarketEvent {
  type: string
  [key: string]: unknown
}

export interface MarketHandlers {
  onEvent?: (event: MarketEvent) => void
  onTaskId?: (taskId: string) => void
}

export async function streamMarket(
  payload: MarketRequestPayload,
  handlers: MarketHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch('/api/market/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new Error(await apiErrorMessage(res, '启动市场洞察失败'))
  }

  const headerTaskId = res.headers.get('X-Market-Task-Id')
  if (headerTaskId) handlers.onTaskId?.(headerTaskId)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (block: string) => {
    let data = ''
    for (const line of block.split('\n')) {
      const text = line.trim()
      if (text.startsWith('data:')) data += text.slice(5).trim()
    }
    if (!data) return
    let event: MarketEvent
    try {
      event = JSON.parse(data) as MarketEvent
    } catch {
      return
    }
    if (event.type === 'task' && typeof event.taskId === 'string') {
      handlers.onTaskId?.(event.taskId)
    }
    handlers.onEvent?.(event)
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let index = buffer.indexOf('\n\n')
      while (index >= 0) {
        dispatch(buffer.slice(0, index))
        buffer = buffer.slice(index + 2)
        index = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer)
  } finally {
    // 取消 / 事件处理抛错时主动断开连接，服务端才能及时停掉这一轮的 producer。
    await reader.cancel().catch(() => undefined)
  }
}

export interface MarketRoleOption {
  title: string
  reason?: string
}

export interface MarketRoleInference {
  roles: MarketRoleOption[]
  city: string
  experience: string
}

/** 用一份简历反推 4 个目标岗位，并带出可直接填入市场调研请求的城市 / 年限。 */
export async function inferMarketRoles(
  resume: unknown[],
  provider: ProviderSettings,
): Promise<MarketRoleInference> {
  const res = await apiFetch('/api/market/roles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume, provider }),
  })
  const data = await unwrap<Partial<MarketRoleInference>>(res, '岗位反推失败')
  return {
    roles: Array.isArray(data?.roles) ? data.roles : [],
    city: typeof data?.city === 'string' ? data.city : '',
    experience: typeof data?.experience === 'string' ? data.experience : '',
  }
}

export async function answerMarket(
  taskId: string,
  questionId: string,
  answers: MarketAnswer[],
): Promise<void> {
  const res = await apiFetch('/api/market/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ taskId, questionId, answers }),
  })
  if (!res.ok) {
    throw new Error(await apiErrorMessage(res, '提交回答失败'))
  }
}

/** 取消一轮调研：停掉后端的 producer，避免旧任务继续占用模型和采集资源。 */
export async function cancelMarket(taskId: string): Promise<void> {
  const res = await apiFetch('/api/market/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ taskId }),
  })
  if (!res.ok) {
    throw new Error(await apiErrorMessage(res, '取消调研失败'))
  }
}
