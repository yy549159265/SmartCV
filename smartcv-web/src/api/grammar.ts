import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import type { Section } from '@/types'

export interface GrammarChange {
  level: 'text' | 'title'
  location: string
  before: string
  after: string
  reason: string
}

export type GrammarSkipped = GrammarChange

export interface GrammarStats {
  checkedUnits: number
  fixed: number
  skipped: number
  titleFixed: number
}

export interface GrammarResult {
  resume: Section[]
  changes: GrammarChange[]
  skipped: GrammarSkipped[]
  stats: GrammarStats
}

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
