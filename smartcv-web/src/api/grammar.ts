/**
 * 全文纠错接口
 *
 * 后端：POST /api/grammar（见 smartcv-api/routers/agent.py）
 *   入参：{ resume: Section[], provider }
 *   出参：{ code, message, data: { resume, changes, skipped, stats } }
 *
 * 只修正简历正文与章节标题的语法 / 拼写 / 标点：模型返回坐标和完整改后文字，
 * 后端按坐标就地写入并做校验；前端拿到结果后复用「AI 修改对比」弹窗确认。
 */
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { Section } from '@/types'

/** 一条已应用的纠错 */
export interface GrammarChange {
  /** text = 正文文字单元；title = 章节标题 */
  level: 'text' | 'title'
  /** 人能看懂的位置（章节标题 / 第 N 条） */
  location: string
  before: string
  after: string
  reason: string
}

/** 一条未应用的纠错建议（原文核对失败、会新增数字等） */
export type GrammarSkipped = GrammarChange

export interface GrammarStats {
  /** 检查了多少个正文文字单元 */
  checkedUnits: number
  /** 实际应用了多少处（含标题） */
  fixed: number
  /** 有多少条建议被校验拦下 */
  skipped: number
  /** 其中标题修正多少处 */
  titleFixed: number
}

export interface GrammarResult {
  resume: Section[]
  changes: GrammarChange[]
  skipped: GrammarSkipped[]
  stats: GrammarStats
}

/**
 * 对整份简历做语法 / 拼写 / 标点纠错。
 * 供应商配置未填齐时前端先拦下；后端 422/500 的 message 会原样抛给调用方。
 */
export async function checkResumeGrammar(resume: Section[]): Promise<GrammarResult> {
  const provider = getProviderSettings()
  const missing = missingProviderFields(provider)
  if (missing.length) {
    throw new Error(`请先在「高级设置」填齐：${missing.join('、')}`)
  }

  const res = await apiFetch('/api/grammar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume, provider }),
  })
  return unwrap<GrammarResult>(res, '全文纠错失败')
}
