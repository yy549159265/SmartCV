/**
 * 模拟面试的浏览器持久化（IndexedDB `smartcv-interview` v1）。
 *
 *   profiles  key = resumeFingerprint，保留最近 3 份
 *   packs     key = pack.id，保留最近 3 份（进行中会话引用的包不删）
 *   sessions  key = threadId，保留进行中的一场 + 最近 5 条已结束（对话 / 清单）
 *
 * localStorage 只放指针（见 stores/interview.ts），大对象都留在这里。
 */

import type {
  Anchor,
  AnswerRecord,
  FollowDepth,
  FollowUp,
  InterviewReport,
  InterviewSummary,
  PackFocus,
  QuestionCard,
  ReferenceAnswer,
  ResumeProfile,
  Scene,
  TeachingEvent,
  TokenUsage,
  UseMode,
} from '@/api/interview'

export const INTERVIEW_DB_NAME = 'smartcv-interview'
const DB_VERSION = 1
const PROFILE_KEEP = 3
const PACK_KEEP = 3
const FINISHED_KEEP = 5
/** 与后端一致：证据锚点不足的项目不进入画像，也不参与项目面试。 */
const MIN_PROJECT_ANCHORS = 2

export interface ProfileRecord {
  fingerprint: string
  profile: ResumeProfile
  anchors: Anchor[]
  warnings: string[]
  editedAt: number
  revision: number
  schemaVersion: 1
  /** 第 1 步累计 token：画像分析 + 锚点编辑。 */
  usage?: TokenUsage
}

export interface PackRecord {
  id: string
  cards: QuestionCard[]
  warnings: string[]
  useMode: UseMode
  scene: Scene
  followDepth: FollowDepth | null
  focus: PackFocus
  projectIds: string[]
  resumeFingerprint: string
  profileRevision: number
  seenCardIds: string[]
  /** 清单自测的已读集合；题卡与对话共用 `cards`。 */
  checklistSeenCardIds?: string[]
  createdAt: number
  /** 第 3 步问题包生成的 token 用量。 */
  usage?: TokenUsage
}

export interface SessionRecord {
  /** 对话面试用服务端 threadId；清单自测用 checklist:<packId> 作历史 key。 */
  threadId: string
  packId: string
  useMode: UseMode
  scene: Scene
  focus?: PackFocus
  projectNames: string[]
  startedAt: number
  endedAt: number
  status: 'active' | 'finished'
  records: AnswerRecord[]
  currentIndex: number
  summary: InterviewSummary | null
  /** 对话面试的讲解轮次，用于最近面试里回看教学内容。 */
  teaching?: TeachingEvent[]
  /** 清单自测历史快照；与对话共用同一批问题卡，只在进入清单时落一份。 */
  checklistCards?: QuestionCard[] | null
  checklistWarnings?: string[]
  checklistSeenCardIds?: string[]
  /** 第 5 步累计 token：对话面试 / 讲解 / 示例回答 / 清单答案。 */
  usage?: TokenUsage
  /** 整场面试报告；功能尚未上线，旧记录与进行中的场次为 null。 */
  report?: InterviewReport | null
}

type ReferenceAnswerInput = Partial<ReferenceAnswer> | null | undefined

/** 旧版本把追问答案按 id 存在卡片上；读出来时迁移到 FollowUp.referenceAnswer。 */
interface LegacyQuestionCard extends Omit<QuestionCard, 'followUps' | 'referenceAnswer'> {
  followUps?: (FollowUp & { referenceAnswer?: ReferenceAnswerInput })[]
  referenceAnswer?: ReferenceAnswerInput
  followUpAnswers?: Record<string, ReferenceAnswerInput>
}

/**
 * 旧版 summary 事件曾按检查点的 snake_case 推给前端；读库与合并 SSE 记录时
 * 都先统一成前端字段，否则 cardId / createdAt / sampleAnswer / offTopic 会全部读不到。
 */
export interface LegacyAnswerRecord extends Partial<AnswerRecord> {
  card_id?: string
  off_topic?: boolean
  sample_answer?: string
  created_at?: string
}

export function normalizeAnswerRecord(record: LegacyAnswerRecord): AnswerRecord {
  return {
    cardId: record.cardId ?? record.card_id ?? '',
    question: record.question ?? '',
    answer: record.answer ?? '',
    source: record.source ?? 'main',
    level: record.level ?? null,
    leaks: record.leaks ?? [],
    offTopic: record.offTopic ?? record.off_topic ?? false,
    feedback: record.feedback ?? '',
    sampleAnswer: record.sampleAnswer ?? record.sample_answer ?? '',
    skipped: record.skipped ?? false,
    createdAt: record.createdAt ?? record.created_at ?? '',
  }
}

function normalizeAnswer(value: ReferenceAnswerInput): ReferenceAnswer {
  return {
    thinking: value?.thinking ?? '',
    answer: value?.answer ?? '',
    keyPoints: value?.keyPoints ?? [],
    missingInfo: value?.missingInfo ?? [],
    assumptions: value?.assumptions ?? [],
  }
}

function normalizeCard(card: LegacyQuestionCard): QuestionCard {
  const { followUpAnswers: legacyAnswers, ...rest } = card
  return {
    ...rest,
    followUps: (card.followUps ?? []).map((followUp) => ({
      ...followUp,
      referenceAnswer: normalizeAnswer(
        followUp.referenceAnswer ?? legacyAnswers?.[followUp.id],
      ),
    })),
    referenceAnswer: normalizeAnswer(card.referenceAnswer),
    dynamicQuestions: card.dynamicQuestions ?? [],
  }
}

function normalizePack(record: PackRecord): PackRecord {
  return {
    ...record,
    cards: (record.cards ?? []).map((card) =>
      normalizeCard(card as LegacyQuestionCard),
    ),
    warnings: record.warnings ?? [],
    focus: record.focus ?? 'balanced',
    projectIds: record.projectIds ?? [],
    checklistSeenCardIds: record.checklistSeenCardIds ?? [],
  }
}

function normalizeSession(record: SessionRecord): SessionRecord {
  const records = ((record.records ?? []) as LegacyAnswerRecord[]).map(
    normalizeAnswerRecord,
  )
  return {
    ...record,
    useMode: record.useMode ?? 'dialog',
    focus: record.focus ?? 'balanced',
    records,
    summary: record.summary
      ? {
          ...record.summary,
          records: ((record.summary.records ?? []) as LegacyAnswerRecord[]).map(
            normalizeAnswerRecord,
          ),
        }
      : null,
    teaching: record.teaching ?? [],
    checklistCards: record.checklistCards
      ? record.checklistCards.map((card) => normalizeCard(card as LegacyQuestionCard))
      : null,
    checklistWarnings: record.checklistWarnings ?? [],
    checklistSeenCardIds: record.checklistSeenCardIds ?? [],
    report: record.report ?? null,
  }
}

/** 旧记录可能还留着证据不足的项目；读出来时统一剔除，避免各页面各过滤一套。 */
function pruneUnanchoredProjects(record: ProfileRecord): ProfileRecord {
  const counts = new Map<string, number>()
  for (const anchor of record.anchors) {
    if (!anchor.projectId) continue
    counts.set(anchor.projectId, (counts.get(anchor.projectId) ?? 0) + 1)
  }
  const projects = record.profile.projects.filter(
    (project) => (counts.get(project.id) ?? 0) >= MIN_PROJECT_ANCHORS,
  )
  const kept = new Set(projects.map((project) => project.id))
  const anchors = record.anchors.filter(
    (anchor) => !anchor.projectId || kept.has(anchor.projectId),
  )
  if (
    projects.length === record.profile.projects.length &&
    anchors.length === record.anchors.length
  ) {
    return record
  }
  return { ...record, profile: { ...record.profile, projects }, anchors }
}

let dbPromise: Promise<IDBDatabase> | null = null

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(INTERVIEW_DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('profiles')) {
        db.createObjectStore('profiles', { keyPath: 'fingerprint' })
      }
      if (!db.objectStoreNames.contains('packs')) {
        db.createObjectStore('packs', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('sessions')) {
        db.createObjectStore('sessions', { keyPath: 'threadId' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB 打开失败'))
  })
  return dbPromise
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB 读写失败'))
  })
}

function transactionDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('IndexedDB 事务失败'))
    tx.onabort = () => reject(tx.error ?? new Error('IndexedDB 事务已取消'))
  })
}

async function withStore<T>(
  name: 'profiles' | 'packs' | 'sessions',
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => Promise<T> | T,
): Promise<T> {
  const db = await openDb()
  const tx = db.transaction(name, mode)
  const result = await run(tx.objectStore(name))
  await transactionDone(tx)
  return result
}

// --------------------------------------------------------------------------- profiles

export async function getProfile(fingerprint: string): Promise<ProfileRecord | null> {
  if (!fingerprint) return null
  const record = await withStore('profiles', 'readonly', (store) =>
    requestResult<ProfileRecord | undefined>(store.get(fingerprint)),
  )
  return record ? pruneUnanchoredProjects(record) : null
}

export async function listProfiles(): Promise<ProfileRecord[]> {
  const records = await withStore('profiles', 'readonly', (store) =>
    requestResult<ProfileRecord[]>(store.getAll()),
  )
  return records
    .sort((a, b) => b.editedAt - a.editedAt)
    .map(pruneUnanchoredProjects)
}

export async function putProfile(record: ProfileRecord): Promise<void> {
  await withStore('profiles', 'readwrite', (store) =>
    store.put(pruneUnanchoredProjects(record)),
  )
  await pruneProfiles()
}

export async function latestProfile(): Promise<ProfileRecord | null> {
  const records = await listProfiles()
  return records[0] ?? null
}

export async function pruneProfiles(): Promise<void> {
  const records = await listProfiles()
  const stale = records.slice(PROFILE_KEEP)
  if (!stale.length) return
  await withStore('profiles', 'readwrite', (store) => {
    for (const record of stale) store.delete(record.fingerprint)
  })
}

// --------------------------------------------------------------------------- packs

export async function getPack(id: string): Promise<PackRecord | null> {
  if (!id) return null
  const record = await withStore('packs', 'readonly', (store) =>
    requestResult<PackRecord | undefined>(store.get(id)),
  )
  return record ? normalizePack(record) : null
}

export async function putPack(record: PackRecord): Promise<void> {
  await withStore('packs', 'readwrite', (store) => store.put(record))
  await prunePacks()
}

export async function listPacks(): Promise<PackRecord[]> {
  const records = await withStore('packs', 'readonly', (store) =>
    requestResult<PackRecord[]>(store.getAll()),
  )
  return records.map(normalizePack).sort((a, b) => b.createdAt - a.createdAt)
}

export async function prunePacks(): Promise<void> {
  const [packs, sessions] = await Promise.all([listPacks(), listSessions()])
  const keep = new Set(
    sessions.filter((session) => session.status === 'active').map((session) => session.packId),
  )
  const stale: PackRecord[] = []
  let kept = 0
  for (const record of packs) {
    if (keep.has(record.id)) continue
    kept += 1
    if (kept > PACK_KEEP) stale.push(record)
  }
  if (!stale.length) return
  await withStore('packs', 'readwrite', (store) => {
    for (const record of stale) store.delete(record.id)
  })
}

// --------------------------------------------------------------------------- sessions

export async function getSession(threadId: string): Promise<SessionRecord | null> {
  if (!threadId) return null
  const record = await withStore('sessions', 'readonly', (store) =>
    requestResult<SessionRecord | undefined>(store.get(threadId)),
  )
  return record ? normalizeSession(record) : null
}

export async function putSession(record: SessionRecord): Promise<void> {
  await withStore('sessions', 'readwrite', (store) =>
    store.put(normalizeSession(record)),
  )
  await pruneSessions()
}

export async function listSessions(): Promise<SessionRecord[]> {
  const records = await withStore('sessions', 'readonly', (store) =>
    requestResult<SessionRecord[]>(store.getAll()),
  )
  return records
    .map(normalizeSession)
    .sort((a, b) => (b.endedAt || b.startedAt) - (a.endedAt || a.startedAt))
}

export async function pruneSessions(): Promise<void> {
  const sessions = await listSessions()
  const active = sessions.filter((session) => session.status === 'active')
  const finished = sessions.filter((session) => session.status === 'finished')
  const stale = [
    ...active.slice(1),
    ...finished.slice(FINISHED_KEEP),
  ]
  if (!stale.length) return
  await withStore('sessions', 'readwrite', (store) => {
    for (const record of stale) store.delete(record.threadId)
  })
}
