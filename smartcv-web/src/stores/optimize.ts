/**
 * "优化简历"页面的状态仓库（Pinia）
 *
 * 存：jd（职位描述）+ messages（对话时间线）。
 *
 * 时间线是混合列表，每项是 user 气泡 / 错误气泡 / 某个 agent 的运行块：
 *   - 诊断 agent：过程（可折叠，含思考正文 + 生命周期步骤）
 *   - 优化 agent：过程（可折叠，含工具调用步骤）
 *   - 摘要 agent：回答（正常对话气泡，就是给用户看的修改说明）
 * 即：除 summarize 外都是"过程"，默认折叠；只有 summarize 的正文作为回答直接展示。
 *
 * send() 接 SSE 流式（后端经 agent 生命周期 custom 流推送），把 agent_start /
 * delta / tool_call / tool_result / agent_end 按 agent 归属记到对应的 agent 块上；
 * 收到 resume 事件【不直接覆盖简历】，而是存成 pendingDiff 由对比弹窗展示
 * （ResumeDiffDialog），用户点「应用修改」才走 applyPendingDiff 写回。
 */
import { defineStore } from 'pinia'
import {
  sendChatAnswers,
  sendChatMessage,
  type AskQuestion,
  type ChatAnswer,
} from '@/api/chat'
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { useResumeStore } from '@/stores/resume'
import { diffResume, mergeResume } from '@/utils/resumeDiff'
import type { Section } from '@/types'

/** 单条执行过程步骤：agent 生命周期 + 工具调用（折叠卡片里的灰字小列表） */
export type ChatStep =
  | { kind: 'agent_start'; agent: string; label: string }
  | { kind: 'agent_end'; agent: string; label: string }
  | { kind: 'tool_call'; tool: string; args: string }
  | { kind: 'tool_result'; tool: string; result: string }

/** 诊断 agent 的反问卡片：pending → submitting → answered（或超时 expired） */
export type QuestionItem = {
  kind: 'question'
  questionId: string
  title: string
  questions: AskQuestion[]
  status: 'pending' | 'submitting' | 'answered' | 'expired'
  /** 用户提交的答案；null = 还没回答 */
  answers: ChatAnswer[] | null
  /** 后端等待回答的秒数 */
  timeoutSeconds: number
  /** 本地截止时间（epoch ms），卡片据此做倒计时 */
  expiresAt: number
}

/** 对话时间线的一条：用户消息 / 错误 / 阶段状态 / 反问 / 某个 agent 的运行块 */
export type ChatItem =
  | { kind: 'user'; text: string }
  | { kind: 'error'; text: string }
  | { kind: 'status'; text: string; done: boolean }
  | QuestionItem
  | { kind: 'agent'; agent: string; label: string; text: string; thinking: string; steps: ChatStep[]; thinkingOpen: boolean; toolsOpen: boolean; answerOpen: boolean; status: 'running' | 'done' }

/** 在时间线里按 questionId 找反问卡片 */
function findQuestion(messages: ChatItem[], questionId: string): QuestionItem | undefined {
  return messages.find(
    (m): m is QuestionItem => m.kind === 'question' && m.questionId === questionId,
  )
}

/**
 * 取（必要时补上）pendingDiff.reverted。
 *
 * 旧的 pendingDiff 可能没有这个字段（开发时 HMR 会保留上一次的 store 状态），
 * 直接 `pending.reverted.indexOf` 会抛异常 —— 表现就是"点切换按钮一点反应都没有"。
 * 所有读写 reverted 的地方都必须经过这里。
 */
function revertedList(pending: { reverted: string[] }): string[] {
  if (!Array.isArray(pending.reverted)) pending.reverted = []
  return pending.reverted
}

/** 把 patch_content 的坐标参数格式化成可读串：[s:0 r:0 c:0 i:0] 新文字（超长截断） */
function formatToolArgs(tool: string, args: Record<string, unknown>): string {
  if (tool === 'ask_user_question') {
    return `${String(args.title ?? '向用户反问')} · ${String(args.questions ?? 0)} 个问题`
  }
  if (tool !== 'patch_content') return JSON.stringify(args)
  const { s, r, c, i } = args
  const text = String(args.text ?? '')
  const shown = text.length > 40 ? `${text.slice(0, 40)}…` : text
  return `[s:${s} r:${r} c:${c} i:${i}] ${shown}`
}

export const useOptimizeStore = defineStore('optimize', {
  state: () => ({
    /** 职位描述（JD），可选 */
    jd: '',
    /** 对话时间线 */
    messages: [] as ChatItem[],
    /** 是否正在等待 AI 回复 */
    sending: false,
    /**
     * 待确认的 AI 修改：{改前快照, 改后简历, 已还原的改动 key}。
     * 后端返回后先放这里、不进简历 store —— 用户点「确定应用」才落库。
     * reverted 放这里而不是弹窗组件里：关掉弹窗再打开（对话栏头有入口），
     * 用户逐处还原的选择不会丢。
     */
    pendingDiff: null as { before: Section[]; after: Section[]; reverted: string[] } | null,
    /** 对比弹窗是否展开（关掉弹窗 pendingDiff 仍保留，可从对话栏头再打开） */
    diffOpen: false,
  }),

  actions: {
    setJd(text: string) {
      this.jd = text
    },

    /** 发送一条消息：上屏用户气泡 → SSE 流式收各 agent 块 → 收下改好的简历待用户确认 */
    async send(text: string) {
      const trimmed = text.trim()
      if (!trimmed || this.sending) return

      // 供应商配置没填齐就拦截，别浪费一次请求（后端 422 是兜底）
      const provider = getProviderSettings()
      const missing = missingProviderFields(provider)
      if (missing.length) {
        this.messages.push({ kind: 'error', text: `⚠️ 请先在「供应商设置」填齐：${missing.join('、')}` })
        return
      }

      const resumeStore = useResumeStore()
      this.messages.push({ kind: 'user', text: trimmed })
      this.sending = true

      // 改前快照：必须在发请求前【深拷贝】——
      // resume 是响应式代理，且流式期间用户还能继续编辑，
      // 不拷贝的话比对的"改前"会跟着变，diff 就成了自己跟自己比。
      const before = JSON.parse(JSON.stringify(resumeStore.resume)) as Section[]

      // 当前正在积累的 agent 块 = 时间线里最后一个 kind==='agent' 的项
      const lastAgent = (): Extract<ChatItem, { kind: 'agent' }> | null => {
        for (let i = this.messages.length - 1; i >= 0; i--) {
          const m = this.messages[i]
          if (m.kind === 'agent') return m
        }
        return null
      }

      try {
        await sendChatMessage(trimmed, this.jd, resumeStore.resume, provider, {
          // convert 阶段（纯代码，非 agent）：显示「正在解析 → 已完成」一条状态
          onStatus: (_stage, text) => {
            const last = this.messages[this.messages.length - 1]
            const done = /已|完成/.test(text)
            if (last && last.kind === 'status') {
              last.text = text
              last.done = done
            } else {
              this.messages.push({ kind: 'status', text, done })
            }
          },
          // 每个 agent 单独开一个块。生命周期用 status：running → done；
          // 思考(reasoning_content) 进 thinking，正文(content) 进 text，前端分区展示。
          onAgentStart: (agent, label) => {
            this.messages.push({ kind: 'agent', agent, label, text: '', thinking: '', steps: [], thinkingOpen: false, toolsOpen: false, answerOpen: true, status: 'running' })
          },
          onDelta: (_stage, tok, kind) => {
            const b = lastAgent()
            if (!b) return
            if (kind === 'thinking') b.thinking += tok
            else b.text += tok
          },
          onToolCall: (tool, args) => {
            lastAgent()?.steps.push({ kind: 'tool_call', tool, args: formatToolArgs(tool, args) })
          },
          onToolResult: (tool, result) => {
            const short = result.length > 60 ? `${result.slice(0, 60)}…` : result
            lastAgent()?.steps.push({ kind: 'tool_result', tool, result: short })
          },
          onAgentEnd: () => {
            const b = lastAgent()
            if (b) b.status = 'done'
          },
          // 诊断 agent 反问：插一张选择题卡片。原 SSE 流保持连接，后端在等答案。
          onAskQuestion: (payload) => {
            const timeoutSeconds = payload.timeoutSeconds ?? 300
            this.messages.push({
              kind: 'question',
              questionId: payload.questionId,
              title: payload.title,
              questions: payload.questions,
              status: 'pending',
              answers: null,
              timeoutSeconds,
              expiresAt: Date.now() + timeoutSeconds * 1000,
            })
          },
          onAskQuestionClosed: (questionId) => {
            const item = findQuestion(this.messages, questionId)
            if (item && item.status === 'pending') item.status = 'expired'
          },
          onResume: ({ resume }) => {
            // 【不覆盖简历】先把「改前 / 改后」存起来，弹对比窗让用户过目。
            // 这里直接用后端返回的原始 JSON、不走 normalizeResumeData：
            // 后者会给每个节点重新生成 uid，两边 id 一失配，
            // 比对就会把整份简历判成"全变了"（后端 patch 是就地的，id 原样保留）。
            this.pendingDiff = { before, after: resume as Section[], reverted: [] }
            this.diffOpen = true
          },
        })
      } catch (err) {
        this.messages.push({ kind: 'error', text: `⚠️ ${err instanceof Error ? err.message : String(err)}` })
      } finally {
        this.sending = false
        // 流已结束，还挂着的反问卡不可能再被后端接收 —— 置为失效
        for (const m of this.messages) {
          if (m.kind === 'question' && (m.status === 'pending' || m.status === 'submitting')) {
            m.status = 'expired'
          }
        }
      }
    },

    /**
     * 提交反问的答案（空数组 = 跳过）。
     *
     * 这里是独立请求，不走 /api/chat 的流：后端拿着原 SSE 连接暂停等待，
     * POST 成功后原流继续输出诊断/优化/总结，所以这里只负责把卡片状态改好。
     */
    async submitQuestionAnswers(questionId: string, answers: ChatAnswer[]) {
      const item = findQuestion(this.messages, questionId)
      if (!item || item.status !== 'pending') return
      item.status = 'submitting'
      try {
        await sendChatAnswers(questionId, answers)
        item.answers = answers
        item.status = 'answered'
      } catch (err) {
        item.status = 'pending'
        this.messages.push({ kind: 'error', text: `⚠️ ${err instanceof Error ? err.message : String(err)}` })
      }
    },

    /** 重新打开对比弹窗（关掉之后对话栏头的入口用） */
    openDiff() {
      if (this.pendingDiff) this.diffOpen = true
    },

    /** 切换某一处改动：接受 ↔ 还原（弹窗里每个 ↺ / ↻ 按钮都走这里） */
    toggleDiffChange(key: string) {
      const pending = this.pendingDiff
      if (!pending) return
      const reverted = revertedList(pending)
      const i = reverted.indexOf(key)
      if (i >= 0) reverted.splice(i, 1)
      else reverted.push(key)
    },

    /** 全部还原：整份简历保持 AI 修改前的样子 */
    revertAllDiff() {
      const pending = this.pendingDiff
      if (!pending) return
      pending.reverted = diffResume(pending.before, pending.after).changes.map((c) => c.key)
    },

    /** 全部接受：回到刚收到 AI 结果时的状态 */
    acceptAllDiff() {
      const pending = this.pendingDiff
      if (pending) pending.reverted = []
    },

    /**
     * 收起对比弹窗但【保留】pendingDiff：简历不动，对话栏头还留着入口，
     * 用户可以再看看对话内容，想好了再点开决定要不要应用。
     */
    dismissDiff() {
      this.diffOpen = false
    },

    /**
     * 应用（已逐处筛选过的）AI 修改：这时候才真正写回简历。
     *
     * 不是原样导入 after，而是按用户的还原选择 merge 之后的结果：
     *  - 改：还原的处用回修改前的内容；
     *  - 删：还原的处插回简历；
     *  - 增：还原的处直接剔除（keepIgnored = false）。
     * 全部还原时不写回（内容和改前完全一样），直接关掉弹窗。
     *
     * importResume 会重生成全部 id 并整体替换（既有的、正确的落库路径），
     * 它同时会被 main.ts 的 $onAction 记一次撤销快照 → 用户 Ctrl+Z 能撤回本次修改。
     *
     * @returns 是否真的改动了简历
     */
    applyPendingDiff(): boolean {
      const pending = this.pendingDiff
      if (!pending) return false

      const reverted = new Set(revertedList(pending))
      const { changes } = diffResume(pending.before, pending.after)
      const allReverted = changes.length > 0 && changes.every((c) => reverted.has(c.key))

      // 先清 pending 再导入：导入若失败也不会留下一个已被用过的待确认状态
      this.pendingDiff = null
      this.diffOpen = false
      if (allReverted) return false

      const { sections } = mergeResume(pending.before, pending.after, reverted, {
        keepIgnored: false,
      })
      useResumeStore().importResume(sections)
      return true
    },

    /** 清空对话：连同"待确认的 AI 修改"一起作废（新会话不该还挂着上次的提案） */
    clearMessages() {
      this.messages = []
      this.pendingDiff = null
      this.diffOpen = false
    },
  },
})
