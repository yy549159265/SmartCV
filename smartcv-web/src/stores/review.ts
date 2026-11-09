import { defineStore } from 'pinia'
import {
  sendChatAnswers,
  sendChatMessage,
  type AskQuestion,
  type ChatAnswer,
  type DiagnosisItem,
  type ReferenceExampleItem,
  type RewriteMode,
  type WebSearchItem,
} from '@/api/chat'
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { useResumeStore } from '@/stores/resume'
import { diffResume, mergeResume } from '@/utils/resumeDiff'
import type { Section } from '@/types'

export type ChatStep =
  | { kind: 'agent_start'; agent: string; label: string }
  | { kind: 'agent_end'; agent: string; label: string }
  | { kind: 'tool_call'; tool: string; args: string }
  | { kind: 'tool_result'; tool: string; result: string }

export type QuestionItem = {
  kind: 'question'
  questionId: string
  title: string
  questions: AskQuestion[]
  status: 'pending' | 'submitting' | 'answered' | 'expired'
  answers: ChatAnswer[] | null
  timeoutSeconds: number
  expiresAt: number
}

export type ChatItem =
  | { kind: 'user'; text: string }
  | { kind: 'error'; text: string }
  | { kind: 'status'; text: string; done: boolean }
  | {
      kind: 'agent'
      agent: string
      label: string
      text: string
      thinking: string
      steps: ChatStep[]
      thinkingOpen: boolean
      toolsOpen: boolean
      answerOpen: boolean
      diagnosis: DiagnosisItem[]
      lead: string
      markdown: string
      markdownOpen: boolean
      questions: QuestionItem[]
      questionsOpen: boolean
      searches: WebSearchItem[]
      searchesOpen: boolean
      references: ReferenceExampleItem[]
      styleNotes: string[]
      examplesOpen: boolean
      nodeOpen: boolean
      status: 'running' | 'done'
    }

function findQuestion(messages: ChatItem[], questionId: string): QuestionItem | undefined {
  for (const m of messages) {
    if (m.kind !== 'agent') continue
    const hit = m.questions.find((q) => q.questionId === questionId)
    if (hit) return hit
  }
  return undefined
}

function revertedList(pending: { reverted: string[] }): string[] {
  if (!Array.isArray(pending.reverted)) pending.reverted = []
  return pending.reverted
}

function formatToolArgs(tool: string, args: Record<string, unknown>): string {
  if (tool === 'ask_user_question') {
    return `${String(args.title ?? '向用户反问')} · ${String(args.questions ?? 0)} 个问题`
  }
  if (tool === 'web_search') return String(args.query ?? '')
  if (tool !== 'patch_content') return JSON.stringify(args)
  const decision = args.decision === 'change' ? '需要修改' : '不修改'
  const head = `诊断 ${String(args.index ?? '?')} · ${decision}`
  const text = String(args.text ?? '')
  if (args.decision === 'change' && text) {
    const shown = text.length > 40 ? `${text.slice(0, 40)}…` : text
    return `${head} → ${shown}`
  }
  return head
}

export const useReviewStore = defineStore('review', {
  state: () => ({
    jd: '',
    referenceIds: [] as string[],
    rewriteMode: 'standard' as RewriteMode,
    messages: [] as ChatItem[],
    sending: false,
    pendingDiff: null as {
      before: Section[]
      after: Section[]
      reverted: string[]
      source?: 'chat' | 'grammar'
    } | null,
    diffOpen: false,
  }),

  actions: {
    setJd(text: string) {
      this.jd = text
    },

    setReferenceIds(ids: string[]) {
      this.referenceIds = ids.slice(0, 3)
    },

    setRewriteMode(mode: RewriteMode) {
      this.rewriteMode = mode
    },

    setPendingDiff(before: Section[], after: Section[], source: 'chat' | 'grammar' = 'chat') {
      this.pendingDiff = { before, after, reverted: [], source }
      this.diffOpen = true
    },

    async send(text: string) {
      const trimmed = text.trim()
      if (!trimmed || this.sending) return

      const provider = getProviderSettings()
      const missing = missingProviderFields(provider)
      if (missing.length) {
        this.messages.push({ kind: 'error', text: `⚠️ 请先在「高级设置」填齐：${missing.join('、')}` })
        return
      }

      const resumeStore = useResumeStore()
      this.messages.push({ kind: 'user', text: trimmed })
      this.sending = true

      const before = JSON.parse(JSON.stringify(resumeStore.resume)) as Section[]

      const lastAgent = (): Extract<ChatItem, { kind: 'agent' }> | null => {
        for (let i = this.messages.length - 1; i >= 0; i--) {
          const m = this.messages[i]
          if (m.kind === 'agent') return m
        }
        return null
      }

      const diagnosisOwner = (): Extract<ChatItem, { kind: 'agent' }> | null => {
        for (let i = this.messages.length - 1; i >= 0; i--) {
          const m = this.messages[i]
          if (m.kind === 'agent' && m.agent === 'diagnose' && m.diagnosis.length) return m
        }
        return null
      }

      try {
        await sendChatMessage(trimmed, this.jd, resumeStore.resume, provider, [...this.referenceIds], this.rewriteMode, {
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
          onAgentStart: (agent, label) => {
            let lead = ''
            const prev = this.messages[this.messages.length - 1]
            if (agent === 'diagnose' && prev?.kind === 'status') {
              lead = prev.text
              this.messages.pop()
            }
            this.messages.push({ kind: 'agent', agent, label, text: '', thinking: '', steps: [], thinkingOpen: false, toolsOpen: false, answerOpen: true, diagnosis: [], lead, markdown: '', markdownOpen: false, questions: [], questionsOpen: false, searches: [], searchesOpen: false, references: [], styleNotes: [], examplesOpen: false, nodeOpen: agent === 'summarize', status: 'running' })
          },
          onResumeMarkdown: (text) => {
            const b = lastAgent()
            if (b) b.markdown = text
          },
          onReferenceExamples: (items) => {
            const b = lastAgent()
            if (b) b.references = items
          },
          onWebSearch: (item) => {
            lastAgent()?.searches.push(item)
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
          onDiagnosis: (items, styleNotes) => {
            const b = lastAgent()
            if (!b) return
            b.diagnosis = items.map((it) => ({ ...it, status: 'pending', note: '' }))
            b.styleNotes = styleNotes
          },
          onDiagnosisStatus: ({ index, status, reason }) => {
            const item = diagnosisOwner()?.diagnosis[index]
            if (!item) return
            item.status = status
            item.note = reason
          },
          onAskQuestion: (payload) => {
            const owner = [...this.messages]
              .reverse()
              .find((m) => m.kind === 'agent' && m.agent === 'diagnose')
            if (!owner || owner.kind !== 'agent') return
            const timeoutSeconds = payload.timeoutSeconds ?? 300
            owner.questions.push({
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
            this.setPendingDiff(before, resume as Section[], 'chat')
          },
        })
      } catch (err) {
        this.messages.push({ kind: 'error', text: `⚠️ ${err instanceof Error ? err.message : String(err)}` })
      } finally {
        this.sending = false
        for (const m of this.messages) {
          if (m.kind !== 'agent') continue
          for (const q of m.questions) {
            if (q.status === 'pending' || q.status === 'submitting') q.status = 'expired'
          }
        }
      }
    },

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

    openDiff() {
      if (this.pendingDiff) this.diffOpen = true
    },

    toggleDiffChange(key: string) {
      const pending = this.pendingDiff
      if (!pending) return
      const reverted = revertedList(pending)
      const i = reverted.indexOf(key)
      if (i >= 0) reverted.splice(i, 1)
      else reverted.push(key)
    },

    revertAllDiff() {
      const pending = this.pendingDiff
      if (!pending) return
      pending.reverted = diffResume(pending.before, pending.after).changes.map((c) => c.key)
    },

    acceptAllDiff() {
      const pending = this.pendingDiff
      if (pending) pending.reverted = []
    },

    dismissDiff() {
      this.diffOpen = false
    },

    discardPendingDiff() {
      this.pendingDiff = null
      this.diffOpen = false
    },

    applyPendingDiff(): boolean {
      const pending = this.pendingDiff
      if (!pending) return false

      const reverted = new Set(revertedList(pending))
      const { changes } = diffResume(pending.before, pending.after)
      const allReverted = changes.length > 0 && changes.every((c) => reverted.has(c.key))

      this.pendingDiff = null
      this.diffOpen = false
      if (allReverted) return false

      const { sections } = mergeResume(pending.before, pending.after, reverted, {
        keepIgnored: false,
      })
      useResumeStore().importResume(sections)
      return true
    },

    clearMessages() {
      this.messages = []
      this.pendingDiff = null
      this.diffOpen = false
    },
  },
})
