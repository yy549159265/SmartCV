/**
 * 简历分析接口 —— 优秀示例库上传前，让 AI 判断这份简历适合投什么方向、好在哪。
 *
 * 后端：POST /api/analyze（见 smartcv-api/routers/agent.py）
 *   入参：{ resume: Section[], provider: {...} }
 *   出参：{ items: [职业名称, 可借鉴的写法] }，固定 2 条、顺序固定。
 *
 * 隐私：只读分析，后端不保存简历，返回后即丢弃。
 */
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { Section } from '@/types'

/** 分析结果：两个位置的语义固定，不要按顺序猜 */
export interface ResumeAnalysis {
  /** 第 1 条：职业名称，2-3 个，用「、」分隔 */
  direction: string
  /** 第 2 条：可借鉴的写法，1. 2. 3. 编号，一条一行 */
  highlights: string
}

/**
 * 分析一份简历。
 * @param resume 简历章节数组（与「导出 JSON」格式一致）；为空时直接抛错，不发请求
 */
export async function analyzeResume(resume: Section[]): Promise<ResumeAnalysis> {
  if (!resume.length) throw new Error('请先上传 JSON')

  const p = getProviderSettings()
  const missing = missingProviderFields(p)
  if (missing.length) {
    throw new Error(`请先在「高级设置」填齐：${missing.join('、')}`)
  }

  const res = await apiFetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume, provider: p }),
  })
  const data = await unwrap<{ items: string[] }>(res, '简历分析失败')
  const items = Array.isArray(data?.items) ? data.items : []
  return {
    direction: String(items[0] ?? '').trim(),
    highlights: String(items[1] ?? '').trim(),
  }
}
