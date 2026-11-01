/**
 * 优秀示例库接口 —— 诊断时可挑选参考的他人简历范例。
 *
 * 后端：smartcv-api/services/reference_examples.py（JSON 文件存储）
 *   GET  /api/reference-examples       列表（只回元数据，不带简历正文）
 *   GET  /api/reference-examples/{id}  详情（含完整 Section[]）
 *   POST /api/reference-examples       新增
 *
 * 设计约束（与后端一致）：
 *   - 示例库全局共享，没有用户区分；
 *   - 只读：只有列表 / 详情 / 新增，没有编辑和删除接口。
 */
import { apiFetch } from '@/api/http'
import { unwrap } from '@/api/error'
import type { Section } from '@/types'

/** 列表里的单条示例（缩略图按需再取详情） */
export interface ReferenceExampleMeta {
  /** 32 位十六进制 uuid，用作后端文件名 */
  id: string
  /** 适用职业方向，如「后端开发」 */
  direction: string
  /** 优秀简历描述：这份示例好在哪里、适合参考什么 */
  description: string
  /** 上传时间（UTC ISO 字符串） */
  createdAt: string
  /** 章节数量（列表页展示用） */
  sectionCount: number
}

/** 详情：元数据 + 完整简历 JSON */
export interface ReferenceExample extends ReferenceExampleMeta {
  resume: Section[]
}

/** 新增示例的入参 */
export interface ReferenceExampleInput {
  direction: string
  description: string
  resume: Section[]
}

/** 列出全部优秀示例（按上传时间倒序，新的在前） */
export async function listReferenceExamples(): Promise<ReferenceExampleMeta[]> {
  const res = await apiFetch('/api/reference-examples')
  const list = await unwrap<ReferenceExampleMeta[]>(res, '读取优秀示例失败')
  return Array.isArray(list) ? list : []
}

/** 读取一份示例的完整内容 */
export async function getReferenceExample(id: string): Promise<ReferenceExample> {
  const res = await apiFetch(`/api/reference-examples/${encodeURIComponent(id)}`)
  const data = await unwrap<ReferenceExample>(res, '读取优秀示例失败')
  if (!data || !Array.isArray(data.resume)) throw new Error('示例内容格式不正确')
  return data
}

/** 新增一份示例（提交后不可编辑、不可删除） */
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
