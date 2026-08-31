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
 * 收到 resume 事件把改好的简历 JSON 灌进简历 store，左栏预览随之更新。
 */
import { defineStore } from 'pinia'
import { sendChatMessage } from '@/api/chat'
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { useResumeStore } from '@/stores/resume'

/** 单条执行过程步骤：agent 生命周期 + 工具调用（折叠卡片里的灰字小列表） */
export type ChatStep =
  | { kind: 'agent_start'; agent: string; label: string }
  | { kind: 'agent_end'; agent: string; label: string }
  | { kind: 'tool_call'; tool: string; args: string }
  | { kind: 'tool_result'; tool: string; result: string }

/** 对话时间线的一条：用户消息 / 错误 / 阶段状态 / 某个 agent 的运行块 */
export type ChatItem =
  | { kind: 'user'; text: string }
  | { kind: 'error'; text: string }
  | { kind: 'status'; text: string; done: boolean }
  | { kind: 'agent'; agent: string; label: string; text: string; thinking: string; steps: ChatStep[]; thinkingOpen: boolean; toolsOpen: boolean; answerOpen: boolean; status: 'running' | 'done' }

/** 把 patch_content 的坐标参数格式化成可读串：[s:0 r:0 c:0 i:0] 新文字（超长截断） */
function formatToolArgs(tool: string, args: Record<string, unknown>): string {
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
  }),

  actions: {
    setJd(text: string) {
      this.jd = text
    },

    /** 发送一条消息：上屏用户气泡 → SSE 流式收各 agent 块 → 应用改好的简历 */
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
          onResume: ({ resume }) => {
            // 改好的简历 JSON 灌进简历 store，左栏预览随之更新
            // （importResume 会重生成全部 id，无碍：后端已保留原结构/样式）
            resumeStore.importResume(resume)
          },
        })
      } catch (err) {
        this.messages.push({ kind: 'error', text: `⚠️ ${err instanceof Error ? err.message : String(err)}` })
      } finally {
        this.sending = false
      }
    },

    clearMessages() {
      this.messages = []
    },
  },
})
