import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

export interface Stats {
  pdf: number
  json: number
}

export async function getStats(): Promise<Stats> {
  const res = await apiFetch('/api/stats')
  return unwrap<Stats>(res, '加载统计数据失败')
}

export async function incrementStats(kind: 'pdf' | 'json'): Promise<Stats> {
  const res = await apiFetch('/api/stats/inc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
  return unwrap<Stats>(res, '更新统计数据失败')
}
