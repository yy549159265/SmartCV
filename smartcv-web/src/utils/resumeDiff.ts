/**
 * 简历差异比对 + 逐处合并（纯函数，与视图无关）
 *
 * 用途：AI 改完简历后，前端不直接覆盖，而是拿"改之前"和"改之后"两份简历比对，
 * 把改动的位置标出来，交给 ResumeDiffDialog 做左右对比展示。
 * 用户可以在对比弹窗里逐处「还原 / 恢复」，最后点确定才写回简历。
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
 *
 * 两份数据都当作只读：mergeResume 只生成新对象，不会改动入参。
 */
import type { Content, ContentData, LayoutWindow, Section } from '@/types'

/** 一处标记的类型；查不到标记 = 该节点未改动 */
export type DiffMark = 'added' | 'removed' | 'changed'

/** 改动所在层级：章节 / 布局窗口 / 内容 */
export type ChangeLevel = 'section' | 'row' | 'content'

/**
 * 给预览组件用的标记表：节点 id → 标记。
 * 三层分开存，组件各取所需（章节标标题、窗口标整块、内容标内容块）。
 */
export interface DiffMarks {
  sections: Record<string, DiffMark>
  rows: Record<string, DiffMark>
  contents: Record<string, DiffMark>
}

/**
 * 一处可独立切换的改动。
 *
 * key 同时用于「已还原集合」和「操作按钮定位」：
 *   `section:<id>` / `row:<id>` / `content:<id>`
 * 同一节点在不同层级各算一处（例如窗口排版改了、里面的文字也改了）。
 */
export interface DiffChange {
  key: string
  level: ChangeLevel
  kind: DiffMark
  /** 所属章节 id（行 / 内容级改动用；章节级改动就是它自己） */
  sectionId: string
  /** 改动的节点 id（章节 / 窗口 / 内容） */
  nodeId: string
  /** 改动前的文字摘要（内容级才有，给按钮气泡看） */
  beforeText: string
  /** 改动后的文字摘要 */
  afterText: string
}

/** 比对结果：左右两栏各用一份标记表 + 本次全部可切换改动 */
export interface ResumeDiff {
  /** 左栏（原始简历）要显示的标记：removed + changed */
  before: DiffMarks
  /** 右栏（修改后简历）要显示的标记：added + changed */
  after: DiffMarks
  /** 可独立切换的改动处数（= changes.length） */
  changedCount: number
  /** 按遍历顺序排列的全部改动（逐处还原/恢复用） */
  changes: DiffChange[]
}

/**
 * 一处改动的渲染态：挂在预览组件上，决定高亮样式和按钮方向。
 * 只给"能操作的那一栏"：
 *   - changed / added → 右栏（结果侧）
 *   - removed         → 左栏（原始侧，内容只在那里）
 */
export interface ChangeView {
  kind: DiffMark
  /** true = 用户已把这处还原成修改前 */
  reverted: boolean
  /** 点击切换：接受 ↔ 还原 */
  toggle: () => void
}

/** 三层各自的改动操作表 */
export interface DiffControls {
  sections: Record<string, ChangeView>
  rows: Record<string, ChangeView>
  contents: Record<string, ChangeView>
}

/** 建一个空标记表 */
function emptyMarks(): DiffMarks {
  return { sections: {}, rows: {}, contents: {} }
}

/** 建一个空操作表 */
function emptyControls(): DiffControls {
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

/* ============================================================
 * 一、比对：产出标记表 + 逐处改动清单
 * ============================================================ */

/** 内容转一行摘要（给按钮提示 / 改动计数用；不参与渲染） */
function contentSummary(content?: Content): string {
  if (!content) return ''
  const d = content.content ?? {}
  const parts: string[] = []
  if (d.text) parts.push(d.text)
  if (d.columns?.length) parts.push(d.columns.join(' | '))
  if (d.start || d.end) parts.push(`${d.start ?? ''} - ${d.end ?? ''}`)
  if (d.tags?.length) parts.push(d.tags.join('、'))
  if (d.items?.length) {
    parts.push(
      d.items
        .map((item) => (typeof item === 'string' ? item : item?.text ?? ''))
        .filter(Boolean)
        .join(' / '),
    )
  }
  if (content.type === 'image') parts.push('图片')
  const text = parts.filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()
  return text.length > 60 ? `${text.slice(0, 60)}…` : text
}

/** 记一处改动；key 由层级 + 节点 id 组成，全简历唯一 */
function addChange(
  diff: ResumeDiff,
  level: ChangeLevel,
  kind: DiffMark,
  nodeId: string,
  sectionId: string,
  beforeText = '',
  afterText = '',
): void {
  diff.changes.push({
    key: `${level}:${nodeId}`,
    level,
    kind,
    sectionId,
    nodeId,
    beforeText,
    afterText,
  })
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

/** 比一行窗口的内容列表 */
function diffContents(
  oldRow: LayoutWindow,
  newRow: LayoutWindow,
  sectionId: string,
  diff: ResumeDiff,
): void {
  const before = byId(oldRow.contents ?? [])
  const after = byId(newRow.contents ?? [])
  for (const id of unionIds(oldRow.contents ?? [], newRow.contents ?? [])) {
    const a = before.get(id)
    const b = after.get(id)
    if (a && !b) {
      diff.before.contents[id] = 'removed'
      addChange(diff, 'content', 'removed', id, sectionId, contentSummary(a))
    } else if (!a && b) {
      diff.after.contents[id] = 'added'
      addChange(diff, 'content', 'added', id, sectionId, '', contentSummary(b))
    } else if (a && b && !sameContent(a, b)) {
      diff.before.contents[id] = 'changed'
      diff.after.contents[id] = 'changed'
      addChange(diff, 'content', 'changed', id, sectionId, contentSummary(a), contentSummary(b))
    }
  }
}

/** 比一个窗口：先比自身字段，再按叶子/容器分别下钻 */
function diffRow(
  oldRow: LayoutWindow,
  newRow: LayoutWindow,
  sectionId: string,
  diff: ResumeDiff,
): void {
  const selfChanged = oldRow.layout !== newRow.layout || isTight(oldRow) !== isTight(newRow)
  if (selfChanged) {
    diff.before.rows[oldRow.id] = 'changed'
    diff.after.rows[newRow.id] = 'changed'
    addChange(diff, 'row', 'changed', oldRow.id, sectionId)
  }

  const oldChildren = oldRow.rows ?? []
  const newChildren = newRow.rows ?? []
  const oldIsContainer = Array.isArray(oldRow.rows)
  const newIsContainer = Array.isArray(newRow.rows)

  // 容器 ↔ 叶子互换：结构变了，两边各标一层，不再下钻（底下已经没有对应关系）。
  // 排版也变了的话上面已经记过一处，这里不再重复记（key 相同，重复会出现两个按钮）。
  if (oldIsContainer !== newIsContainer) {
    diff.before.rows[oldRow.id] = 'changed'
    diff.after.rows[newRow.id] = 'changed'
    if (!selfChanged) addChange(diff, 'row', 'changed', oldRow.id, sectionId)
    return
  }

  if (oldIsContainer) {
    const before = byId(oldChildren)
    const after = byId(newChildren)
    for (const id of unionIds(oldChildren, newChildren)) {
      const a = before.get(id)
      const b = after.get(id)
      if (a && !b) {
        markSubtree(a, diff.before, 'removed')
        addChange(diff, 'row', 'removed', a.id, sectionId)
      } else if (!a && b) {
        markSubtree(b, diff.after, 'added')
        addChange(diff, 'row', 'added', b.id, sectionId)
      } else if (a && b) {
        diffRow(a, b, sectionId, diff)
      }
    }
    return
  }

  diffContents(oldRow, newRow, sectionId, diff)
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
    addChange(
      diff,
      'section',
      'changed',
      oldSection.id,
      oldSection.id,
      oldSection.title,
      newSection.title,
    )
  }

  const before = byId(oldSection.rows ?? [])
  const after = byId(newSection.rows ?? [])
  for (const id of unionIds(oldSection.rows ?? [], newSection.rows ?? [])) {
    const a = before.get(id)
    const b = after.get(id)
    if (a && !b) {
      markSubtree(a, diff.before, 'removed')
      addChange(diff, 'row', 'removed', a.id, oldSection.id)
    } else if (!a && b) {
      markSubtree(b, diff.after, 'added')
      addChange(diff, 'row', 'added', b.id, oldSection.id)
    } else if (a && b) {
      diffRow(a, b, oldSection.id, diff)
    }
  }
}

/**
 * 比对两份简历，返回左右两栏各自的标记表 + 可逐处切换的改动清单。
 * 章节按 id 对齐（顺序变化不影响结果）；新增/删除的章节整棵标一层。
 */
export function diffResume(before: Section[], after: Section[]): ResumeDiff {
  const diff: ResumeDiff = {
    before: emptyMarks(),
    after: emptyMarks(),
    changedCount: 0,
    changes: [],
  }

  const oldSections = byId(before ?? [])
  const newSections = byId(after ?? [])

  for (const id of unionIds(before ?? [], after ?? [])) {
    const a = oldSections.get(id)
    const b = newSections.get(id)
    if (a && !b) {
      // 整个章节被删掉：章节标一层，内部的窗口/内容也标上（左栏要整块泛红才看得见）
      diff.before.sections[id] = 'removed'
      for (const row of a.rows ?? []) markSubtree(row, diff.before, 'removed')
      addChange(diff, 'section', 'removed', a.id, a.id, a.title)
    } else if (!a && b) {
      diff.after.sections[id] = 'added'
      for (const row of b.rows ?? []) markSubtree(row, diff.after, 'added')
      addChange(diff, 'section', 'added', b.id, b.id, '', b.title)
    } else if (a && b) {
      diffSection(a, b, diff)
    }
  }

  // 改动处数 = 可独立切换的处数（章节增删按一处算，不按内部内容数累加）
  diff.changedCount = diff.changes.length
  return diff
}

/**
 * 预览组件用的一行标记：被用户还原的改动要换一种颜色。
 * 返回的 'restored' / 'ignored' 是 global.css 里额外定义的两档样式。
 *   restored —— 这处已还原成修改前（绿色）
 *   ignored  —— 这处新增被忽略（灰色 + 删除线，确认时不会写入）
 */
export type DiffAttr = DiffMark | 'restored' | 'ignored'

export function diffAttr(mark: DiffMark | undefined, view: ChangeView | undefined): DiffAttr | undefined {
  if (view?.reverted) return view.kind === 'added' ? 'ignored' : 'restored'
  return mark
}

/* ============================================================
 * 二、逐处合并：按"已还原集合"算出当前结果
 * ============================================================ */

/**
 * 合并结果。
 * sections 是给右栏渲染的（默认保留被还原的新增节点，让用户还能点 → 恢复）；
 * ignored 是这些"保留但已忽略"的节点 key，确认写回时剔除。
 */
export interface MergeResult {
  sections: Section[]
  ignored: Set<string>
}

/** 已还原集合（`section:id` / `row:id` / `content:id`） */
export type RevertedSet = ReadonlySet<string>

const isReverted = (reverted: RevertedSet, level: ChangeLevel, id: string) =>
  reverted.has(`${level}:${id}`)

/**
 * 按顺序合并两个同层数组。
 *
 * 以「改后」的顺序为骨架：
 *  - 两边都有的节点交给 mergeAfter 递归；
 *  - 只在改后的（新增）由 mergeAfter 决定保留还是丢弃；
 *  - 只在改前的（删除）只有被用户还原时才插回，插入位置按改前顺序
 *    （放在它后面的第一个"改前也存在的节点"之前）。
 */
function mergeList<T extends { id: string }>(
  beforeList: T[],
  afterList: T[],
  isRestored: (node: T) => boolean,
  mergeAfter: (node: T) => T | null,
): T[] {
  const beforeIndex = new Map(beforeList.map((node, i) => [node.id, i]))
  const restored = beforeList.filter(isRestored)
  let ri = 0
  const out: T[] = []

  for (const node of afterList) {
    const pos = beforeIndex.get(node.id) ?? Number.POSITIVE_INFINITY
    while (ri < restored.length && (beforeIndex.get(restored[ri].id) ?? 0) < pos) {
      out.push(restored[ri++])
    }
    const merged = mergeAfter(node)
    if (merged) out.push(merged)
  }
  while (ri < restored.length) out.push(restored[ri++])
  return out
}

/** 合并一个叶子窗口的内容列表 */
function mergeContents(
  beforeContents: Content[],
  afterContents: Content[],
  reverted: RevertedSet,
  ignored: Set<string>,
  keepIgnored: boolean,
): Content[] {
  const beforeMap = byId(beforeContents)
  const afterIds = new Set(afterContents.map((c) => c.id))

  return mergeList(
    beforeContents,
    afterContents,
    (c) => !afterIds.has(c.id) && isReverted(reverted, 'content', c.id),
    (b) => {
      const a = beforeMap.get(b.id)
      if (a) {
        // 两边都有：还原了就整块换回改前（type / content / style 一起换）
        return isReverted(reverted, 'content', b.id) ? a : b
      }
      // 新增内容：还原 = 不采用；预览时保留成"已忽略"占位，方便再点回来
      if (!isReverted(reverted, 'content', b.id)) return b
      if (!keepIgnored) return null
      ignored.add(`content:${b.id}`)
      return b
    },
  )
}

/** 合并一个布局窗口（递归） */
function mergeWindow(
  beforeRow: LayoutWindow,
  afterRow: LayoutWindow,
  reverted: RevertedSet,
  ignored: Set<string>,
  keepIgnored: boolean,
): LayoutWindow {
  const selfReverted = isReverted(reverted, 'row', afterRow.id)
  const beforeIsContainer = Array.isArray(beforeRow.rows)
  const afterIsContainer = Array.isArray(afterRow.rows)

  // 容器 ↔ 叶子互换：结构不同，没有可递归的共同层，整块按选中的一侧取
  if (beforeIsContainer !== afterIsContainer) return selfReverted ? beforeRow : afterRow

  const selfFields = selfReverted ? { layout: beforeRow.layout, tight: beforeRow.tight } : {}

  if (afterIsContainer) {
    return {
      ...afterRow,
      ...selfFields,
      rows: mergeWindows(
        beforeRow.rows ?? [],
        afterRow.rows ?? [],
        reverted,
        ignored,
        keepIgnored,
      ),
    }
  }
  return {
    ...afterRow,
    ...selfFields,
    contents: mergeContents(
      beforeRow.contents ?? [],
      afterRow.contents ?? [],
      reverted,
      ignored,
      keepIgnored,
    ),
  }
}

/** 合并一组布局窗口 */
function mergeWindows(
  beforeRows: LayoutWindow[],
  afterRows: LayoutWindow[],
  reverted: RevertedSet,
  ignored: Set<string>,
  keepIgnored: boolean,
): LayoutWindow[] {
  const beforeMap = byId(beforeRows)
  const afterIds = new Set(afterRows.map((r) => r.id))

  return mergeList(
    beforeRows,
    afterRows,
    (r) => !afterIds.has(r.id) && isReverted(reverted, 'row', r.id),
    (b) => {
      const a = beforeMap.get(b.id)
      if (a) return mergeWindow(a, b, reverted, ignored, keepIgnored)
      if (!isReverted(reverted, 'row', b.id)) return b
      if (!keepIgnored) return null
      ignored.add(`row:${b.id}`)
      return b
    },
  )
}

/** 合并一个章节（标题/样式 + 内部窗口） */
function mergeSection(
  beforeSection: Section,
  afterSection: Section,
  reverted: RevertedSet,
  ignored: Set<string>,
  keepIgnored: boolean,
): Section {
  const selfReverted = isReverted(reverted, 'section', afterSection.id)
  return {
    ...afterSection,
    ...(selfReverted
      ? {
          title: beforeSection.title,
          icon: beforeSection.icon,
          style: beforeSection.style,
          pageBreakBefore: beforeSection.pageBreakBefore,
        }
      : {}),
    rows: mergeWindows(
      beforeSection.rows ?? [],
      afterSection.rows ?? [],
      reverted,
      ignored,
      keepIgnored,
    ),
  }
}

/**
 * 按"已还原集合"合并出当前结果。
 *
 * @param reverted 用户已还原的改动 key 集合
 * @param options.keepIgnored 是否在结果里保留"被还原的新增"（预览用 true，
 *   这样按钮还在、能点回来；确认写回用 false，直接剔除）。
 */
export function mergeResume(
  before: Section[],
  after: Section[],
  reverted: RevertedSet,
  options: { keepIgnored?: boolean } = {},
): MergeResult {
  const keepIgnored = options.keepIgnored !== false
  const ignored = new Set<string>()
  const beforeMap = byId(before ?? [])
  const afterIds = new Set((after ?? []).map((s) => s.id))

  const sections = mergeList(
    before ?? [],
    after ?? [],
    (s) => !afterIds.has(s.id) && isReverted(reverted, 'section', s.id),
    (b) => {
      const a = beforeMap.get(b.id)
      if (a) return mergeSection(a, b, reverted, ignored, keepIgnored)
      if (!isReverted(reverted, 'section', b.id)) return b
      if (!keepIgnored) return null
      ignored.add(`section:${b.id}`)
      return b
    },
  )

  return { sections, ignored }
}

/* ============================================================
 * 三、给对比弹窗拼操作表
 * ============================================================ */

/** 改动层级 → DiffMarks / DiffControls 的键（单数 → 复数） */
const BUCKET: Record<ChangeLevel, keyof DiffMarks> = {
  section: 'sections',
  row: 'rows',
  content: 'contents',
}

/** 某一侧的改动操作表（哪一侧能操作见函数内注释） */
export function buildControls(
  diff: ResumeDiff,
  side: 'before' | 'after',
  reverted: RevertedSet,
  toggle: (key: string) => void,
): DiffControls {
  const controls = emptyControls()
  for (const change of diff.changes) {
    // 改 / 增：节点只在右栏（结果侧），按钮放右栏。
    // 删：节点在左栏（原始侧）；被还原后也会插进右栏，所以两栏都挂 ——
    //    右栏那个按钮只在"已还原"时才会真的渲染出来。
    const onThisSide = change.kind === 'removed' || side === 'after'
    if (!onThisSide) continue
    controls[BUCKET[change.level]][change.nodeId] = {
      kind: change.kind,
      reverted: reverted.has(change.key),
      toggle: () => toggle(change.key),
    }
  }
  return controls
}
