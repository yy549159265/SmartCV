/**
 * "润色"接口
 *
 * 后端：POST /api/polish（见 smartcv-api/main.py）
 *   入参：{ items: string[], provider: {...}, description?: string, mode?: PolishMode }
 *         —— 待润色的列表文字 + 供应商配置 + 用户的润色描述/思路（可不填，空串 = 按默认规则润色）
 *            + 润色模式（默认 strict）
 *   出参：统一响应 { code, message, data }，data 为 { items: string[] }
 *         条数与顺序与入参一致，前端按原位置写回列表。
 *   供应商配置未填齐：前端先拦截提示（不发请求）；后端 422 兜底，错误取 message。
 * 后端若改成 SSE 流式返回，可复用 @microsoft/fetch-event-source 逐字渲染。
 */
import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

/**
 * 润色模式（后端按它选用不同的系统提示词）：
 *  - strict 严谨：规则锁死，只重构表达，不改变原文内容
 *  - free   自由：像直接问 AI，模型自主判断怎么写最好，可补充数据，并优先遵循用户思路
 * 两者差别在"改写自由度"：strict 只动表达，free 可放开写甚至补数据。
 */
export type PolishMode = 'strict' | 'free'

/**
 * @param texts       待润色的文本（一行一条，返回顺序与之一致）
 * @param description 用户的润色描述/思路，可不填（空串时后端按默认规则润色）
 * @param mode        润色模式，默认 strict（严谨）
 */
export async function polishTexts(
  texts: string[],
  description = '',
  mode: PolishMode = 'strict',
): Promise<string[]> {
  const p = getProviderSettings()
  const missing = missingProviderFields(p)
  if (missing.length) {
    throw new Error(`请先在「供应商设置」填齐：${missing.join('、')}`)
  }

  const res = await apiFetch('/api/polish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: texts, provider: p, description, mode }),
  })
  const data = await unwrap<{ items: string[] }>(res, '润色失败')
  return data.items
}
