/**
 * 简历差异比对（纯函数，与视图无关）
 *
 * 用途：AI 改完简历后，前端不直接覆盖，而是拿"改之前"和"改之后"两份简历比对，
 * 把改动的位置标出来，交给 ResumeDiffDialog 做左右对比展示。
 *
 * 为什么能按 id 对齐：后端 smartcv-api/agents/optimize/graph.py 对入参简历只做
 * 一层浅拷贝（OptimizeStore([dict(s) for s in resume_sections])），patch_content
 * 就地改文字、不动结构，所以返回的 JSON 里 id 与前端发出去的完全一致。
 * 也正因为如此，比对时必须用「后端返回的原始 JSON」——
 * 一旦走 stores/resume.ts 的 normalizeResumeData（会重生成全部 uid），
 * 两边 id 就对不上，整份简历会被误判成"全变了"。
 *
 * 标记语义（三种都按"只标改动的那一层"记，子树不重复标注）：
 *   added   —— 只在改后简历里存在（新增）
 *   removed —— 只在改前简历里存在（删除）
 *   changed —— 两边都在，但内容/样式不同（修改）
 */
import type { Content, ContentData, LayoutWindow, Section } from '@/types'

/** 一处标记的类型；查不到标记 = 该节点未改动 */
export type DiffMark = 'added' | 'removed' | 'changed'

/**
 * 给预览组件用的标记表：节点 id → 标记。
 * 三层分开存，组件各取所需（章节标标题、窗口标整块、内容标内容块）。
 */
export interface DiffMarks {
  sections: Record<string, DiffMark>
  rows: Record<string, DiffMark>
  contents: Record<string, DiffMark>
}

/** 比对结果：左右两栏各用一份标记表 */
export interface ResumeDiff {
  /** 左栏（原始简历）要显示的标记：removed + changed */
  before: DiffMarks
  /** 右栏（修改后简历）要显示的标记：added + changed */
  after: DiffMarks
  /**
   * 有差异的【内容】块数量（新增 + 删除 + 修改；只改章节标题这类空章节不计入），
   * 用于标题栏「共 N 处修改」。首版只统计内容，因为要不要在一个空标题上标"改了"
   * 对用户没什么信息量。
   */
  changedCount: number
}

/** 建一个空标记表 */
function emptyMarks(): DiffMarks {
  return { sections: {}, rows: {}, contents: {} }
}

/**
 * 按 id 把数组转成索引表。
 * 只用于同一层级内查找"对面有没有这个 id 的节点"，与顺序无关。
 */
function byId<T extends { id: string }>(list: T[]): Map<string, T> {
  const map = new Map<string, T>()
  for (const item of list) {
    if (item && typeof item.id === 'string') map.set(item.id, item)
  }
  return map
}

/** 两侧 id 的并集（先左后右，顺序只影响遍历次序，不影响结果） */
function unionIds<T extends { id: string }>(a: T[], b: T[]): string[] {
  const ids: string[] = []
  const seen = new Set<string>()
  for (const item of [...a, ...b]) {
    if (item && typeof item.id === 'string' && !seen.has(item.id)) {
      seen.add(item.id)
      ids.push(item.id)
    }
  }
  return ids
}

/** 逐项比字符串数组（columns / tags） */
function sameStringArray(a?: string[], b?: string[]): boolean {
  const x = a ?? []
  const y = b ?? []
  if (x.length !== y.length) return false
  return x.every((v, i) => v === y[i])
}

/**
 * 内容的深比较。
 * 不用 JSON.stringify：后端 patch 之后 key 的书写顺序可能与前端不同，
 * stringify 出来的字符串就会不相等，把没改的内容误判成"改了"。
 */
function sameContentData(a?: ContentData, b?: ContentData): boolean {
  const x = a ?? {}
  const y = b ?? {}
  if (
    (x.icon ?? '') !== (y.icon ?? '') ||
    (x.text ?? '') !== (y.text ?? '') ||
    (x.separator ?? '') !== (y.separator ?? '') ||
    (x.start ?? '') !== (y.start ?? '') ||
    (x.end ?? '') !== (y.end ?? '') ||
    (x.listType ?? '') !== (y.listType ?? '') ||
    (x.image ?? '') !== (y.image ?? '') ||
    (x.imageSize ?? 0) !== (y.imageSize ?? 0) ||
    (x.imageShape ?? '') !== (y.imageShape ?? '') ||
    (x.imageAlign ?? '') !== (y.imageAlign ?? '')
  ) {
    return false
  }
  if (!sameStringArray(x.columns, y.columns)) return false
  if (!sameStringArray(x.tags, y.tags)) return false

  // 列表项：text + indent（indent 缺省当 0，避免 undefined 与 0 被当成不同）
  const xi = x.items ?? []
  const yi = y.items ?? []
  if (xi.length !== yi.length) return false
  return xi.every((item, i) => (item?.text ?? '') === (yi[i]?.text ?? '') && (item?.indent ?? 0) === (yi[i]?.indent ?? 0))
}

/** 样式对象的浅比较（BaseStyle / ContentStyle 都是平铺的原始值字段） */
function sameStyle(a?: Record<string, unknown>, b?: Record<string, unknown>): boolean {
  const x = a ?? {}
  const y = b ?? {}
  const keys = new Set([...Object.keys(x), ...Object.keys(y)])
  for (const k of keys) {
    if ((x[k] ?? null) !== (y[k] ?? null)) return false
  }
  return true
}

/** tight 字段缺省 = false，统一成布尔再比 */
const isTight = (node: { tight?: boolean }) => node.tight === true

/** 内容是否没变：类型、内容数据、样式、紧贴任一不同都算变 */
function sameContent(a: Content, b: Content): boolean {
  return (
    a.type === b.type &&
    sameContentData(a.content, b.content) &&
    sameStyle(a.style as Record<string, unknown>, b.style as Record<string, unknown>) &&
    isTight(a) === isTight(b)
  )
}

/**
 * 给"整棵子树"打标记（节点是新增/删除时用）。
 *
 * 只标这一层、**不下钻**：窗口的底色会把整个窗口（含里面的内容、子窗口）都罩住，
 * 再往下逐层标只会叠出深浅不一的色块，反而看不清边界。
 */
function markSubtree(row: LayoutWindow, marks: DiffMarks, mark: DiffMark): void {
  marks.rows[row.id] = mark
}

/** 统计某棵子树里的内容数（新增/删除的"处数"按内容个数算） */
function countContents(row: LayoutWindow): number {
  let n = (row.contents ?? []).length
  for (const child of row.rows ?? []) n += countContents(child)
  return n
}

/** 比一行窗口的内容列表 */
function diffContents(oldRow: LayoutWindow, newRow: LayoutWindow, diff: ResumeDiff): void {
  const before = byId(oldRow.contents ?? [])
  const after = byId(newRow.contents ?? [])
  for (const id of unionIds(oldRow.contents ?? [], newRow.contents ?? [])) {
    const a = before.get(id)
    const b = after.get(id)
    if (a && !b) {
      diff.before.contents[id] = 'removed'
      diff.changedCount += 1
    } else if (!a && b) {
      diff.after.contents[id] = 'added'
      diff.changedCount += 1
    } else if (a && b && !sameContent(a, b)) {
      diff.before.contents[id] = 'changed'
      diff.after.contents[id] = 'changed'
      diff.changedCount += 1
    }
  }
}

/** 比一个窗口：先比自身字段，再按叶子/容器分别下钻 */
function diffRow(oldRow: LayoutWindow, newRow: LayoutWindow, diff: ResumeDiff): void {
  const selfChanged = oldRow.layout !== newRow.layout || isTight(oldRow) !== isTight(newRow)
  if (selfChanged) {
    diff.before.rows[oldRow.id] = 'changed'
    diff.after.rows[newRow.id] = 'changed'
  }

  const oldChildren = oldRow.rows ?? []
  const newChildren = newRow.rows ?? []
  const oldIsContainer = Array.isArray(oldRow.rows)
  const newIsContainer = Array.isArray(newRow.rows)

  // 容器 ↔ 叶子互换：结构变了，两边各标一层，不再下钻（底下已经没有对应关系）
  if (oldIsContainer !== newIsContainer) {
    diff.before.rows[oldRow.id] = 'changed'
    diff.after.rows[newRow.id] = 'changed'
    return
  }

  if (oldIsContainer) {
    const before = byId(oldChildren)
    const after = byId(newChildren)
    for (const id of unionIds(oldChildren, newChildren)) {
      const a = before.get(id)
      const b = after.get(id)
      if (a && !b) markSubtree(a, diff.before, 'removed')
      else if (!a && b) markSubtree(b, diff.after, 'added')
      else if (a && b) diffRow(a, b, diff)
    }
    return
  }

  diffContents(oldRow, newRow, diff)
}

/** 比一个章节：先比自身字段，再比窗口 */
function diffSection(oldSection: Section, newSection: Section, diff: ResumeDiff): void {
  const selfChanged =
    (oldSection.title ?? '') !== (newSection.title ?? '') ||
    (oldSection.icon ?? '') !== (newSection.icon ?? '') ||
    (oldSection.pageBreakBefore === true) !== (newSection.pageBreakBefore === true) ||
    !sameStyle(
      oldSection.style as Record<string, unknown>,
      newSection.style as Record<string, unknown>,
    )
  if (selfChanged) {
    diff.before.sections[oldSection.id] = 'changed'
    diff.after.sections[newSection.id] = 'changed'
  }

  const before = byId(oldSection.rows ?? [])
  const after = byId(newSection.rows ?? [])
  for (const id of unionIds(oldSection.rows ?? [], newSection.rows ?? [])) {
    const a = before.get(id)
    const b = after.get(id)
    if (a && !b) markSubtree(a, diff.before, 'removed')
    else if (!a && b) markSubtree(b, diff.after, 'added')
    else if (a && b) diffRow(a, b, diff)
  }
}

/**
 * 比对两份简历，返回左右两栏各自的标记表。
 * 章节按 id 对齐（顺序变化不影响结果）；新增/删除的章节整棵标一层。
 */
export function diffResume(before: Section[], after: Section[]): ResumeDiff {
  const diff: ResumeDiff = { before: emptyMarks(), after: emptyMarks(), changedCount: 0 }

  const oldSections = byId(before ?? [])
  const newSections = byId(after ?? [])

  for (const id of unionIds(before ?? [], after ?? [])) {
    const a = oldSections.get(id)
    const b = newSections.get(id)
    if (a && !b) {
      // 整个章节被删掉：章节标一层，内部的窗口/内容也标上（左栏要整块泛红才看得见）
      diff.before.sections[id] = 'removed'
      for (const row of a.rows ?? []) {
        markSubtree(row, diff.before, 'removed')
        diff.changedCount += countContents(row)
      }
    } else if (!a && b) {
      diff.after.sections[id] = 'added'
      for (const row of b.rows ?? []) {
        markSubtree(row, diff.after, 'added')
        diff.changedCount += countContents(row)
      }
    } else if (a && b) {
      diffSection(a, b, diff)
    }
  }

  return diff
}
