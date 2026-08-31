/**
 * 导出统计接口
 *
 * 后端：GET /api/stats（读）、POST /api/stats/inc（+1）
 *   计数存后端文件（docker 里挂载 /opt/smartcv/stats），跨容器重建保留，
 *   所有访客共享一个全局累计值。
 */
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

export interface Stats {
  /** 导出 PDF 次数 */
  pdf: number
  /** 导出 JSON 次数 */
  json: number
}

/** 读取累计导出次数。 */
export async function getStats(): Promise<Stats> {
  const res = await apiFetch('/api/stats')
  return unwrap<Stats>(res, '加载统计数据失败')
}

/** 对应类型导出计数 +1，返回最新计数。 */
export async function incrementStats(kind: 'pdf' | 'json'): Promise<Stats> {
  const res = await apiFetch('/api/stats/inc', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
  return unwrap<Stats>(res, '更新统计数据失败')
}
