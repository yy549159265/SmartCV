import type { Section } from '@/types'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

interface IndexEntry {
  name: string
  title?: string
  size?: number
}

export interface ExampleItem {
  name: string
  title: string
  order: number
  size: number
}

function parseName(name: string): { order: number; title: string } {
  const stem = name.replace(/\.json$/i, '')
  const matched = /^(\d+)\s*[-_.、\s]\s*(.+)$/.exec(stem)
  if (matched) return { order: Number(matched[1]), title: matched[2].trim() }
  return { order: Number.MAX_SAFE_INTEGER, title: stem }
}

export async function listExamples(_force = false): Promise<ExampleItem[]> {
  const res = await apiFetch('/api/examples')
  const entries = await unwrap<IndexEntry[]>(res, '读取示例清单失败')
  if (!Array.isArray(entries)) throw new Error('示例清单格式不正确')

  return entries
    .filter((e) => e !== null && typeof e === 'object' && typeof e.name === 'string' && /\.json$/i.test(e.name))
    .map((e) => {
      const parsed = parseName(e.name)
      return {
        name: e.name,
        title: e.title || parsed.title,
        size: typeof e.size === 'number' ? e.size : 0,
        order: parsed.order,
      }
    })
    .sort((a, b) => a.order - b.order || a.name.localeCompare(b.name))
}

const contentCache = new Map<string, unknown>()

export function clearExampleCache(): void {
  contentCache.clear()
}

export async function loadExample(item: ExampleItem): Promise<unknown> {
  const hit = contentCache.get(item.name)
  if (hit !== undefined) return hit

  const res = await apiFetch(`/api/examples/${encodeURIComponent(item.name)}`)
  const data = await unwrap<unknown>(res, '读取示例失败')
  contentCache.set(item.name, data)
  return data
}

export function toSections(data: unknown): Section[] | null {
  if (!Array.isArray(data) || data.length === 0) return null
  const ok = data.every(
    (s) => s !== null && typeof s === 'object' && Array.isArray((s as Section).rows),
  )
  return ok ? (data as Section[]) : null
}
