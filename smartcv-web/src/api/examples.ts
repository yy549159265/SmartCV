/**
 * 示例模板接口 —— 数据源是本机后端 smartcv-api/example/ 目录。
 *
 * 清单和文件都走后端接口（GET /api/examples、GET /api/examples/{name}），
 * 不再依赖 GitHub。新增示例只要往 smartcv-api/example/ 丢一个 json、
 * 在 index.json 里登记一行，前端不用改代码、也不用重新构建。
 *
 * 维护：新增/删除示例后，在 smartcv-web 下运行 `npm run examples:index`
 *   重新生成 index.json（见 scripts/gen-example-index.mjs）。
 *
 * 命名约定：`01-经典左头图.json` → 序号 1、标题「经典左头图」。
 *   不按这个约定命名也能用，只是排到最后、标题直接取文件名。
 */
import type { Section } from '@/types'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'

/** index.json 里的单个条目：name 必填，title/size 省略时由文件名推导或显示为 0 */
interface IndexEntry {
  name: string
  title?: string
  size?: number
}

/** 画廊里的一张示例卡片 */
export interface ExampleItem {
  /** 示例文件名，如 01-经典左头图.json */
  name: string
  /** 展示用标题（清单里的 title，没有则从文件名解析） */
  title: string
  /** 排序号（文件名前缀数字；没写前缀的排到最后） */
  order: number
  /** 文件大小（字节；清单里没写就是 0） */
  size: number
}

/** 把文件名解析成「序号 + 标题」：`01-经典左头图.json` → 1 / 经典左头图 */
function parseName(name: string): { order: number; title: string } {
  const stem = name.replace(/\.json$/i, '')
  const matched = /^(\d+)\s*[-_.、\s]\s*(.+)$/.exec(stem)
  if (matched) return { order: Number(matched[1]), title: matched[2].trim() }
  // 没按 `<序号>-<标题>` 命名的：排到最后，标题就用去掉扩展名的文件名
  return { order: Number.MAX_SAFE_INTEGER, title: stem }
}

/**
 * 列出后端 example/ 下的所有示例（按序号排序）。
 * 清单是本地文件，没有缓存；force 参数保留给画廊的「重试」按钮（触发内容缓存作废）。
 */
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
        // 清单里显式写了 title 就用它，否则按文件名约定推导
        title: e.title || parsed.title,
        size: typeof e.size === 'number' ? e.size : 0,
        order: parsed.order,
      }
    })
    .sort((a, b) => a.order - b.order || a.name.localeCompare(b.name))
}

/** 已拉取过的示例内容（key = 文件名）—— 点「使用」时不用再请求一次 */
const contentCache = new Map<string, unknown>()

/** 作废已下载的示例内容 —— 刷新时必须调，否则缩略图还是旧 JSON */
export function clearExampleCache(): void {
  contentCache.clear()
}

/** 从后端读取一份示例文件，返回原始 JSON（结构校验交给 toSections / store） */
export async function loadExample(item: ExampleItem): Promise<unknown> {
  const hit = contentCache.get(item.name)
  if (hit !== undefined) return hit

  const res = await apiFetch(`/api/examples/${encodeURIComponent(item.name)}`)
  const data = await unwrap<unknown>(res, '读取示例失败')
  contentCache.set(item.name, data)
  return data
}

/**
 * 宽松校验：示例文件是不是「章节数组」。
 * 只用于缩略图渲染前的把关（渲染时直接读 rows/contents，结构不对会白屏）；
 * 真正的导入仍走 store.importResume()，由它做完整规范化。
 */
export function toSections(data: unknown): Section[] | null {
  if (!Array.isArray(data) || data.length === 0) return null
  const ok = data.every(
    (s) => s !== null && typeof s === 'object' && Array.isArray((s as Section).rows),
  )
  return ok ? (data as Section[]) : null
}
