/**
 * 模拟面试页状态机（SDD 6.2）：
 *
 *   idle → analyzing → profileReady → choosing → generating → packReady
 *                                              ├─ 对话面试：interviewing ↔ teaching → finished
 *                                              └─ 清单自测：直接展开同一份问题包
 *
 * 先选场景出题包，第 4 步再选方式；两种方式共用题卡，只有对话面试建场（/thread）。
 * 大对象（画像 / 问题包 / 会话）只进 IndexedDB；localStorage 只存指针。
 * 刷新后用 GET /api/interview/state 对齐服务端检查点。
 */

import { defineStore } from 'pinia'

import {
  addFollowUp as requestAddFollowUp,
  analyzeProfile,
  createInterviewThread,
  editContent,
  generateFollowUpAnswers,
  generatePack,
  generateReferenceAnswer,
  generateSampleAnswer as requestSampleAnswer,
  getInterviewState,
  streamInterview,
  type AnswerRecord,
  type Anchor,
  type Evaluation,
  type FollowDepth,
  type InterviewAction,
  type InterviewFocus,
  type InterviewQuestion,
  type InterviewSummary,
  type PackScene,
  type ResumeProfile,
  type Scene,
  type ServerState,
  type TeachingTurn,
  type TokenUsage,
  type UseMode,
} from '@/api/interview'
import { getProviderSettings, missingProviderFields, type ProviderSettings } from '@/api/provider'
import { useResumeStore } from '@/stores/resume'
import { message } from '@/utils/feedback'
import { LEVEL_LABEL, mergeUsage, resumeFingerprint } from '@/utils/interview'
import {
  getPack,
  getProfile,
  getSession,
  latestProfile,
  listSessions,
  normalizeAnswerRecord,
  putPack,
  putProfile,
  putSession,
  type PackRecord,
  type ProfileRecord,
  type SessionRecord,
} from '@/utils/interviewDb'

export type StorePhase =
  | 'idle'
  | 'analyzing'
  | 'profileReady'
  | 'choosing'
  | 'generating'
  | 'packReady'
  | 'interviewing'
  | 'teaching'
  | 'finished'

interface Pointer {
  threadId: string
  packId: string
  useMode?: UseMode
  scene?: Scene
}

const POINTER_KEY = 'smartcv-interview-last'

function readPointer(): Partial<Pointer> {
  try {
    return JSON.parse(localStorage.getItem(POINTER_KEY) ?? '{}') as Partial<Pointer>
  } catch {
    return {}
  }
}

function writePointer(pointer: Pointer): void {
  localStorage.setItem(POINTER_KEY, JSON.stringify(pointer))
}

/** IndexedDB 不能直接结构化克隆 Vue 的响应式代理。 */
function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function providerOrWarn(): ProviderSettings | null {
  const provider = getProviderSettings()
  const missing = missingProviderFields(provider)
  if (missing.length) {
    message.warning(`请先在「高级设置」里填好：${missing.join('、')}`)
    return null
  }
  return provider
}

function summaryFromRecords(
  records: AnswerRecord[],
  options: {
    dynamicCount?: number
    teachingCount?: number
    finishedReason?: string
  } = {},
): InterviewSummary {
  const answered = records.filter((record) => !record.skipped)
  return {
    records,
    dynamicCount: options.dynamicCount ?? 0,
    teachingCount: options.teachingCount ?? 0,
    answeredCount: answered.length,
    skippedCount: records.length - answered.length,
    finishedReason: options.finishedReason ?? '',
  }
}

function summaryFromState(
  state: ServerState,
  records: AnswerRecord[] = state.records,
): InterviewSummary {
  return summaryFromRecords(records, {
    dynamicCount: state.dynamicCount,
    teachingCount: state.teaching.length,
    finishedReason: state.finishedReason,
  })
}

function recordKey(record: AnswerRecord): string {
  return `${record.cardId}\u0000${record.question}\u0000${record.answer}`
}

function roundKey(record: AnswerRecord): string {
  return `${record.cardId}\u0000${record.question}`
}

/**
 * 示例回答只存在本地：服务端记录覆盖本地时，按 卡 + 问题 + 回答
 * 把已经生成的示例回答带回去，刷新或结束时不会丢。
 *
 * 服务端事件可能带 snake_case 字段，回答文本也可能被归一化；因此先统一
 * 字段名，再按完整键查找。仍找不到时按同一道题的第几次作答兜底，
 * 避免把上一轮的示例回答错配到新一轮。
 */
function mergeSamples(
  next: AnswerRecord[],
  current: AnswerRecord[],
): AnswerRecord[] {
  const local = current.map((record) => normalizeAnswerRecord(record))
  const counts = new Map<string, number>()
  const samples = new Map<string, Map<number, string>>()
  const exactSamples = new Map<string, string>()
  for (const record of local) {
    const key = roundKey(record)
    const order = counts.get(key) ?? 0
    counts.set(key, order + 1)
    if (!record.sampleAnswer) continue
    exactSamples.set(recordKey(record), record.sampleAnswer)
    const byOrder = samples.get(key) ?? new Map<number, string>()
    byOrder.set(order, record.sampleAnswer)
    samples.set(key, byOrder)
  }
  if (!exactSamples.size) {
    return next.map((record) => normalizeAnswerRecord(record))
  }

  const nextCounts = new Map<string, number>()
  return next.map((record) => {
    const normalized = normalizeAnswerRecord(record)
    const key = roundKey(normalized)
    const order = nextCounts.get(key) ?? 0
    nextCounts.set(key, order + 1)
    if (normalized.sampleAnswer) return normalized
    const exact = exactSamples.get(recordKey(normalized))
    if (exact) return { ...normalized, sampleAnswer: exact }
    const sample = samples.get(key)?.get(order)
    return sample ? { ...normalized, sampleAnswer: sample } : normalized
  })
}

function recordIndex(
  records: AnswerRecord[],
  cardId: string,
  question: string,
  answer: string,
): number {
  for (let index = records.length - 1; index >= 0; index -= 1) {
    const record = records[index]
    if (record.cardId !== cardId) continue
    if (question && record.question !== question) continue
    if (answer && record.answer !== answer) continue
    return index
  }
  return -1
}

function checklistSessionKey(packId: string): string {
  return `checklist:${packId}`
}

export const useInterviewStore = defineStore('interview', {
  state: () => ({
    ready: false,
    fingerprint: '',
    profileRecord: null as ProfileRecord | null,
    latest: null as ProfileRecord | null,
    packRecord: null as PackRecord | null,
    session: null as SessionRecord | null,
    /** 只读回看：最近面试里打开的历史记录，不覆盖当前活动题包。 */
    reviewSession: null as SessionRecord | null,
    reviewPack: null as PackRecord | null,
    checklistSessionId: '',
    threadId: '',
    phase: 'idle' as StorePhase,
    analyzing: false,
    generating: false,
    /** 正在生成主问题参考答案的卡片。 */
    answerGeneratingCardIds: [] as string[],
    /** 正在生成追问答案的卡片。 */
    followUpsGeneratingCardIds: [] as string[],
    /** 正在按用户方向新增追问的卡片。 */
    followUpAddingCardIds: [] as string[],
    creatingThread: false,
    streaming: false,
    expired: false,
    error: '',
    statusText: '',
    question: null as InterviewQuestion | null,
    evaluation: null as Evaluation | null,
    evaluationPending: false,
    /** 评价卡上的 AI 示例回答正在生成。 */
    samplePending: false,
    pendingAnswer: '',
    pendingQuestion: '',
    teachingTurns: [] as TeachingTurn[],
    teachingStream: '',
    serverState: null as ServerState | null,
    summary: null as InterviewSummary | null,
    history: [] as SessionRecord[],
  }),

  getters: {
    hasProfile: (state) => Boolean(state.profileRecord),
    inDialog: (state) =>
      ['interviewing', 'teaching', 'finished'].includes(state.phase) && Boolean(state.threadId),
    packStale: (state) =>
      Boolean(
        state.packRecord &&
          state.profileRecord &&
          state.packRecord.profileRevision !== state.profileRecord.revision,
      ),
    activeSession: (state) =>
      state.history.find((item) => item.status === 'active') ?? null,
    finishedSessions: (state) =>
      state.history.filter((item) => item.status === 'finished').slice(0, 5),
    activeHistoryId: (state) =>
      state.reviewSession?.threadId ||
      state.threadId ||
      (state.packRecord?.useMode === 'checklist' ? state.checklistSessionId : ''),
    currentCard: (state) =>
      state.packRecord?.cards.find((card) => card.id === state.question?.cardId) ?? null,
    /** 第 1 步用量：画像分析 + 锚点编辑。 */
    profileUsage: (state): TokenUsage | null => state.profileRecord?.usage ?? null,
    /** 第 3 步用量：问题包生成。 */
    packUsage: (state): TokenUsage | null => state.packRecord?.usage ?? null,
    /** 第 5 步用量：对话面试、示例回答或清单自测的累计值。 */
    roomUsage(state): TokenUsage | null {
      if (state.reviewSession) return state.reviewSession.usage ?? null
      if (
        state.session &&
        ['interviewing', 'teaching', 'finished'].includes(state.phase)
      ) {
        return state.session.usage ?? state.serverState?.usage ?? null
      }
      if (state.checklistSessionId) {
        const session = state.history.find(
          (item) => item.threadId === state.checklistSessionId,
        )
        return session?.usage ?? null
      }
      return null
    },
  },

  actions: {
    async init(): Promise<void> {
      if (this.ready) return
      const resumeStore = useResumeStore()
      this.fingerprint = resumeFingerprint(resumeStore.resume)
      this.latest = await latestProfile().catch(() => null)
      this.profileRecord = await getProfile(this.fingerprint).catch(() => null)
      if (this.profileRecord) this.phase = 'profileReady'
      this.history = await listSessions().catch(() => [])

      const pointer = readPointer()
      if (pointer.packId) {
        this.packRecord = await getPack(pointer.packId).catch(() => null)
        if (this.packRecord && !this.packRecord.useMode) this.packRecord.useMode = 'dialog'
      }
      const wantsChecklist =
        pointer.useMode === 'checklist' || this.packRecord?.useMode === 'checklist'
      if (!wantsChecklist && pointer.threadId && pointer.packId) {
        this.session = await getSession(pointer.threadId).catch(() => null)
        const state = await getInterviewState(pointer.threadId).catch(() => null)
        if (state) {
          this.threadId = pointer.threadId
          this.applyState(state)
          if (this.session?.summary) this.summary = this.session.summary
          if (state.phase === 'finished' && !this.summary) {
            this.summary = summaryFromState(state, this.session?.records)
          }
          // 服务端已结束但本地记录还停在 active（比如在别处结束、或结束事件没收到）：
          // 这里补齐状态，否则左侧「最近面试」会把一场已结束的面试显示成进行中。
          if (
            state.phase === 'finished' &&
            this.session &&
            this.session.status !== 'finished'
          ) {
            this.session.status = 'finished'
            this.session.endedAt = Date.now()
            this.session.records = mergeSamples(state.records, this.session.records)
            this.session.summary = this.summary
            await putSession(plain(this.session)).catch(() => undefined)
            this.history = await listSessions().catch(() => this.history)
          }
          if (state.phase === 'finished' && this.session) {
            this.reviewSession = this.session
            this.reviewPack = this.packRecord
          }
        } else if (this.session?.status === 'active') {
          this.expired = true
        } else if (this.session?.status === 'finished') {
          this.threadId = pointer.threadId
          this.phase = 'finished'
          this.expired = true
          this.summary =
            this.session.summary ??
            summaryFromRecords(this.session.records, {
              teachingCount: this.session.teaching?.length ?? 0,
            })
          this.reviewSession = this.session
          this.reviewPack = this.packRecord
        }
      } else if (this.packRecord) {
        this.phase = 'packReady'
        if (this.packRecord.useMode === 'checklist') {
          const match = this.history.find(
            (item) =>
              item.useMode === 'checklist' && item.packId === this.packRecord?.id,
          )
          this.checklistSessionId = match?.threadId ?? ''
        }
      }
      this.ready = true
    },

    applyState(state: ServerState): void {
      this.serverState = state
      this.phase = state.phase
      this.threadId = state.threadId || this.threadId
      if (this.session) {
        this.session.records = mergeSamples(state.records, this.session.records)
        this.session.currentIndex = state.index
        this.session.teaching = state.teaching
        // 刷新恢复时检查点是唯一可信来源；正常情况下它与本地累加值一致。
        if (state.usage) this.session.usage = state.usage
      }
      if (state.phase === 'finished' || !state.currentQuestion) {
        this.question = null
        return
      }
      const card = this.packRecord?.cards.find((item) => item.id === state.currentCardId)
      const dynamic =
        card?.dynamicQuestions.some((item) => item.question === state.currentQuestion) ?? false
      this.question = {
        cardId: state.currentCardId,
        text: state.currentQuestion,
        level: state.currentLevel ?? '',
        dynamic,
        mainQuestion: card?.mainQuestion ?? state.currentQuestion,
        dimension: card?.dimension ?? 'implementation',
        projectId: card?.projectId ?? '',
        followupsUsed: state.followupUsed[state.currentCardId] ?? 0,
        index: state.index,
        total: state.total,
      }
      const active = [...state.teaching].reverse().find((item) => item.outcome === 'active')
      if (active) {
        this.teachingTurns = active.turns
        this.teachingStream = ''
      }
    },

    closeHistoryReview(): void {
      this.reviewSession = null
      this.reviewPack = null
    },

    /** 清单历史回看里标记已读，写回该条历史快照。 */
    async markReviewSeen(cardId: string): Promise<void> {
      const session = this.reviewSession
      if (!session || session.useMode !== 'checklist') return
      const seen = session.checklistSeenCardIds ?? []
      if (seen.includes(cardId)) return
      session.checklistSeenCardIds = [...seen, cardId]
      await putSession(plain(session)).catch(() => undefined)
      this.history = await listSessions().catch(() => this.history)
    },

    /**
     * 从编辑页回来时简历可能已变：换了简历就重新找对应画像。
     * 面试进行中不打断当前线程（画像已在检查点里），只更新本地指纹。
     */
    async syncResume(): Promise<void> {
      const resumeStore = useResumeStore()
      const fingerprint = resumeFingerprint(resumeStore.resume)
      if (fingerprint === this.fingerprint) return
      this.fingerprint = fingerprint
      this.latest = await latestProfile().catch(() => null)
      const record = await getProfile(fingerprint).catch(() => null)
      if (['interviewing', 'teaching', 'finished'].includes(this.phase) && this.threadId) {
        this.profileRecord = record ?? this.profileRecord
        return
      }
      this.profileRecord = record
      this.packRecord = null
      this.reviewSession = null
      this.reviewPack = null
      this.checklistSessionId = ''
      this.summary = null
      this.question = null
      this.threadId = ''
      this.session = null
      this.expired = false
      this.phase = record ? 'profileReady' : 'idle'
    },

    async analyze(): Promise<boolean> {
      const provider = providerOrWarn()
      if (!provider) return false
      const resumeStore = useResumeStore()
      this.analyzing = true
      this.phase = 'analyzing'
      this.error = ''
      this.fingerprint = resumeFingerprint(resumeStore.resume)
      try {
        const result = await analyzeProfile(resumeStore.resume, provider)
        const record: ProfileRecord = {
          fingerprint: this.fingerprint,
          profile: result.profile,
          anchors: result.anchors,
          warnings: result.warnings ?? [],
          editedAt: Date.now(),
          revision: (this.profileRecord?.revision ?? 0) + 1,
          schemaVersion: 1,
          usage: result.usage,
        }
        await putProfile(plain(record))
        this.profileRecord = record
        this.latest = record
        this.phase = 'profileReady'
        message.success('简历画像已生成，请确认后继续')
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : '简历分析失败'
        message.error(this.error)
        this.phase = this.profileRecord ? 'profileReady' : 'idle'
        return false
      } finally {
        this.analyzing = false
      }
    },

    async useLatestProfile(): Promise<void> {
      if (!this.latest) return
      this.profileRecord = this.latest
      this.phase = 'profileReady'
    },

    async saveProfile(
      profile: ResumeProfile,
      anchors: Anchor[],
      usage?: TokenUsage | null,
    ): Promise<void> {
      const base = this.profileRecord
      const record: ProfileRecord = {
        fingerprint: this.fingerprint,
        profile,
        anchors,
        warnings: base?.warnings ?? [],
        editedAt: Date.now(),
        revision: (base?.revision ?? 0) + 1,
        schemaVersion: 1,
        usage: usage ? mergeUsage(base?.usage, usage) : base?.usage,
      }
      await putProfile(plain(record)).catch(() => undefined)
      this.profileRecord = record
      this.latest = record
      this.phase = 'profileReady'
    },

    /** 只按场景出题；面试方式在题包生成后再选。 */
    async generate(options: {
      scene: PackScene
      followDepth: FollowDepth | null
      /** 项目面试可选；未选择或综合面试为 null，保存时用 balanced 占位。 */
      focus: InterviewFocus | null
      projectIds: string[]
    }): Promise<boolean> {
      const provider = providerOrWarn()
      if (!provider || !this.profileRecord) return false
      const previousPhase = this.phase
      this.reviewSession = null
      this.reviewPack = null
      this.generating = true
      this.answerGeneratingCardIds = []
      this.followUpsGeneratingCardIds = []
      this.followUpAddingCardIds = []
      this.phase = 'generating'
      this.error = ''
      this.expired = false
      try {
        const result = await generatePack({
          provider,
          profile: this.profileRecord.profile,
          anchors: this.profileRecord.anchors,
          scene: options.scene,
          followDepth: options.followDepth,
          focus: options.focus ?? undefined,
          projectIds: options.projectIds,
        })
        const record: PackRecord = {
          id: `pack_${Date.now().toString(36)}`,
          cards: result.cards,
          warnings: result.warnings,
          // 生成时还没有选方式；先给默认值，第 3 步再按用户选择更新。
          useMode: 'dialog',
          scene: options.scene,
          followDepth: options.followDepth,
          focus: options.focus ?? 'balanced',
          projectIds: [...options.projectIds],
          resumeFingerprint: this.fingerprint,
          profileRevision: this.profileRecord.revision,
          seenCardIds: [],
          checklistSeenCardIds: [],
          createdAt: Date.now(),
          usage: result.usage,
        }
        await putPack(plain(record))
        this.packRecord = record
        this.summary = null
        this.evaluation = null
        this.teachingTurns = []
        this.teachingStream = ''
        // 新一轮出题只准备题包；旧会话留在历史里，真正开始面试时再收尾。
        this.threadId = ''
        this.session = null
        this.phase = 'packReady'
        writePointer({
          threadId: '',
          packId: record.id,
          useMode: record.useMode,
          scene: options.scene,
        })
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : '问题包生成失败'
        message.error(this.error)
        this.phase =
          previousPhase === 'generating'
            ? this.profileRecord
              ? 'choosing'
              : 'idle'
            : previousPhase
        return false
      } finally {
        this.generating = false
      }
    },

    /** 第 3 步：题包生成后选择怎么消费它。 */
    async setUseMode(mode: UseMode): Promise<void> {
      if (!this.packRecord) return
      this.reviewSession = null
      this.reviewPack = null
      this.packRecord.useMode = mode
      await putPack(plain(this.packRecord)).catch(() => undefined)
      writePointer({
        threadId: this.threadId,
        packId: this.packRecord.id,
        useMode: mode,
        scene: this.packRecord.scene,
      })
    },

    /**
     * 第 4 步选中清单：复用第 3 步问题包，只记录当前方式并写一条历史快照。
     */
    async openChecklist(): Promise<boolean> {
      const record = this.packRecord
      if (!record) return false
      if (this.packStale) {
        message.warning('简历画像已修改，请重新生成问题包')
        return false
      }
      if (!record.cards.length) {
        message.warning('没有可用题目，请重新生成')
        return false
      }

      this.reviewSession = null
      this.reviewPack = null
      record.useMode = 'checklist'
      await putPack(plain(record)).catch(() => undefined)
      writePointer({
        threadId: this.threadId,
        packId: record.id,
        useMode: 'checklist',
        scene: record.scene,
      })
      await this.syncChecklistSession().catch(() => undefined)
      // 答案由用户点击「AI生成答案」触发生成，进入清单时不再自动补齐。
      return true
    },

    /**
     * 把当前题包写成清单历史快照；与对话共用同一批问题卡。
     * 补 AI 答案或标记已读后更新同一条记录，不再按题量分多份。
     */
    async syncChecklistSession(): Promise<void> {
      const record = this.packRecord
      if (!record) return
      const key = checklistSessionKey(record.id)
      const existing = await getSession(key).catch(() => null)
      const now = Date.now()
      const projectNames = record.projectIds
        .map(
          (id) =>
            this.profileRecord?.profile.projects.find((project) => project.id === id)?.name ?? '',
        )
        .filter(Boolean)
      const session: SessionRecord = {
        threadId: key,
        packId: record.id,
        useMode: 'checklist',
        scene: record.scene,
        focus: record.focus,
        projectNames,
        startedAt: existing?.startedAt ?? now,
        endedAt: now,
        status: 'finished',
        records: [],
        currentIndex: 0,
        summary: null,
        teaching: [],
        checklistCards: record.cards,
        checklistWarnings: record.warnings ?? [],
        checklistSeenCardIds: record.checklistSeenCardIds ?? [],
        // 补答案 / 标记已读会反复重建快照，累计用量必须保留。
        usage: existing?.usage,
      }
      await putSession(plain(session))
      this.checklistSessionId = key
      this.history = await listSessions().catch(() => this.history)
    },

    /**
     * 第 5 步 token 累计：对话面试记到当前会话，清单自测记到清单快照。
     * 传入的是一次请求新增的用量，这里只做累加。
     */
    async addRoomUsage(delta: TokenUsage | null | undefined): Promise<void> {
      if (!delta || !delta.calls) return
      const checklistKey =
        this.packRecord?.useMode === 'checklist' ? this.checklistSessionId : ''
      if (!this.session || checklistKey) {
        if (!checklistKey) return
        const session =
          (await getSession(checklistKey).catch(() => null)) ??
          this.history.find((item) => item.threadId === checklistKey) ??
          null
        if (!session) return
        session.usage = mergeUsage(session.usage, delta)
        await putSession(plain(session)).catch(() => undefined)
        this.history = await listSessions().catch(() => this.history)
        return
      }
      this.session.usage = mergeUsage(this.session.usage, delta)
    },

    /** 手动为一张卡生成主问题参考答案，并写回当前题包。 */
    async generateAnswer(cardId: string): Promise<boolean> {
      const provider = providerOrWarn()
      const record = this.packRecord
      const profileRecord = this.profileRecord
      if (!provider || !record || !profileRecord) return false
      if (this.answerGeneratingCardIds.includes(cardId)) return false

      const card = record.cards.find((item) => item.id === cardId)
      if (!card) return false
      if (card.referenceAnswer?.answer) return false

      this.answerGeneratingCardIds = [...this.answerGeneratingCardIds, cardId]
      this.error = ''
      try {
        const result = await generateReferenceAnswer({
          provider,
          profile: profileRecord.profile,
          anchors: profileRecord.anchors,
          card: plain(card),
        })
        card.referenceAnswer = result.answer
        await putPack(plain(record)).catch(() => undefined)
        await this.addRoomUsage(result.usage)
        if (record.useMode === 'checklist') {
          await this.syncChecklistSession().catch(() => undefined)
        }
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'AI 示范答案生成失败'
        message.error(this.error)
        return false
      } finally {
        this.answerGeneratingCardIds = this.answerGeneratingCardIds.filter(
          (id) => id !== cardId,
        )
      }
    },

    /** 为一张卡的 L1/L2/L3 追问生成示范答案；一次补齐所有缺失项。 */
    async generateFollowUpAnswers(cardId: string): Promise<boolean> {
      const provider = providerOrWarn()
      const record = this.packRecord
      const profileRecord = this.profileRecord
      if (!provider || !record || !profileRecord) return false
      if (this.followUpsGeneratingCardIds.includes(cardId)) return false
      if (this.answerGeneratingCardIds.includes(cardId)) return false

      const card = record.cards.find((item) => item.id === cardId)
      if (!card) return false

      const followUpIds = card.followUps
        .filter((followUp) => Boolean(followUp.id) && !followUp.referenceAnswer?.answer)
        .map((followUp) => followUp.id)
      if (!followUpIds.length) return false

      this.followUpsGeneratingCardIds = [...this.followUpsGeneratingCardIds, cardId]
      this.error = ''
      try {
        const result = await generateFollowUpAnswers({
          provider,
          profile: profileRecord.profile,
          anchors: profileRecord.anchors,
          card: plain(card),
          followUpIds,
        })
        for (const item of result.answers) {
          const followUp = card.followUps.find((entry) => entry.id === item.followUpId)
          if (followUp) followUp.referenceAnswer = item.answer
        }
        await putPack(plain(record)).catch(() => undefined)
        await this.addRoomUsage(result.usage)
        if (record.useMode === 'checklist') {
          await this.syncChecklistSession().catch(() => undefined)
        }
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'AI 追问答案生成失败'
        message.error(this.error)
        return false
      } finally {
        this.followUpsGeneratingCardIds = this.followUpsGeneratingCardIds.filter(
          (id) => id !== cardId,
        )
      }
    },

    /**
     * 按用户思路改写一条 L1/L2/L3 追问。
     *
     * `level` 交给服务端锁定，前端也只回填 `question` / `intent`，改写不会改变层级。
     * 问法变了以后，原来的追问示范答案已经对不上，一并清空等待重新生成。
     * 成功返回改写摘要；素材缺失返回 null，接口失败直接抛出。
     */
    async rewriteFollowUp(
      cardId: string,
      followUpId: string,
      instruction: string,
    ): Promise<string | null> {
      const record = this.packRecord
      const profileRecord = this.profileRecord
      const text = instruction.trim()
      if (!record || !profileRecord || !text) return null

      const card = record.cards.find((item) => item.id === cardId)
      const followUp = card?.followUps.find((item) => item.id === followUpId)
      if (!card || !followUp) return null

      const projectName =
        profileRecord.profile.projects.find((item) => item.id === card.projectId)?.name ?? ''
      const result = await editContent({
        scene: 'follow_up',
        instruction: text,
        content: {
          id: followUp.id,
          level: followUp.level,
          question: followUp.question,
          intent: followUp.intent,
        },
        context: {
          projectName,
          mainQuestion: card.mainQuestion,
          mainIntent: card.intent,
          dimension: card.dimension,
          evidenceQuote: card.evidenceQuote,
          siblingQuestions: card.followUps
            .filter((item) => item.id && item.id !== followUp.id)
            .map((item) => ({ level: item.level, question: item.question })),
        },
        // 层级是追问的结构属性，不能随用户措辞漂移。
        lockedFields: ['id', 'level'],
      })

      const question =
        typeof result.content.question === 'string' ? result.content.question.trim() : ''
      if (!question) throw new Error('AI 没有返回可用的追问，请重试')
      const intent =
        typeof result.content.intent === 'string'
          ? result.content.intent.trim()
          : followUp.intent

      if (question !== followUp.question) {
        followUp.referenceAnswer = {
          thinking: '',
          answer: '',
          keyPoints: [],
          missingInfo: [],
          assumptions: [],
        }
      }
      followUp.question = question
      followUp.intent = intent
      record.usage = mergeUsage(record.usage, result.usage)
      await putPack(plain(record)).catch(() => undefined)
      if (record.useMode === 'checklist') {
        await this.syncChecklistSession().catch(() => undefined)
      }
      return result.summary ?? ''
    },

    /**
     * 按用户给的方向给一张卡补一条追问。
     *
     * 层级由服务端结合已有追问链判断；前端按 L1→L2→L3 插入，保持追问链的推进顺序。
     * 成功返回服务端摘要；素材缺失返回 null，接口失败直接抛出。
     */
    async addFollowUp(cardId: string, instruction: string): Promise<string | null> {
      const provider = providerOrWarn()
      const record = this.packRecord
      const profileRecord = this.profileRecord
      const text = instruction.trim()
      if (!provider || !record || !profileRecord || !text) return null
      if (this.followUpAddingCardIds.includes(cardId)) return null

      const card = record.cards.find((item) => item.id === cardId)
      if (!card) return null

      this.followUpAddingCardIds = [...this.followUpAddingCardIds, cardId]
      try {
        const result = await requestAddFollowUp({
          provider,
          profile: profileRecord.profile,
          anchors: profileRecord.anchors,
          card: plain(card),
          instruction: text,
        })
        const order = (level: string): number =>
          level === 'L1' ? 1 : level === 'L2' ? 2 : 3
        card.followUps = [...card.followUps, result.followUp].sort(
          (a, b) => order(a.level) - order(b.level),
        )
        record.usage = mergeUsage(record.usage, result.usage)
        await putPack(plain(record)).catch(() => undefined)
        if (record.useMode === 'checklist') {
          await this.syncChecklistSession().catch(() => undefined)
        }
        return result.summary || `已添加 ${LEVEL_LABEL[result.followUp.level]} 追问`
      } finally {
        this.followUpAddingCardIds = this.followUpAddingCardIds.filter(
          (id) => id !== cardId,
        )
      }
    },

    /** 删除一条追问；题包立即生效，清单历史快照同步更新。 */
    async deleteFollowUp(cardId: string, followUpId: string): Promise<boolean> {
      const record = this.packRecord
      const card = record?.cards.find((item) => item.id === cardId)
      if (!record || !card) return false
      const next = card.followUps.filter((item) => item.id !== followUpId)
      if (next.length === card.followUps.length) return false
      card.followUps = next
      await putPack(plain(record)).catch(() => undefined)
      if (record.useMode === 'checklist') {
        await this.syncChecklistSession().catch(() => undefined)
      }
      return true
    },

    /** 评价卡上的「生成 AI 示例回答」：按本轮记录生成，结果写回本次会话。 */
    async generateSample(): Promise<boolean> {
      const evaluation = this.evaluation
      if (!evaluation || this.samplePending || this.streaming) return false
      if (!evaluation.feedback && !evaluation.leaks.length) return false
      if (!this.threadId) return false
      const provider = providerOrWarn()
      if (!provider) return false

      const cardId = evaluation.cardId
      const question = this.pendingQuestion
      const answer = this.pendingAnswer
      this.samplePending = true
      try {
        const result = await requestSampleAnswer({
          provider,
          threadId: this.threadId,
          cardId,
          question,
        })
        const sample = (result.answer || '').trim()
        if (!sample) return false

        // 生成期间可能已开始下一题：只有评价仍是这一轮时才回填卡片。
        if (this.evaluation === evaluation) {
          this.evaluation = { ...evaluation, sampleAnswer: sample }
        }
        this.applySample(cardId, question, answer, sample)
        await this.addRoomUsage(result.usage)
        await this.persist()
        return true
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'AI 示例回答生成失败')
        return false
      } finally {
        this.samplePending = false
      }
    },

    /** 把示例回答写回本轮作答记录，刷新与复盘时仍能看到。 */
    applySample(
      cardId: string,
      question: string,
      answer: string,
      sample: string,
    ): void {
      const session = this.session
      if (!session) return

      const patch = (records: AnswerRecord[]): AnswerRecord[] | null => {
        const index = recordIndex(records, cardId, question, answer)
        if (index < 0) return null
        const next = [...records]
        next[index] = { ...next[index], sampleAnswer: sample }
        return next
      }

      const records = patch(session.records)
      if (records) session.records = records

      const summary = this.summary ?? session.summary
      if (!summary) return
      const summaryRecords = patch(summary.records)
      if (!summaryRecords) return
      const nextSummary = { ...summary, records: summaryRecords }
      if (this.summary) this.summary = nextSummary
      session.summary = nextSummary
    },

    /** 选中对话面试后创建检查点；第 4 步只消费已选方式的题包。 */
    async startInterview(): Promise<boolean> {
      const provider = providerOrWarn()
      if (!provider || !this.profileRecord || !this.packRecord) return false
      if (!this.packRecord.cards.length) {
        message.warning('没有可用题目，请重新生成')
        return false
      }
      if (this.packStale) {
        message.warning('简历画像已修改，请重新生成问题包')
        return false
      }
      if (this.creatingThread || this.streaming) return false

      this.creatingThread = true
      this.error = ''
      this.expired = false
      try {
        await this.retireActiveSessions(provider)
        const result = await createInterviewThread({
          profile: this.profileRecord.profile,
          anchors: this.profileRecord.anchors,
          cards: this.packRecord.cards,
          scene: this.packRecord.scene,
          followDepth: this.packRecord.followDepth,
          focus: this.packRecord.focus,
          useMode: 'dialog',
        })
        // 线程建好但拿不到首题说明服务端入座失败，不能留下一个没有当前题的「进行中」会话。
        const state = await getInterviewState(result.threadId).catch(() => null)
        if (!state || !state.currentQuestion) {
          throw new Error('面试未能正常开始，请重新发起')
        }
        this.packRecord.useMode = 'dialog'
        const projectNames = this.packRecord.projectIds
          .map(
            (id) =>
              this.profileRecord?.profile.projects.find((project) => project.id === id)?.name ??
              '',
          )
          .filter(Boolean)
        const session: SessionRecord = {
          threadId: result.threadId,
          packId: this.packRecord.id,
          useMode: 'dialog',
          scene: this.packRecord.scene,
          focus: this.packRecord.focus,
          projectNames,
          startedAt: Date.now(),
          endedAt: 0,
          status: 'active',
          records: [],
          currentIndex: 1,
          summary: null,
          teaching: [],
        }
        await putSession(plain(session))
        await putPack(plain(this.packRecord)).catch(() => undefined)
        this.session = session
        this.threadId = result.threadId
        this.checklistSessionId = ''
        this.reviewSession = null
        this.reviewPack = null
        this.summary = null
        this.evaluation = null
        this.teachingTurns = []
        this.teachingStream = ''
        writePointer({
          threadId: result.threadId,
          packId: this.packRecord.id,
          useMode: this.packRecord.useMode,
          scene: this.packRecord.scene,
        })
        this.applyState(state)
        this.history = await listSessions().catch(() => this.history)
        return true
      } catch (error) {
        this.error = error instanceof Error ? error.message : '面试创建失败'
        message.error(this.error)
        return false
      } finally {
        this.creatingThread = false
      }
    },

    /** 开新一场前收尾旧线程：发 end 让服务端生成正式复盘，再落到历史里。 */
    async retireActiveSessions(provider: ProviderSettings): Promise<void> {
      const sessions = await listSessions().catch(() => [] as SessionRecord[])
      for (const session of sessions) {
        if (session.status !== 'active') continue
        let summary: InterviewSummary | null = null
        let records = session.records
        let teaching = session.teaching ?? []
        try {
          await streamInterview(
            { threadId: session.threadId, action: 'end', provider },
            {
              onSummary: (event) => {
                summary = event
                records = mergeSamples(event.records, records)
              },
            },
          )
        } catch {
          // 线程可能已被清理或已是结束状态；下面按现有记录收尾。
        }
        const state = await getInterviewState(session.threadId).catch(() => null)
        if (state) {
          records = mergeSamples(state.records, records)
          teaching = state.teaching
          // 收尾时以检查点的整场累计为准，避免本地漏记。
          if (state.usage) session.usage = state.usage
        }
        let finalSummary = summary as InterviewSummary | null
        if (finalSummary) finalSummary = { ...finalSummary, records }
        else if (session.summary) finalSummary = { ...session.summary, records }
        await putSession(
          plain({
            ...session,
            status: 'finished' as const,
            endedAt: Date.now(),
            summary: finalSummary,
            records,
            teaching,
          }),
        )
      }
    },

    async runAction(
      action: InterviewAction,
      payload: { answer?: string; message?: string } = {},
    ): Promise<void> {
      if (this.streaming || !this.threadId) return
      const provider = providerOrWarn()
      if (!provider) return

      this.streaming = true
      this.error = ''
      this.samplePending = false
      if (action === 'answer') {
        this.evaluation = null
        this.evaluationPending = true
        this.pendingAnswer = payload.answer ?? ''
        this.pendingQuestion = this.question?.text ?? ''
      }
      if (action === 'reanswer') {
        // 回到上一题：收起上一轮评价，重新作答后再生成新的评价。
        this.evaluation = null
        this.evaluationPending = false
      }
      if (action === 'teach') {
        this.teachingTurns = []
        this.teachingStream = ''
      }
      if (action === 'return') this.teachingStream = ''

      try {
        await streamInterview(
          { threadId: this.threadId, action, ...payload, provider },
          {
            onStarted: () => {
              this.statusText = '面试已开始'
            },
            onTurnStart: (event) => {
              this.statusText = `正在评估第 ${event.index} 题…`
            },
            // 本轮新增用量；服务端的 state / summary 里是整场累计，这里只叠加增量。
            onUsage: ({ usage }) => {
              if (this.session) this.session.usage = mergeUsage(this.session.usage, usage)
            },
            onStatus: (event) => {
              this.statusText = event.text
            },
            onDelta: (event) => {
              if (event.stage === 'teaching') this.teachingStream += event.text
            },
            onQuestion: (event) => {
              this.question = event
              this.evaluationPending = false
              this.statusText = ''
              if (this.phase !== 'finished') this.phase = 'interviewing'
            },
            onEvaluation: (event) => {
              this.evaluation = event
              this.evaluationPending = false
              if (this.session) {
                const record: AnswerRecord = {
                  cardId: event.cardId,
                  question: this.question?.text ?? '',
                  answer: this.pendingAnswer,
                  source: event.source,
                  level: event.level || null,
                  leaks: event.leaks,
                  offTopic: event.offTopic,
                  feedback: event.feedback,
                  skipped: false,
                  createdAt: new Date().toISOString(),
                }
                this.session.records = [...this.session.records, record]
              }
            },
            onTeachingStarted: () => {
              this.phase = 'teaching'
              // 后端在大模型回复后才补记首条用户消息，先在这里对齐恢复时的形态。
              this.teachingTurns = [{ role: 'user', content: '我不会，请讲解这道题。' }]
              this.teachingStream = ''
              this.statusText = ''
            },
            onTeachingTurn: (event) => {
              if (event.role === 'teacher') this.teachingStream = ''
              this.teachingTurns = [
                ...this.teachingTurns,
                { role: event.role, content: event.text },
              ]
            },
            onTeachingClosed: () => {
              this.teachingStream = ''
              if (this.phase !== 'finished') this.phase = 'interviewing'
            },
            onState: (event) => {
              this.serverState = event
              this.threadId = event.threadId || this.threadId
              if (event.phase === 'finished') {
                this.phase = 'finished'
                this.question = null
              } else if (event.phase) {
                this.phase = event.phase
              }
              if (this.session) {
                this.session.records = mergeSamples(event.records, this.session.records)
                this.session.currentIndex = event.index
                this.session.teaching = event.teaching
              }
            },
            onSummary: (event) => {
              const records = mergeSamples(event.records, this.session?.records ?? [])
              this.summary = { ...event, records }
              this.question = null
              this.phase = 'finished'
              if (this.session) {
                this.session.summary = this.summary
                this.session.records = records
                if (this.serverState) this.session.teaching = this.serverState.teaching
                this.session.status = 'finished'
                this.session.endedAt = Date.now()
              }
            },
            onError: (event) => {
              this.error = event.message
              message.error(event.message)
              if (event.fatal && /过期|不存在/.test(event.message)) {
                this.expired = true
                if (this.session) {
                  this.session.status = 'finished'
                  this.session.endedAt = Date.now()
                }
              }
            },
          },
        )
      } catch (error) {
        this.error = error instanceof Error ? error.message : '面试请求失败'
        message.error(this.error)
        if (/过期|不存在/.test(this.error)) {
          this.expired = true
          if (this.session) {
            this.session.status = 'finished'
            this.session.endedAt = Date.now()
          }
        }
      } finally {
        this.streaming = false
        this.evaluationPending = false
        this.samplePending = false
        this.statusText = ''
        await this.persist()
      }
    },

    submitAnswer(text: string): Promise<void> {
      return this.runAction('answer', { answer: text })
    },

    skip(): Promise<void> {
      return this.runAction('skip')
    },

    /** 只跳过当前追问：主问题保留已答，进入下一张主问题。 */
    skipFollowup(): Promise<void> {
      return this.runAction('skip_followup')
    },

    /** 回到上一题重新作答；评价卡上的「重答本题」入口。 */
    reanswer(): Promise<void> {
      return this.runAction('reanswer')
    },

    teach(): Promise<void> {
      return this.runAction('teach')
    },

    teachMessage(text: string): Promise<void> {
      return this.runAction('teach_message', { message: text })
    },

    returnToInterview(): Promise<void> {
      return this.runAction('return')
    },

    endInterview(): Promise<void> {
      return this.runAction('end')
    },

    async persist(): Promise<void> {
      if (!this.session) return
      if (this.serverState) this.session.currentIndex = this.serverState.index
      await putSession(plain(this.session)).catch(() => undefined)
      this.history = await listSessions().catch(() => this.history)
    },

    async markSeen(cardId: string): Promise<void> {
      if (!this.packRecord) return
      if (this.packRecord.useMode === 'checklist') {
        const seen = this.packRecord.checklistSeenCardIds ?? []
        if (seen.includes(cardId)) return
        this.packRecord.checklistSeenCardIds = [...seen, cardId]
        const key = checklistSessionKey(this.packRecord.id)
        const session =
          this.history.find((item) => item.threadId === key) ??
          (await getSession(key).catch(() => null))
        if (session) {
          session.checklistSeenCardIds = this.packRecord.checklistSeenCardIds
          await putSession(plain(session)).catch(() => undefined)
        }
      } else {
        if (this.packRecord.seenCardIds.includes(cardId)) return
        this.packRecord.seenCardIds = [...this.packRecord.seenCardIds, cardId]
      }
      await putPack(plain(this.packRecord)).catch(() => undefined)
    },

    backToProfile(): void {
      this.phase = this.profileRecord ? 'profileReady' : 'idle'
    },

    backToChoosing(): void {
      this.phase = this.profileRecord ? 'choosing' : 'idle'
    },

    /** 上次线程已被清理：保留本地问题包，允许重新生成。 */
    restart(): void {
      this.expired = false
      this.summary = null
      this.evaluation = null
      this.question = null
      this.threadId = ''
      this.session = null
      this.reviewSession = null
      this.reviewPack = null
      this.phase = this.profileRecord ? 'choosing' : 'idle'
    },
  },
})
