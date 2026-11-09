import { apiFetch } from '@/api/http'
import { unwrap } from '@/api/error'
import type { Section } from '@/types'

export interface ReferenceExampleMeta {
  id: string
  direction: string
  description: string
  createdAt: string
  sectionCount: number
}

export interface ReferenceExample extends ReferenceExampleMeta {
  resume: Section[]
}

export interface ReferenceExampleInput {
  direction: string
  description: string
  resume: Section[]
}

export async function listReferenceExamples(): Promise<ReferenceExampleMeta[]> {
  const res = await apiFetch('/api/reference-examples')
  const list = await unwrap<ReferenceExampleMeta[]>(res, '读取优秀示例失败')
  return Array.isArray(list) ? list : []
}

export async function getReferenceExample(id: string): Promise<ReferenceExample> {
  const res = await apiFetch(`/api/reference-examples/${encodeURIComponent(id)}`)
  const data = await unwrap<ReferenceExample>(res, '读取优秀示例失败')
  if (!data || !Array.isArray(data.resume)) throw new Error('示例内容格式不正确')
  return data
}

export async function createReferenceExample(
  input: ReferenceExampleInput,
): Promise<ReferenceExampleMeta> {
  const res = await apiFetch('/api/reference-examples', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  return unwrap<ReferenceExampleMeta>(res, '上传优秀示例失败')
}
