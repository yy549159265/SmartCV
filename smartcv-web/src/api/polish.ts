/**
 * "润色"接口
 *
 * 后端：POST /api/polish（见 smartcv-api/main.py）
 *   入参：{ items: string[], provider: {...} } —— 待润色的列表文字 + 供应商配置
 *   出参：统一响应 { code, message, data }，data 为 { items: string[] }
 *         条数与顺序与入参一致，前端按原位置写回列表。
 *   供应商配置未填齐：前端先拦截提示（不发请求）；后端 422 兜底，错误取 message。
 * 后端若改成 SSE 流式返回，可复用 @microsoft/fetch-event-source 逐字渲染。
 */
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

export async function polishTexts(texts: string[]): Promise<string[]> {
  const p = getProviderSettings()
  const missing = missingProviderFields(p)
  if (missing.length) {
    throw new Error(`请先在「供应商设置」填齐：${missing.join('、')}`)
  }

  const res = await apiFetch('/api/polish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: texts, provider: p }),
  })
  const data = await unwrap<{ items: string[] }>(res, '润色失败')
  return data.items
}
