import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

export type PolishMode = 'strict' | 'free' | 'enhance'

export async function polishTexts(
  texts: string[],
  description = '',
  mode: PolishMode = 'strict',
  context = '',
): Promise<string[]> {
  const p = getProviderSettings()
  const missing = missingProviderFields(p)
  if (missing.length) {
    throw new Error(`请先在「高级设置」填齐：${missing.join('、')}`)
  }

  const res = await apiFetch('/api/polish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: texts, provider: p, description, context, mode }),
  })
  const data = await unwrap<{ items: string[] }>(res, '润色失败')
  return data.items
}
