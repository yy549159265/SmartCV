/**
 * AI 模拟面试接口。
 *
 * 画像 / 问题包是普通 JSON；内容编辑走 /api/interview/edit，只返回同结构内容；
 * 对话面试每轮 action 走 SSE，
 * 解析方式与 api/chat.ts 一致（fetch + ReadableStream，按空行切块）。
 * 刷新恢复用 GET /api/interview/state，不做断线重放。
 */

import { apiErrorMessage, unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import {
  getProviderSettings,
  missingProviderFields,
  type ProviderSettings,
} from '@/api/provider'

/** 一段流程累计的 token 用量；与后端 agents/utils/usage.py 的字段一致。 */
export interface TokenUsage {
  inputTokens: number
  outputTokens: number
  totalTokens: number
  calls: number
}

export type TechLevel = '精通' | '熟练' | '掌握'
export type Coord = [number, number, number, number]
export type AnchorKind = 'tech' | 'result' | 'architecture' | 'metric' | 'contribution'
export type UseMode = 'dialog' | 'checklist'
/** 出题场景；checklist 只用于兼容升级前的旧题包。 */
export type Scene = 'project' | 'comprehensive' | 'scenario' | 'checklist'
export type PackScene = 'project' | 'comprehensive' | 'scenario'
/** 追问强度；deep 表示追问更直接、更关注依据与个人贡献。 */
export type FollowDepth = 'normal' | 'deep'

/** 项目面试的考察方向；必须在选择页明确选择，没有默认值。 */
export type InterviewFocus = 'business' | 'tech' | 'architecture' | 'review'
/** 题包与历史记录里保存的方向；综合面试不使用方向，用 balanced 占位并兼容旧记录。 */
export type PackFocus = InterviewFocus | 'balanced'
export type FollowLevel = 'L1' | 'L2' | 'L3'
export type InterviewPhase = 'interviewing' | 'teaching' | 'finished'
export type Dimension =
  | 'project_background'
  | 'business_need'
  | 'architecture'
  | 'implementation'
  | 'difficulty'
  | 'problem_solving'
  | 'result'
  | 'contribution'
  | 'tech_stack'
  | 'motivation'
  | 'career_plan'
  | 'salary'
  | 'stability'
  | 'authenticity'
export type Priority = 'high' | 'medium' | 'low'
export type InterviewAction =
  | 'answer'
  | 'skip'
  | 'skip_followup'
  | 'reanswer'
  | 'teach'
  | 'teach_message'
  | 'return'
  | 'end'

export interface TechStackItem {
  name: string
  level: TechLevel
  quote: string
  refs: Coord[]
}

export interface ProjectItem {
  id: string
  name: string
  intro: string
  role: string
  techStack: string[]
  highlights: string[]
}

export interface Anchor {
  id: string
  kind: AnchorKind
  quote: string
  refs: Coord[]
  projectId: string
  followDirections: string[]
}

export interface ResumeProfile {
  direction: string
  intro: string
  introRefs: Coord[]
  techStacks: TechStackItem[]
  projects: ProjectItem[]
}

export interface FollowUp {
  id: string
  level: FollowLevel
  question: string
  intent: string
  /** 进入清单后由用户主动触发生成；空 answer 表示尚未生成。 */
  referenceAnswer: ReferenceAnswer
}

export interface ReferenceAnswer {
  /** 回答思路：先讲什么、如何组织。 */
  thinking: string
  /** 示范回答正文；空字符串表示尚未生成。 */
  answer: string
  keyPoints: string[]
  /** 简历缺少哪些回答所需的证据；没有缺口时为空。 */
  missingInfo: string[]
  /** 为补全示范答案所做的假设，逐条展示，避免被当成简历事实。 */
  assumptions?: string[]
}

export interface DynamicQuestion {
  id: string
  question: string
  level: FollowLevel
  anchorId: string
  reasonType: 'new_anchor' | 'contradiction' | 'metric_anomaly' | 'shallow'
  sourceIndex: number
}

export interface QuestionCard {
  id: string
  projectId: string
  anchorId: string
  dimension: Dimension
  priority: Priority
  mainQuestion: string
  followUps: FollowUp[]
  evidenceQuote: string
  intent: string
  referenceAnswer: ReferenceAnswer
  leakSignals: string[]
  coverage: string[]
  dynamicQuestions: DynamicQuestion[]
}

export interface AnswerRecord {
  cardId: string
  question: string
  answer: string
  source: 'main' | 'followup' | 'reanswer' | 'skip'
  level: FollowLevel | null
  leaks: string[]
  offTopic: boolean
  feedback: string
  /** 按本轮改进建议生成的简短示例回答；旧记录或未生成时为空。 */
  sampleAnswer?: string
  skipped: boolean
  createdAt: string
}

export interface TeachingTurn {
  role: 'user' | 'teacher'
  content: string
}

export interface TeachingEvent {
  cardId: string
  question: string
  turns: TeachingTurn[]
  outcome: 'active' | 'returned' | 'skipped'
  startedAt: string
  endedAt: string
}

export interface InterviewSummary {
  records: AnswerRecord[]
  dynamicCount: number
  teachingCount: number
  answeredCount: number
  skippedCount: number
  /** 本场累计 token；旧记录可能没有。 */
  usage?: TokenUsage
  finishedReason: string
}

/** 面试报告的一个分区；报告页与导出 HTML 共用同一结构。 */
export interface InterviewReportSection {
  id: string
  title: string
  /** Markdown 正文；渲染时禁用原始 HTML。 */
  prose: string
}

/** 整场面试的报告；尚未生成时为 null，导出时仍保留该章节。 */
export interface InterviewReport {
  generatedAt?: string
  sections: InterviewReportSection[]
}

export interface ProfileResponse {
  profile: ResumeProfile
  anchors: Anchor[]
  warnings: string[]
  usage?: TokenUsage
}

export interface PackPayload {
  provider: ProviderSettings
  profile: ResumeProfile
  anchors: Anchor[]
  scene: PackScene
  followDepth: FollowDepth | null
  /** 项目面试考察方向；未选择时传 balanced，综合面试不传。 */
  focus?: PackFocus
  projectIds: string[]
}

export interface PackResponse {
  cards: QuestionCard[]
  warnings: string[]
  usage?: TokenUsage
}

export interface ReferenceAnswerPayload {
  provider: ProviderSettings
  profile: ResumeProfile
  anchors: Anchor[]
  card: QuestionCard
}

export interface ReferenceAnswerResponse {
  answer: ReferenceAnswer
  usage?: TokenUsage
}

export interface FollowUpAnswer {
  followUpId: string
  answer: ReferenceAnswer
}

export interface FollowUpAnswersPayload {
  provider: ProviderSettings
  profile: ResumeProfile
  anchors: Anchor[]
  card: QuestionCard
  followUpIds: string[]
}

export interface FollowUpAnswersResponse {
  answers: FollowUpAnswer[]
  usage?: TokenUsage
}

export interface FollowUpAddPayload {
  provider: ProviderSettings
  profile: ResumeProfile
  anchors: Anchor[]
  card: QuestionCard
  /** 想追问的方向；层级由服务端结合已有追问链判断。 */
  instruction: string
}

export interface FollowUpAddResponse {
  followUp: FollowUp
  summary: string
  usage?: TokenUsage
}

export interface ThreadPayload {
  profile: ResumeProfile
  anchors: Anchor[]
  cards: QuestionCard[]
  scene: Scene
  followDepth: FollowDepth | null
  focus: PackFocus
  useMode: UseMode
}

export interface ThreadResponse {
  threadId: string
}

export interface InterviewQuestion {
  cardId: string
  text: string
  level: FollowLevel | ''
  dynamic: boolean
  mainQuestion: string
  dimension: Dimension
  projectId: string
  followupsUsed: number
  index: number
  total: number
  resumed?: boolean
  /** 从评价卡回到上一题重答；与讲解结束返回区分开。 */
  reanswer?: boolean
}

export interface Evaluation {
  cardId: string
  leaks: string[]
  offTopic: boolean
  feedback: string
  source: AnswerRecord['source']
  level: FollowLevel | ''
  /** 用户点击「生成 AI 示例回答」后填入；未生成时为空。 */
  sampleAnswer?: string
}

export interface ServerState {
  threadId: string
  scene: Scene
  followDepth: FollowDepth | null
  phase: InterviewPhase
  currentCardId: string
  currentQuestion: string
  currentLevel: FollowLevel | null
  index: number
  total: number
  dynamicCount: number
  followupUsed: Record<string, number>
  records: AnswerRecord[]
  skippedCards: string[]
  teaching: TeachingEvent[]
  /** 本场累计 token；由服务端检查点维护。 */
  usage?: TokenUsage
  finishedReason: string
}

export interface InterviewHandlers {
  /** 本轮新增的 token 与整场累计值；本轮没有调用模型时不会触发。 */
  onUsage?: (payload: { usage: TokenUsage; total: TokenUsage }) => void
  onStarted?: (payload: {
    threadId: string
    scene: Scene
    followDepth: string
    totalCards: number
  }) => void
  onTurnStart?: (payload: { cardId: string; index: number; total: number }) => void
  onStatus?: (payload: { stage: string; text: string }) => void
  onDelta?: (payload: { stage: string; text: string }) => void
  onQuestion?: (payload: InterviewQuestion) => void
  onEvaluation?: (payload: Evaluation) => void
  onTeachingStarted?: (payload: { cardId: string; question: string }) => void
  onTeachingTurn?: (payload: {
    role: 'user' | 'teacher'
    text: string
    cardId: string
  }) => void
  onTeachingClosed?: (payload: { outcome: string }) => void
  onState?: (payload: ServerState) => void
  onSummary?: (payload: InterviewSummary) => void
  onError?: (payload: { message: string; fatal: boolean }) => void
  onDone?: (payload: { status: string }) => void
}

/** 通用内容编辑：一段 JSON + 修改思路 -> 同结构的改好内容。 */
export interface ContentEditPayload {
  scene: string
  instruction: string
  content: Record<string, unknown>
  context?: Record<string, unknown>
  /** 不允许模型改写的顶层字段，如 id、原文引用等证据字段。 */
  lockedFields?: string[]
}

export interface ContentEditResult {
  content: Record<string, unknown>
  summary: string
  usage?: TokenUsage
}

/** 目前用于画像锚点；其它位置复用同一函数，换 `scene` 即可。 */
export async function editContent(
  payload: ContentEditPayload,
): Promise<ContentEditResult> {
  const provider = getProviderSettings()
  const missing = missingProviderFields(provider)
  if (missing.length) {
    throw new Error(`请先在「高级设置」填齐：${missing.join('、')}`)
  }

  const res = await apiFetch('/api/interview/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, ...payload }),
  })
  return unwrap<ContentEditResult>(res, '内容修改失败')
}

export async function analyzeProfile(
  resume: unknown,
  provider: ProviderSettings,
): Promise<ProfileResponse> {
  const res = await apiFetch('/api/interview/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume, provider }),
  })
  return unwrap<ProfileResponse>(res, '简历分析失败')
}

export async function generatePack(payload: PackPayload): Promise<PackResponse> {
  const res = await apiFetch('/api/interview/pack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<PackResponse>(res, '问题包生成失败')
}

export async function generateReferenceAnswer(
  payload: ReferenceAnswerPayload,
): Promise<ReferenceAnswerResponse> {
  const res = await apiFetch('/api/interview/reference-answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<ReferenceAnswerResponse>(res, 'AI 示范答案生成失败')
}

export async function generateFollowUpAnswers(
  payload: FollowUpAnswersPayload,
): Promise<FollowUpAnswersResponse> {
  const res = await apiFetch('/api/interview/follow-up-answers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<FollowUpAnswersResponse>(res, 'AI 追问答案生成失败')
}

/** 按用户方向新增一条追问；层级与 id 都由服务端返回。 */
export async function addFollowUp(
  payload: FollowUpAddPayload,
): Promise<FollowUpAddResponse> {
  const res = await apiFetch('/api/interview/follow-up', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<FollowUpAddResponse>(res, '新增追问失败')
}

/** 按一轮已记录的作答生成示例回答；画像、题卡与评价由后端从检查点还原。 */
export interface SampleAnswerPayload {
  provider: ProviderSettings
  threadId: string
  cardId: string
  question: string
}

export async function generateSampleAnswer(
  payload: SampleAnswerPayload,
): Promise<{ answer: string; usage?: TokenUsage }> {
  const res = await apiFetch('/api/interview/sample-answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<{ answer: string; usage?: TokenUsage }>(res, 'AI 示例回答生成失败')
}

export async function createInterviewThread(
  payload: ThreadPayload,
): Promise<ThreadResponse> {
  const res = await apiFetch('/api/interview/thread', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return unwrap<ThreadResponse>(res, '面试创建失败')
}

export async function getInterviewState(threadId: string): Promise<ServerState | null> {
  const res = await apiFetch(
    `/api/interview/state?threadId=${encodeURIComponent(threadId)}`,
  )
  if (res.status === 404) return null
  return unwrap<ServerState>(res, '读取面试状态失败')
}

export async function streamInterview(
  body: {
    threadId: string
    action: InterviewAction
    answer?: string
    message?: string
    provider: ProviderSettings
  },
  handlers: InterviewHandlers = {},
): Promise<void> {
  const res = await apiFetch('/api/interview/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    throw new Error(await apiErrorMessage(res, '面试请求失败'))
  }

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
    let event: Record<string, unknown>
    try {
      event = JSON.parse(data) as Record<string, unknown>
    } catch {
      return
    }

    switch (event.type) {
      case 'usage': {
        const usage = event.usage as unknown as TokenUsage | undefined
        const total = event.total as unknown as TokenUsage | undefined
        if (usage && total) handlers.onUsage?.({ usage, total })
        break
      }
      case 'interview.started':
        handlers.onStarted?.({
          threadId: String(event.threadId ?? ''),
          scene: String(event.scene ?? 'project') as Scene,
          followDepth: String(event.followDepth ?? ''),
          totalCards: Number(event.totalCards ?? 0),
        })
        break
      case 'turn.start':
        handlers.onTurnStart?.({
          cardId: String(event.cardId ?? ''),
          index: Number(event.index ?? 0),
          total: Number(event.total ?? 0),
        })
        break
      case 'status':
        handlers.onStatus?.({
          stage: String(event.stage ?? ''),
          text: String(event.text ?? ''),
        })
        break
      case 'delta':
        handlers.onDelta?.({
          stage: String(event.stage ?? ''),
          text: String(event.text ?? ''),
        })
        break
      case 'question':
        handlers.onQuestion?.(event as unknown as InterviewQuestion)
        break
      case 'evaluation':
        handlers.onEvaluation?.(event as unknown as Evaluation)
        break
      case 'teaching.started':
        handlers.onTeachingStarted?.({
          cardId: String(event.cardId ?? ''),
          question: String(event.question ?? ''),
        })
        break
      case 'teaching.turn':
        handlers.onTeachingTurn?.({
          role: event.role === 'teacher' ? 'teacher' : 'user',
          text: String(event.text ?? ''),
          cardId: String(event.cardId ?? ''),
        })
        break
      case 'teaching.closed':
        handlers.onTeachingClosed?.({
          outcome: String(event.outcome ?? 'returned'),
        })
        break
      case 'state':
        handlers.onState?.(event as unknown as ServerState)
        break
      case 'summary':
        handlers.onSummary?.(event as unknown as InterviewSummary)
        break
      case 'error':
        handlers.onError?.({
          message: String(event.message ?? '面试推进失败'),
          fatal: Boolean(event.fatal),
        })
        break
      case 'done':
        handlers.onDone?.({ status: String(event.status ?? 'ok') })
        break
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
}
