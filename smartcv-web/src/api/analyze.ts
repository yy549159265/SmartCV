import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { Section } from '@/types'

export interface ResumeAnalysis {
  direction: string
  highlights: string
}

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
