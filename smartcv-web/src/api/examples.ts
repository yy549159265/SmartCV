/**
 * 示例模板接口 —— 数据源是 GitHub 仓库的 example/ 目录。
 *
 * 为什么放 GitHub 而不是打包进前端：
 *   1. 新增示例只要往仓库 example/ 丢一个 json、在 index.json 里登记一行，
 *      前端不用改代码、也不用重新构建；
 *   2. 目录清单由仓库里的 example/index.json 给出，画廊照单渲染 —— 加多少张卡片都自动排版。
 *
 * 为什么用 index.json 而不是 GitHub API 列目录：
 *   api.github.com 未认证只有 60 次/小时/IP，多开标签页、换设备，或者同一出口 IP
 *   的其它工具都会一起消耗它。改成读仓库里的静态清单后，清单和文件都走
 *   raw.githubusercontent.com（CDN 直出），不消耗 API 配额，也不需要 token。
 *
 * 维护：新增/删除示例后，在 smartcv-web 下运行 `npm run examples:index`
 *   重新生成 index.json（见 scripts/gen-example-index.mjs）。
 *
 * 命名约定：`01-经典左头图.json` → 序号 1、标题「经典左头图」。
 *   不按这个约定命名也能用，只是排到最后、标题直接取文件名。
 */
import type { Section } from '@/types'

/** 示例所在仓库 / 分支 / 目录 */
const REPO = 'yy549159265/SmartCV'
const BRANCH = 'main'
const DIR = 'example'

/** raw CDN 根地址：清单和示例文件都从这里取，不消耗 GitHub API 配额 */
const RAW_BASE = `https://raw.githubusercontent.com/${REPO}/${BRANCH}/${DIR}`

/** 清单地址（仓库里的 example/index.json，由 scripts/gen-example-index.mjs 生成） */
const LIST_URL = `${RAW_BASE}/index.json`

/** 清单缓存的 sessionStorage key 与有效期（1 小时） */
const CACHE_KEY = 'smartcv-example-list'
const CACHE_TTL = 60 * 60 * 1000

/** index.json 里的单个条目：name 必填，title/size 省略时由文件名推导或显示为 0 */
interface IndexEntry {
  name: string
  title?: string
  size?: number
}

/** 画廊里的一张示例卡片 */
export interface ExampleItem {
  /** 仓库里的文件名，如 01-经典左头图.json */
  name: string
  /** 展示用标题（清单里的 title，没有则从文件名解析） */
  title: string
  /** 排序号（文件名前缀数字；没写前缀的排到最后） */
  order: number
  /** 文件大小（字节；清单里没写就是 0） */
  size: number
  /** 下载地址（raw CDN，由文件名编码拼接） */
  url: string
}

/** 把文件名解析成「序号 + 标题」：`01-经典左头图.json` → 1 / 经典左头图 */
function parseName(name: string): { order: number; title: string } {
  const stem = name.replace(/\.json$/i, '')
  const matched = /^(\d+)\s*[-_.、\s]\s*(.+)$/.exec(stem)
  if (matched) return { order: Number(matched[1]), title: matched[2].trim() }
  // 没按 `<序号>-<标题>` 命名的：排到最后，标题就用去掉扩展名的文件名
  return { order: Number.MAX_SAFE_INTEGER, title: stem }
}

/** 读清单缓存；过期/损坏都当作没有 */
function readCache(): ExampleItem[] | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { at: number; items: ExampleItem[] }
    if (!Array.isArray(parsed.items)) return null
    if (Date.now() - parsed.at > CACHE_TTL) return null
    return parsed.items
  } catch {
    return null
  }
}

/** 写清单缓存（无痕模式等写不进去的情况忽略，不影响功能） */
function writeCache(items: ExampleItem[]): void {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), items }))
  } catch {
    /* 忽略 */
  }
}

/**
 * 列出仓库 example/ 下的所有示例（按序号排序）。
 * force = true 时跳过缓存强制重新拉取（给「重试」按钮用）。
 */
export async function listExamples(force = false): Promise<ExampleItem[]> {
  if (!force) {
    const cached = readCache()
    if (cached) return cached
  }

  let res: Response
  try {
    // force 时绕过浏览器 HTTP 缓存，否则刚推上去的示例目录可能还是旧的
    res = await fetch(LIST_URL, { cache: force ? 'reload' : 'default' })
  } catch {
    throw new Error('连接 GitHub 失败，请检查网络后重试')
  }

  if (!res.ok) {
    // 404 = 仓库里没有 index.json（或分支/目录改名了）
    if (res.status === 404) throw new Error('仓库里找不到 example/index.json')
    throw new Error(`读取示例清单失败（HTTP ${res.status}）`)
  }

  const entries = (await res.json()) as IndexEntry[]
  if (!Array.isArray(entries)) throw new Error('示例清单格式不正确')

  const items = entries
    .filter((e) => e !== null && typeof e === 'object' && typeof e.name === 'string' && /\.json$/i.test(e.name))
    .map((e) => {
      const parsed = parseName(e.name)
      return {
        name: e.name,
        // 清单里显式写了 title 就用它，否则按文件名约定推导
        title: e.title || parsed.title,
        size: typeof e.size === 'number' ? e.size : 0,
        // 下载地址由清单里的文件名拼出来，和清单一样走 raw CDN
        url: `${RAW_BASE}/${encodeURIComponent(e.name)}`,
        order: parsed.order,
      }
    })
    .sort((a, b) => a.order - b.order || a.name.localeCompare(b.name))

  writeCache(items)
  return items
}

/** 已拉取过的示例内容（key = 文件名）—— 点「使用」时不用再请求一次 */
const contentCache = new Map<string, unknown>()

/**
 * 冷启动计数：点「刷新」后自增，给下载地址挂个变化的查询参数，
 * 强制绕过 raw.githubusercontent.com 的浏览器 HTTP 缓存（它只给几分钟有效期，
 * 刚改完示例时缩略图会一直是旧的）。
 */
let contentVersion = 0

/** 作废已下载的示例内容 —— 刷新时必须调，否则缩略图还是旧 JSON */
export function clearExampleCache(): void {
  contentCache.clear()
  contentVersion += 1
}

/** 下载并解析一份示例文件，返回原始 JSON（结构校验交给 toSections / store） */
export async function loadExample(item: ExampleItem): Promise<unknown> {
  const hit = contentCache.get(item.name)
  if (hit !== undefined) return hit

  const url = contentVersion > 0 ? `${item.url}?v=${contentVersion}` : item.url

  let res: Response
  try {
    res = await fetch(url, { cache: 'no-store' })
  } catch {
    throw new Error('下载失败，请检查网络')
  }
  if (!res.ok) throw new Error(`下载失败（HTTP ${res.status}）`)

  const data: unknown = await res.json()
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
