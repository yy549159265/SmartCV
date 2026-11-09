/**
 * 分页计算（纯函数）。
 *
 * 把简历拍平成「可裁切单元」的有序列表（章节标题 或 一个顶层行），逐行分页：
 * 普通章节结果与章节级分页一致，长章节可跨页并填满上一页剩余空隙，页数不虚高。
 * 预览与导出共用同一份 PagePlan，页数才对得上。
 */

export const SECTION_TOP_PAD = 2
export const SECTION_BOTTOM_PAD = 10

export interface PageUnit {
  id: string
  sectionId: string
  kind: 'title' | 'row'
  rowIndex: number
  offsetTop: number
  height: number
  spaceBefore: number
  sectionRowCount: number
  forced: boolean
}

export interface RunSpec {
  sectionId: string
  rowFrom: number
  rowTo: number
  hasTitle: boolean
  topPad: boolean
  bottomPad: boolean
  spaceBefore: number
}

export interface PagePlan {
  pages: { unitIds: string[]; forced: boolean }[]
  pageStartOffsets: number[]
  totalHeight: number
}

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

    const sectionEndsHere =
      rows.length > 0
        ? lastRow === u.sectionRowCount - 1
        : u.sectionRowCount === 0
    const hasNextRunHere = j + 1 < units.length

    runs.push({
      sectionId: u.sectionId,
      rowFrom: firstRow < 0 ? 0 : firstRow,
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
    const used = current.length === 0 ? g.height : g.offsetTop - startTop + g.height

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

  for (let i = 1; i < pages.length; i++) {
    const firstId = pages[i].unitIds[0]
    const firstUnit = firstId ? sorted.find((x) => x.id === firstId) : undefined
    pages[i].forced = firstUnit ? firstUnit.forced : false
  }

  return { pages, pageStartOffsets, totalHeight }
}
