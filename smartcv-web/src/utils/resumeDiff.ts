/**
 * 简历差异比对 + 逐处合并（纯函数）。
 *
 * 按 id 对齐：后端只浅拷贝并就地改文字，id 不变；因此比对必须用后端返回的原始 JSON，
 * 一旦走 normalizeResumeData（会重生成 uid），整份简历会被误判成「全变了」。
 * 文字单元（units）与后端坐标的 i 对应，只标变动的行/栏，不把整个内容块罩住。
 */

import type { Content, ContentData, ContentType, LayoutWindow, ListItem, Section } from '@/types'

export type DiffMark = 'added' | 'removed' | 'changed'

export type ChangeLevel = 'section' | 'row' | 'content' | 'unit'

export interface DiffMarks {
  sections: Record<string, DiffMark>
  rows: Record<string, DiffMark>
  contents: Record<string, DiffMark>
  units: Record<string, Record<number, DiffMark>>
}

export interface DiffChange {
  key: string
  level: ChangeLevel
  kind: DiffMark
  sectionId: string
  nodeId: string
  unitIndex?: number
  beforeText: string
  afterText: string
}

export interface ResumeDiff {
  before: DiffMarks
  after: DiffMarks
  changedCount: number
  changes: DiffChange[]
}

export interface ChangeView {
  kind: DiffMark
  reverted: boolean
  toggle: () => void
  diagIndex?: number
  jumpToDiagnosis?: () => void
}

export interface DiffControls {
  sections: Record<string, ChangeView>
  rows: Record<string, ChangeView>
  contents: Record<string, ChangeView>
  units: Record<string, Record<number, ChangeView>>
}

function emptyMarks(): DiffMarks {
  return { sections: {}, rows: {}, contents: {}, units: {} }
}

function emptyControls(): DiffControls {
  return { sections: {}, rows: {}, contents: {}, units: {} }
}

function byId<T extends { id: string }>(list: T[]): Map<string, T> {
  const map = new Map<string, T>()
  for (const item of list) {
    if (item && typeof item.id === 'string') map.set(item.id, item)
  }
  return map
}

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

function sameStringArray(a?: string[], b?: string[]): boolean {
  const x = a ?? []
  const y = b ?? []
  if (x.length !== y.length) return false
  return x.every((v, i) => v === y[i])
}

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

  const xi = x.items ?? []
  const yi = y.items ?? []
  if (xi.length !== yi.length) return false
  return xi.every((item, i) => (item?.text ?? '') === (yi[i]?.text ?? '') && (item?.indent ?? 0) === (yi[i]?.indent ?? 0))
}

function sameStyle(a?: Record<string, unknown>, b?: Record<string, unknown>): boolean {
  const x = a ?? {}
  const y = b ?? {}
  const keys = new Set([...Object.keys(x), ...Object.keys(y)])
  for (const k of keys) {
    if ((x[k] ?? null) !== (y[k] ?? null)) return false
  }
  return true
}

const isTight = (node: { tight?: boolean }) => node.tight === true

function sameContent(a: Content, b: Content): boolean {
  return (
    a.type === b.type &&
    sameContentData(a.content, b.content) &&
    sameStyle(a.style as Record<string, unknown>, b.style as Record<string, unknown>) &&
    isTight(a) === isTight(b)
  )
}

export function unitTexts(content: Content): string[] {
  const d = content.content ?? {}
  switch (content.type) {
    case 'iconText':
      return [d.text ?? '']
    case 'twoColumn':
      return (d.columns ?? []).map((col) => col ?? '')
    case 'timeRange':
      return [`${d.start ?? ''} - ${d.end ?? ''}`]
    case 'listText': {
      const items = (d.items ?? []) as Array<ListItem | string>
      return items.map((item) => (typeof item === 'string' ? item : item?.text ?? ''))
    }
    case 'tag':
      return (d.tags ?? []).map((tag) => tag ?? '')
    default:
      return []
  }
}

function withoutUnitTexts(content: Content): Content {
  const data: ContentData = { ...(content.content ?? {}) }
  switch (content.type) {
    case 'iconText':
      data.text = ''
      break
    case 'twoColumn':
      if (data.columns) data.columns = data.columns.map(() => '')
      break
    case 'timeRange':
      data.start = ''
      data.end = ''
      break
    case 'listText':
      if (data.items) {
        data.items = (data.items as Array<ListItem | string>).map((item) =>
          typeof item === 'string' ? { text: '' } : { ...item, text: '' },
        )
      }
      break
    case 'tag':
      if (data.tags) data.tags = data.tags.map(() => '')
      break
  }
  return { ...content, content: data }
}

function textSummary(text: string): string {
  const value = (text ?? '').replace(/\s+/g, ' ').trim()
  return value.length > 60 ? `${value.slice(0, 60)}…` : value
}

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

function addChange(
  diff: ResumeDiff,
  level: ChangeLevel,
  kind: DiffMark,
  nodeId: string,
  sectionId: string,
  beforeText = '',
  afterText = '',
  unitIndex?: number,
): void {
  diff.changes.push({
    key: level === 'unit' ? `unit:${nodeId}:${unitIndex}` : `${level}:${nodeId}`,
    level,
    kind,
    sectionId,
    nodeId,
    unitIndex,
    beforeText,
    afterText,
  })
}

function markSubtree(row: LayoutWindow, marks: DiffMarks, mark: DiffMark): void {
  marks.rows[row.id] = mark
}

function diffUnits(a: Content, b: Content, sectionId: string, diff: ResumeDiff): boolean {
  const oldUnits = unitTexts(a)
  const newUnits = unitTexts(b)
  if (oldUnits.length === 0 || oldUnits.length !== newUnits.length) return false
  if (!sameContent(withoutUnitTexts(a), withoutUnitTexts(b))) return false

  let before = diff.before.units[a.id]
  if (!before) diff.before.units[a.id] = before = {}
  let after = diff.after.units[b.id]
  if (!after) diff.after.units[b.id] = after = {}

  let changed = false
  for (let i = 0; i < oldUnits.length; i++) {
    if (oldUnits[i] === newUnits[i]) continue
    before[i] = 'changed'
    after[i] = 'changed'
    addChange(
      diff,
      'unit',
      'changed',
      a.id,
      sectionId,
      textSummary(oldUnits[i]),
      textSummary(newUnits[i]),
      i,
    )
    changed = true
  }
  return changed
}

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
      if (diffUnits(a, b, sectionId, diff)) continue
      diff.before.contents[id] = 'changed'
      diff.after.contents[id] = 'changed'
      addChange(diff, 'content', 'changed', id, sectionId, contentSummary(a), contentSummary(b))
    }
  }
}

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

  diff.changedCount = diff.changes.length
  return diff
}

export type DiffAttr = DiffMark | 'restored' | 'ignored'

export function diffAttr(mark: DiffMark | undefined, view: ChangeView | undefined): DiffAttr | undefined {
  if (view?.reverted) return view.kind === 'added' ? 'ignored' : 'restored'
  return mark
}

export interface MergeResult {
  sections: Section[]
  ignored: Set<string>
}

export type RevertedSet = ReadonlySet<string>

const isReverted = (reverted: RevertedSet, level: ChangeLevel, id: string) =>
  reverted.has(`${level}:${id}`)

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

function restoreUnits(before: Content, after: Content, reverted: RevertedSet): Content {
  const prefix = `unit:${after.id}:`
  let touched = false
  for (const key of reverted) {
    if (key.startsWith(prefix)) {
      touched = true
      break
    }
  }
  if (!touched) return after

  const oldTexts = unitTexts(before)
  const pick = (i: number, current: string) =>
    reverted.has(`${prefix}${i}`) && oldTexts[i] !== undefined ? oldTexts[i] : current
  const data: ContentData = { ...(after.content ?? {}) }

  switch (after.type) {
    case 'iconText':
      data.text = pick(0, data.text ?? '')
      break
    case 'twoColumn':
      if (data.columns) data.columns = data.columns.map((col, i) => pick(i, col ?? ''))
      break
    case 'timeRange':
      if (reverted.has(`${prefix}0`)) {
        data.start = before.content?.start ?? ''
        data.end = before.content?.end ?? ''
      }
      break
    case 'listText':
      if (data.items) {
        data.items = (data.items as Array<ListItem | string>).map((item, i) =>
          typeof item === 'string'
            ? { text: pick(i, item) }
            : { ...item, text: pick(i, item?.text ?? '') },
        )
      }
      break
    case 'tag':
      if (data.tags) data.tags = data.tags.map((tag, i) => pick(i, tag ?? ''))
      break
  }
  return { ...after, content: data }
}

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
        return isReverted(reverted, 'content', b.id) ? a : restoreUnits(a, b, reverted)
      }
      if (!isReverted(reverted, 'content', b.id)) return b
      if (!keepIgnored) return null
      ignored.add(`content:${b.id}`)
      return b
    },
  )
}

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

const BUCKET: Record<'section' | 'row' | 'content', 'sections' | 'rows' | 'contents'> = {
  section: 'sections',
  row: 'rows',
  content: 'contents',
}

export function buildControls(
  diff: ResumeDiff,
  side: 'before' | 'after',
  reverted: RevertedSet,
  toggle: (key: string) => void,
  diagIndexByKey?: ReadonlyMap<string, number>,
  jumpToDiagnosis?: (index: number) => void,
): DiffControls {
  const controls = emptyControls()
  for (const change of diff.changes) {
    const onThisSide = change.kind === 'removed' || side === 'after'
    if (!onThisSide) continue
    const view: ChangeView = {
      kind: change.kind,
      reverted: reverted.has(change.key),
      toggle: () => toggle(change.key),
    }
    const diagIndex = diagIndexByKey?.get(change.key)
    if (diagIndex !== undefined) {
      view.diagIndex = diagIndex
      view.jumpToDiagnosis = () => jumpToDiagnosis?.(diagIndex)
    }
    if (change.level === 'unit') {
      const index = change.unitIndex ?? 0
      let bucket = controls.units[change.nodeId]
      if (!bucket) controls.units[change.nodeId] = bucket = {}
      bucket[index] = view
      continue
    }
    controls[BUCKET[change.level]][change.nodeId] = view
  }
  return controls
}

const PATCHABLE_TYPES = new Set<ContentType>(['iconText', 'twoColumn', 'timeRange', 'listText', 'tag'])

export interface CoordTarget {
  sectionId: string
  contentId: string
  unitIndex: number
}

export function coordToTarget(
  resume: Section[],
  s: number,
  r: number,
  c: number,
  i: number,
): CoordTarget | null {
  if (!(0 <= s && s < resume.length)) return null
  const section = resume[s]
  const leaves: LayoutWindow[] = []
  const walk = (rows: LayoutWindow[]) => {
    for (const row of rows) {
      if (row.rows && row.rows.length) walk(row.rows)
      else leaves.push(row)
    }
  }
  walk(section.rows ?? [])
  if (!(0 <= r && r < leaves.length)) return null
  const patchable = (leaves[r].contents ?? []).filter((c) => PATCHABLE_TYPES.has(c.type))
  if (!(0 <= c && c < patchable.length)) return null
  return { sectionId: section.id, contentId: patchable[c].id, unitIndex: i }
}

export function collectContentUnits(resume: Section[]): Map<string, string[]> {
  const map = new Map<string, string[]>()
  const walkRows = (rows: LayoutWindow[]) => {
    for (const row of rows) {
      if (row.rows && row.rows.length) walkRows(row.rows)
      for (const content of row.contents ?? []) {
        map.set(content.id, unitTexts(content))
      }
    }
  }
  for (const section of resume) walkRows(section.rows ?? [])
  return map
}

export interface InlineDiffSeg {
  kind: 'eq' | 'del' | 'ins'
  text: string
}

const CJK_CHAR = /[一-鿿]/

function tokenize(s: string): string[] {
  const tokens: string[] = []
  let i = 0
  while (i < s.length) {
    if (CJK_CHAR.test(s[i])) {
      tokens.push(s[i])
      i++
    } else {
      let j = i
      while (j < s.length && !CJK_CHAR.test(s[j])) j++
      tokens.push(s.slice(i, j))
      i = j
    }
  }
  return tokens
}

export function diffInlineText(a: string, b: string): InlineDiffSeg[] {
  const at = tokenize(a)
  const bt = tokenize(b)
  const m = at.length
  const n = bt.length
  const lcs: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      lcs[i][j] = at[i] === bt[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const ops: InlineDiffSeg[] = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    if (at[i] === bt[j]) {
      ops.push({ kind: 'eq', text: at[i] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      ops.push({ kind: 'del', text: at[i] })
      i++
    } else {
      ops.push({ kind: 'ins', text: bt[j] })
      j++
    }
  }
  while (i < m) {
    ops.push({ kind: 'del', text: at[i] })
    i++
  }
  while (j < n) {
    ops.push({ kind: 'ins', text: bt[j] })
    j++
  }
  const segs: InlineDiffSeg[] = []
  for (const op of ops) {
    const last = segs[segs.length - 1]
    if (last && last.kind === op.kind) last.text += op.text
    else segs.push({ kind: op.kind, text: op.text })
  }
  return segs
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function inlineDiffHtml(a: string, b: string): string {
  return diffInlineText(a, b)
    .map((seg) => {
      if (seg.kind === 'eq') return escapeHtml(seg.text)
      if (seg.kind === 'del') return `<del>${escapeHtml(seg.text)}</del>`
      return `<ins>${escapeHtml(seg.text)}</ins>`
    })
    .join('')
}
