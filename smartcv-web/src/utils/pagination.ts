/**
 * 分页计算（纯函数，与视图无关）
 *
 * 一页能放多高、哪些内容放同一页 —— 全部在这里决定。
 *
 * 关键：把整份简历拍平成一张"可裁切单元(unit)"的有序列表。一个单元 = 标题 或 一个顶层行：
 *
 *    章节 A   → [A:title, A:row0, A:row1, ...]
 *    章节 B   → [B:title, B:row0, ...]
 *
 * 这样分页是"逐行"排的，而不是"逐章节"排：
 *  - 普通简历：一个章节 ≤ 一页，结果和旧的"章节级分页"别无二致；
 *  - 长章节（超过一页的超大工作经历）：会被自然地跨页拆开，而且【还能紧贴着上一页剩下的空隙】，
 *    不会为了塞下一个大章节而白白空出上一页 —— 页数才真实、不虚高。
 *
 * 前端"实时预览"、"导出 PDF"用的是同一份分页方案 + 同一份单元数据：
 *  - 预览：每个 A4 纸块 = 一页单元；
 *  - 导出：每页一个块 + break-after:page，页数 = 预览页数。
 * 每页内容都被严格控制在 ≤ 一页可用高度（CONTENT_HEIGHT），
 * 无头 Chromium 打 PDF 时绝不会再把它硬拆成两页 → 导出的页数真正和预览一致。
 */

/** 一页的可用内容高度 = 纸高 - 上下留白（与 constants.CONTENT_HEIGHT 一致） */
export const CONTENT_HEIGHT = 1123 - 48 * 2

/** 与 PreviewSection.vue 的 padding 保持一致（顶部 4px，底部 16px） */
export const SECTION_TOP_PAD = 4
export const SECTION_BOTTOM_PAD = 16

/**
 * 一个"可裁切单元"：某个章节的标题，或它的某个顶层行。
 * 它既用于分页计算（offsetTop / height），也用于渲染（rowIndex / 标题 / 留白判断）。
 */
export interface PageUnit {
  /** 单元唯一 id（`sectionId:title` 或 `sectionId:row:N`） */
  id: string
  /** 所属章节 id */
  sectionId: string
  kind: 'title' | 'row'
  /** 标题为 -1；行 = 在 section.rows 中的下标 */
  rowIndex: number
  /** 本单元顶边相对"连续流"原点的偏移 */
  offsetTop: number
  /** 本单元自身高度（不含与前/后单元之间的间隙；间隙由 offsetTop 差值在换页判定时自动算入） */
  height: number
  /** 本单元前面的间距（标题单元 = 章节 spaceBefore；行单元 = 0） */
  spaceBefore: number
  /** 所属章节的顶层行总数（渲染时判断某页是否是章节末页） */
  sectionRowCount: number
  /** 是否由强制分页开启（pageBreakBefore；只标在章节标题单元上） */
  forced: boolean
}

/** 一页的渲染指令：如何渲染一个"连续同章节单元的片段" */
export interface RunSpec {
  sectionId: string
  rowFrom: number
  rowTo: number
  hasTitle: boolean
  topPad: boolean
  bottomPad: boolean
  spaceBefore: number
}

/** 完整分页方案 */
export interface PagePlan {
  /** 每页的单元 id 列表（按顺序） */
  pages: { unitIds: string[]; forced: boolean }[]
  /** 第 2、3… 页的起始偏移（第 1 页恒为 0，不记录） */
  pageStartOffsets: number[]
  /** 全部内容的总高度 */
  totalHeight: number
}

/**
 * 把一页的单元列表切成若干"连续同章节片段"（RunSpec），用于渲染。
 * - 第一个片段（页面开头）强制 spaceBefore = 0，避免页首多出章节间距；
 * - 一个章节在本页结束、且后面紧跟另一个章节时，才渲染它的底部留白，
 *   否则直接以换页代替（页与页之间不必再留一段空白）。
 */
export function pageRunSpecs(units: PageUnit[]): RunSpec[] {
  const runs: RunSpec[] = []
  let i = 0
  while (i < units.length) {
    const u = units[i]
    let j = i
    while (j + 1 < units.length && units[j + 1].sectionId === u.sectionId) j += 1
    const inRun = units.slice(i, j + 1)

    const rows = inRun.filter((x) => x.kind === 'row')
    const hasTitle = inRun.some((x) => x.kind === 'title')
    const firstRow = rows.length > 0 ? Math.min(...rows.map((x) => x.rowIndex)) : -1
    const lastRow = rows.length > 0 ? Math.max(...rows.map((x) => x.rowIndex)) : -1

    // 章节在本页是否"结束"（本页有它的最后一行，或它本就是空章节只有标题）。
    // 注意：标题单独落到页底（行全在下一页）时，章节并没有在本页结束。
    const sectionEndsHere =
      rows.length > 0
        ? lastRow === u.sectionRowCount - 1
        : u.sectionRowCount === 0
    const hasNextRunHere = j + 1 < units.length // 本页后面还有别的章节片段

    runs.push({
      sectionId: u.sectionId,
      rowFrom: firstRow < 0 ? 0 : firstRow,
      // 无行片段（标题单独在页底）rowTo 必须 < rowFrom → 切出空行集，绝不能渲染整行
      rowTo: lastRow < 0 ? -1 : lastRow,
      hasTitle,
      topPad: hasTitle,
      bottomPad: sectionEndsHere && hasNextRunHere,
      spaceBefore: hasTitle ? (i === 0 ? 0 : u.spaceBefore) : 0,
    })
    i = j + 1
  }
  return runs
}

/**
 * 分页：对拍平后的单元列表做"贪心装页"。
 * 采用 offsetTop 差值算页面真实占用（把单元之间的 spaceBefore 间隙也带进去），
 * 不满足"装得下"或"被强制分页"时换页。第一单元永不换页（避免开头空页）。
 */
export function computePages(
  metrics: PageUnit[],
  contentHeight: number,
): PagePlan {
  const sorted = [...metrics].sort((a, b) => a.offsetTop - b.offsetTop)

  const pages: { unitIds: string[]; forced: boolean }[] = []
  const pageStartOffsets: number[] = []

  let current: PageUnit[] = []
  let startTop = 0
  let totalHeight = 0

  for (const g of sorted) {
    // 页面真实占用高度：本页第一单元顶边 → 当前单元底边（含中间所有间隙）
    const used = current.length === 0 ? g.height : g.offsetTop - startTop + g.height

    // 两种需要换页的情况：放不下（自动分页）/ 被标记强制分页
    const needBreak = current.length > 0 && (used > contentHeight || g.forced)

    if (needBreak) {
      pages.push({ unitIds: current.map((x) => x.id), forced: false })
      pageStartOffsets.push(g.offsetTop)
      current = []
    }

    if (current.length === 0) startTop = g.offsetTop
    current.push(g)
    totalHeight = Math.max(totalHeight, g.offsetTop + g.height)
  }

  if (current.length > 0) {
    pages.push({ unitIds: current.map((x) => x.id), forced: false })
  }

  // 补"本页是否强制分页"标记：看每页第一个单元（第 1 页永远在最开头，不标）
  for (let i = 1; i < pages.length; i++) {
    const firstId = pages[i].unitIds[0]
    const firstUnit = firstId ? sorted.find((x) => x.id === firstId) : undefined
    pages[i].forced = firstUnit ? firstUnit.forced : false
  }

  return { pages, pageStartOffsets, totalHeight }
}
