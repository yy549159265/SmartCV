/**
 * 简历数据仓库：全应用唯一数据源。
 * 编辑画布、预览、样式面板、导出读写的都是 state.resume，不存在第二份拷贝。
 */

import { defineStore } from 'pinia'
import type { Content, Section, LayoutWindow, ContentStyle, SectionLayout, SectionStyle } from '@/types'
import {
  createContentFromPreset,
  createSectionFromPreset,
  createRowFromPreset,
  type ContentPreset,
  type SectionPreset,
  type RowPreset,
} from '@/data/presets'
import { uid } from '@/utils/id'
import { mergeStyle } from '@/utils/style'
import type { PagePlan, PageUnit } from '@/utils/pagination'

const MAX_HISTORY = 50

const EMPTY_CONTENT_DATA: Record<Content['type'], Content['content']> = {
  iconText: { icon: '', text: '' },
  twoColumn: { columns: ['', ''], separator: '|' },
  timeRange: { start: '', end: '' },
  tag: { tags: ['新标签'] },
  listText: { listType: 'bullet', items: [{ text: '' }] },
  image: { image: '', imageSize: 96, imageShape: 'rounded' },
  spacer: {},
}

function findContent(
  resume: Section[],
  contentId: string,
): { section: Section; row: LayoutWindow; index: number } | undefined {
  for (const g of resume) {
    for (const r of g.rows) {
      const found = findContentInRow(r, contentId)
      if (found) return { section: g, row: found.row, index: found.index }
    }
  }
  return undefined
}

function findContentInRow(row: LayoutWindow, contentId: string): { row: LayoutWindow; index: number } | undefined {
  if (row.contents) {
    const index = row.contents.findIndex((b) => b.id === contentId)
    if (index >= 0) return { row, index }
  }
  for (const child of row.rows ?? []) {
    const found = findContentInRow(child, contentId)
    if (found) return found
  }
  return undefined
}

function findRowWithParent(
  rows: LayoutWindow[],
  rowId: string,
  parentRow: LayoutWindow | null = null,
  grandList: LayoutWindow[] | null = null,
  grandRow: LayoutWindow | null = null,
): {
  row: LayoutWindow
  parentList: LayoutWindow[]
  parentRow: LayoutWindow | null
  grandList: LayoutWindow[] | null
  grandRow: LayoutWindow | null
  index: number
} | undefined {
  const topIndex = rows.findIndex((r) => r.id === rowId)
  if (topIndex >= 0) {
    return { row: rows[topIndex], parentList: rows, parentRow, grandList, grandRow, index: topIndex }
  }
  for (const r of rows) {
    if (r.rows && r.rows.length > 0) {
      const found = findRowWithParent(r.rows, rowId, r, rows, parentRow)
      if (found) return found
    }
  }
  return undefined
}

type RowAncestry = NonNullable<ReturnType<typeof findRowWithParent>>

function placeRowNear(found: RowAncestry, newRow: LayoutWindow, pos: 'top' | 'bottom' | 'left' | 'right', section: Section) {
  const { row, parentList, parentRow, grandList, index } = found

  if (row.rows) {
    if (pos === 'left' || pos === 'top') row.rows.unshift(newRow)
    else row.rows.push(newRow)
    return
  }

  if (pos === 'left' || pos === 'right') {
    if (parentRow?.layout === 'horizontal') {
      parentList.splice(pos === 'left' ? index : index + 1, 0, newRow)
    } else {
      const container: LayoutWindow = {
        id: uid(),
        layout: 'horizontal',
        contents: [],
        rows: pos === 'left' ? [newRow, row] : [row, newRow],
      }
      parentList.splice(index, 1, container)
    }
  } else {
    if (parentRow?.layout === 'horizontal') {
      const newRowContainer: LayoutWindow = { id: uid(), layout: 'horizontal', contents: [], rows: [newRow] }
      const rowList = grandList ?? section.rows
      const rowIndex = rowList.indexOf(parentRow)
      rowList.splice(pos === 'top' ? rowIndex : rowIndex + 1, 0, newRowContainer)
    } else {
      parentList.splice(pos === 'top' ? index : index + 1, 0, newRow)
    }
  }
}

function normalizeRow(row: LayoutWindow): LayoutWindow {
  if (!row.rows || row.rows.length === 0) return row
  row.rows = row.rows.map(normalizeRow)
  if (row.rows.length === 1) return row.rows[0]
  return row
}

function isDescendant(row: LayoutWindow, targetId: string): boolean {
  for (const child of row.rows ?? []) {
    if (child.id === targetId || isDescendant(child, targetId)) return true
  }
  return false
}

function lastLeafRow(row: LayoutWindow): LayoutWindow {
  if (row.rows && row.rows.length > 0) return lastLeafRow(row.rows[row.rows.length - 1])
  return row
}

function cloneRow(row: LayoutWindow): LayoutWindow {
  const copy: LayoutWindow = {
    id: uid(),
    layout: row.layout,
    contents: row.contents.map((b) => ({ ...JSON.parse(JSON.stringify(b)), id: uid() })),
    ...(row.tight === true ? { tight: true } : {}),
  }
  if (row.rows) copy.rows = row.rows.map(cloneRow)
  return copy
}

export const RESUME_STORAGE_KEY = 'smartcv-resume-data'

const VALID_CONTENT_TYPES = ['iconText', 'twoColumn', 'timeRange', 'tag', 'listText', 'image', 'spacer'] as const

function normalizeContentImport(raw: Record<string, unknown>): Content | undefined {
  const type = raw.type as Content['type']
  if (!VALID_CONTENT_TYPES.includes(type as (typeof VALID_CONTENT_TYPES)[number])) return undefined
  const content = (raw.content as Content['content']) ?? {}
  if (type === 'twoColumn' && !Array.isArray(content.columns)) {
    const legacy = content as unknown as Record<string, unknown>
    content.columns = [
      typeof legacy.left === 'string' ? legacy.left : '',
      typeof legacy.right === 'string' ? legacy.right : '',
    ]
    content.separator = typeof legacy.separator === 'string' ? legacy.separator : '|'
    delete legacy.left
    delete legacy.right
  }
  return {
    id: uid(),
    kind: 'content',
    type,
    content,
    style: (raw.style as Content['style']) ?? {},
    ...(raw.tight === true ? { tight: true } : {}),
  }
}

function normalizeRowImport(raw: Record<string, unknown>): LayoutWindow {
  const layout: SectionLayout = raw.layout === 'horizontal' ? 'horizontal' : 'vertical'
  const contents = (
    Array.isArray(raw.contents) ? raw.contents : Array.isArray(raw.blocks) ? raw.blocks : []
  )
    .map((b) => normalizeContentImport(b as Record<string, unknown>))
    .filter((b): b is Content => b !== undefined)
  const childRows = Array.isArray(raw.rows) ? raw.rows.map((r) => normalizeRowImport(r as Record<string, unknown>)) : []
  return {
    id: uid(),
    layout,
    contents,
    ...(Array.isArray(raw.rows) ? { rows: childRows } : {}),
    ...(raw.tight === true ? { tight: true } : {}),
  }
}

function normalizeResumeData(data: unknown): Section[] | null {
  if (!Array.isArray(data)) return null
  const sections: Section[] = []
  for (const item of data) {
    const raw = item as Record<string, unknown>
    if (!raw || typeof raw !== 'object') continue
    let rows: LayoutWindow[] = []
    if (Array.isArray(raw.rows)) {
      rows = raw.rows.map((r) => normalizeRowImport(r as Record<string, unknown>))
    } else {
      const direct = Array.isArray(raw.contents) ? raw.contents : Array.isArray(raw.blocks) ? raw.blocks : []
      if (direct.length > 0) {
        rows = [
          {
            id: uid(),
            layout: 'vertical',
            contents: direct
              .map((b) => normalizeContentImport(b as Record<string, unknown>))
              .filter((b): b is Content => b !== undefined),
          },
        ]
      }
    }
    sections.push({
      id: uid(),
      kind: 'section',
      title: typeof raw.title === 'string' ? raw.title : '新章节',
      style: (raw.style as SectionStyle) ?? {},
      rows,
      ...(raw.pageBreakBefore === true ? { pageBreakBefore: true } : {}),
    })
  }
  return sections
}

function loadResumeFromStorage(): Section[] {
  try {
    const raw = localStorage.getItem(RESUME_STORAGE_KEY)
    if (raw) {
      const normalized = normalizeResumeData(JSON.parse(raw))
      if (normalized) return normalized
    }
  } catch {
  }
  return []
}

export const useResumeStore = defineStore('resume', {
  state: () => ({
    resume: loadResumeFromStorage() as Section[],
    selectedId: null as string | null,
    collapsedSectionIds: [] as string[],
    collapsedContentIds: [] as string[],
    pagePlan: { pages: [], pageStartOffsets: [], totalHeight: 0 } as PagePlan,
    pageUnits: [] as PageUnit[],
    undoStack: [] as Section[][],
    redoStack: [] as Section[][],
  }),

  getters: {
    selectedSection(state): Section | undefined {
      return state.resume.find((g) => g.id === state.selectedId)
    },
    selectedContent(state): { section: Section; row: LayoutWindow; content: Content } | undefined {
      const found = findContent(state.resume, state.selectedId ?? '')
      return found ? { section: found.section, row: found.row, content: found.row.contents[found.index] } : undefined
    },
    selectedRow(state): { section: Section; row: LayoutWindow } | undefined {
      for (const g of state.resume) {
        const found = findRowWithParent(g.rows, state.selectedId ?? '')
        if (found) return { section: g, row: found.row }
      }
      return undefined
    },
    sectionById: (state) => (id: string) => state.resume.find((g) => g.id === id),
    unitById: (state) => (id: string) => state.pageUnits.find((u) => u.id === id),
    isRowContainer: (state) => (sectionId: string, rowId: string) => {
      const section = state.resume.find((g) => g.id === sectionId)
      if (!section) return false
      return !!findRowWithParent(section.rows, rowId)?.row.rows
    },
    isSectionCollapsed: (state) => (id: string) => state.collapsedSectionIds.includes(id),
    isContentCollapsed: (state) => (id: string) => state.collapsedContentIds.includes(id),
  },

  actions: {

    select(id: string | null) {
      this.selectedId = id
    },

    toggleSectionCollapsed(id: string) {
      const i = this.collapsedSectionIds.indexOf(id)
      if (i >= 0) this.collapsedSectionIds.splice(i, 1)
      else this.collapsedSectionIds.push(id)
    },

    toggleContentCollapsed(id: string) {
      const i = this.collapsedContentIds.indexOf(id)
      if (i >= 0) this.collapsedContentIds.splice(i, 1)
      else this.collapsedContentIds.push(id)
    },

    clearAll() {
      this.resume.splice(0, this.resume.length)
      this.selectedId = null
      this.collapsedSectionIds = []
      this.collapsedContentIds = []
    },

    importResume(data: unknown): boolean {
      const normalized = normalizeResumeData(data)
      if (!normalized) return false
      this.resume.splice(0, this.resume.length, ...normalized)
      this.selectedId = null
      this.collapsedSectionIds = []
      this.collapsedContentIds = []
      return true
    },

    canOpenResume(data: unknown): boolean {
      return normalizeResumeData(data) !== null
    },

    openResume(data: unknown): boolean {
      const normalized = normalizeResumeData(data)
      if (!normalized) return false
      this.resume.splice(0, this.resume.length, ...normalized)
      this.selectedId = null
      this.collapsedSectionIds = []
      this.collapsedContentIds = []
      this.undoStack = []
      this.redoStack = []
      return true
    },

    saveToStorage(): void {
      try {
        localStorage.setItem(RESUME_STORAGE_KEY, JSON.stringify(this.resume))
      } catch {
      }
    },

    addSection(preset: SectionPreset, index?: number) {
      const section = createSectionFromPreset(preset)
      if (index === undefined || index < 0 || index > this.resume.length) {
        this.resume.push(section)
      } else {
        this.resume.splice(index, 0, section)
      }
      this.selectedId = section.id
    },

    removeSection(id: string) {
      const i = this.resume.findIndex((g) => g.id === id)
      if (i >= 0) {
        this.resume.splice(i, 1)
        if (this.selectedId === id) this.selectedId = null
        this.collapsedSectionIds = this.collapsedSectionIds.filter((x) => x !== id)
      }
    },

    duplicateSection(id: string) {
      const g = this.resume.find((x) => x.id === id)
      if (!g) return
      const copy: Section = {
        ...JSON.parse(JSON.stringify(g)),
        id: uid(),
        rows: g.rows.map(cloneRow),
      }
      this.resume.splice(this.resume.indexOf(g) + 1, 0, copy)
      this.selectedId = copy.id
    },

    updateSection(
      id: string,
      patch: Partial<Pick<Section, 'title' | 'icon' | 'pageBreakBefore'>> & {
        style?: Partial<SectionStyle>
      },
    ) {
      const g = this.resume.find((x) => x.id === id)
      if (!g) return
      if (patch.title !== undefined) g.title = patch.title
      if (patch.icon !== undefined) g.icon = patch.icon
      if (patch.pageBreakBefore !== undefined) g.pageBreakBefore = patch.pageBreakBefore
      mergeStyle(g.style, patch.style)
    },

    moveSection(id: string, toIndex: number) {
      const fromIndex = this.resume.findIndex((g) => g.id === id)
      if (fromIndex < 0) return
      const [section] = this.resume.splice(fromIndex, 1)
      let idx = fromIndex < toIndex ? toIndex - 1 : toIndex
      idx = Math.min(Math.max(idx, 0), this.resume.length)
      this.resume.splice(idx, 0, section)
      this.selectedId = section.id
    },

    createRow(layout: SectionLayout = 'vertical'): LayoutWindow {
      return { id: uid(), layout, contents: [] }
    },

    addRow(sectionId: string, index?: number): LayoutWindow | undefined {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return undefined
      const row = this.createRow()
      if (index === undefined || index < 0 || index > section.rows.length) {
        section.rows.push(row)
      } else {
        section.rows.splice(index, 0, row)
      }
      return row
    },

    addRowFromPreset(sectionId: string, preset: RowPreset, index?: number): LayoutWindow | undefined {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return undefined
      const row = createRowFromPreset(preset)
      if (index === undefined || index < 0 || index > section.rows.length) {
        section.rows.push(row)
      } else {
        section.rows.splice(index, 0, row)
      }
      return row
    },

    insertRowRelative(
      sectionId: string,
      rowId: string,
      pos: 'top' | 'bottom' | 'left' | 'right',
      rowToInsert?: LayoutWindow,
    ): LayoutWindow | undefined {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return undefined
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return undefined
      const newRow = rowToInsert ?? this.createRow()
      placeRowNear(found, newRow, pos, section)
      return newRow
    },

    moveRowByDrop(
      fromSectionId: string,
      rowId: string,
      toSectionId: string,
      toRowId: string,
      pos: 'top' | 'bottom' | 'left' | 'right',
    ) {
      const sourceSection = this.resume.find((g) => g.id === fromSectionId)
      if (!sourceSection) return
      const src = findRowWithParent(sourceSection.rows, rowId)
      if (!src) return
      if (toRowId === rowId || isDescendant(src.row, toRowId)) return

      const toSection = this.resume.find((g) => g.id === toSectionId) ?? sourceSection
      const dst = findRowWithParent(toSection.rows, toRowId)
      if (!dst || dst.row.id === rowId) return

      src.parentList.splice(src.index, 1)
      placeRowNear(dst, src.row, pos, toSection)

      sourceSection.rows = sourceSection.rows.map(normalizeRow)
      if (toSection !== sourceSection) toSection.rows = toSection.rows.map(normalizeRow)
    },

    removeRow(sectionId: string, rowId: string) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return
      const parentList = found.parentList ?? section.rows
      parentList.splice(found.index, 1)
      section.rows = section.rows.map(normalizeRow)
      if (this.selectedId === rowId) this.selectedId = null
    },

    setRowLayout(sectionId: string, rowId: string, layout: SectionLayout) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (found) found.row.layout = layout
    },

    updateRow(sectionId: string, rowId: string, patch: { tight?: boolean }) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return
      if (patch.tight === true) found.row.tight = true
      else if (patch.tight === false) delete found.row.tight
    },

    moveRow(
      sectionId: string,
      rowId: string,
      toSectionId: string,
      toRowId?: string,
      pos: 'before' | 'after' = 'after',
    ) {
      const sourceSection = this.resume.find((g) => g.id === sectionId)
      if (!sourceSection) return
      const src = findRowWithParent(sourceSection.rows, rowId)
      if (!src) return
      if (toRowId && (toRowId === rowId || isDescendant(src.row, toRowId))) return

      const toSection = this.resume.find((g) => g.id === toSectionId) ?? sourceSection

      let dstParent: LayoutWindow[]
      let insertIndex: number
      if (toRowId) {
        const dst = findRowWithParent(toSection.rows, toRowId)
        if (!dst || dst.row.id === rowId) return
        dstParent = dst.parentList ?? toSection.rows
        insertIndex = dst.index + (pos === 'after' ? 1 : 0)
      } else {
        dstParent = toSection.rows
        insertIndex = toSection.rows.length
      }

      const srcParent = src.parentList ?? sourceSection.rows
      srcParent.splice(src.index, 1)
      if (srcParent === dstParent && src.index < insertIndex) insertIndex -= 1
      insertIndex = Math.min(Math.max(insertIndex, 0), dstParent.length)
      dstParent.splice(insertIndex, 0, src.row)

      sourceSection.rows = sourceSection.rows.map(normalizeRow)
      if (toSection !== sourceSection) toSection.rows = toSection.rows.map(normalizeRow)
    },

    addContent(sectionId: string, rowId: string, preset: ContentPreset, index?: number) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return
      const row = lastLeafRow(found.row)
      const content = createContentFromPreset(preset)
      if (index === undefined || index < 0 || index > row.contents.length) {
        row.contents.push(content)
      } else {
        row.contents.splice(index, 0, content)
      }
      this.selectedId = content.id
    },

    addBlankContent(sectionId: string, rowId: string, type: Content['type']) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return
      const row = lastLeafRow(found.row)
      const content: Content = {
        id: uid(),
        kind: 'content',
        type,
        content: JSON.parse(JSON.stringify(EMPTY_CONTENT_DATA[type])),
        style: {},
      }
      row.contents.push(content)
      this.selectedId = content.id
    },

    removeContent(sectionId: string, contentId: string) {
      const found = findContent(this.resume, contentId)
      if (!found) return
      found.row.contents.splice(found.index, 1)
      if (this.selectedId === contentId) this.selectedId = null
      this.collapsedContentIds = this.collapsedContentIds.filter((x) => x !== contentId)
    },

    duplicateContent(sectionId: string, contentId: string) {
      const found = findContent(this.resume, contentId)
      if (!found) return
      const copy = JSON.parse(JSON.stringify(found.row.contents[found.index])) as Content
      copy.id = uid()
      found.row.contents.splice(found.index + 1, 0, copy)
      this.selectedId = copy.id
    },

    moveContent(
      fromSectionId: string,
      fromRowId: string,
      contentId: string,
      toSectionId: string,
      toRowId: string,
      toIndex: number,
    ) {
      const fromSection = this.resume.find((g) => g.id === fromSectionId)
      if (!fromSection) return
      const fromFound = findRowWithParent(fromSection.rows, fromRowId)
      if (!fromFound) return
      const fromRow = lastLeafRow(fromFound.row)
      const fromIndex = fromRow.contents.findIndex((b) => b.id === contentId)
      if (fromIndex < 0) return
      const [content] = fromRow.contents.splice(fromIndex, 1)

      const toSection = this.resume.find((g) => g.id === toSectionId) ?? fromSection
      const toFound = findRowWithParent(toSection.rows, toRowId)
      const toRow = toFound
        ? lastLeafRow(toFound.row)
        : lastLeafRow(toSection.rows[toSection.rows.length - 1])
      if (!toRow) return
      let idx = toIndex
      if (fromRow.id === toRow.id && fromIndex < toIndex) idx -= 1
      idx = Math.min(Math.max(idx, 0), toRow.contents.length)
      toRow.contents.splice(idx, 0, content)
      this.selectedId = content.id
    },

    updateContent(
      sectionId: string,
      contentId: string,
      patch: { content?: Partial<Content['content']>; style?: Partial<ContentStyle>; tight?: boolean },
    ) {
      const found = findContent(this.resume, contentId)
      if (!found) return
      const content = found.row.contents[found.index]
      if (patch.content) {
        Object.assign(content.content, patch.content)
      }
      mergeStyle(content.style, patch.style)
      if (patch.tight === true) content.tight = true
      else if (patch.tight === false) delete content.tight
    },

    pushSnapshot() {
      this.undoStack.push(JSON.parse(JSON.stringify(this.resume)))
      if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift()
      this.redoStack = []
    },

    undo() {
      const prev = this.undoStack.pop()
      if (!prev) return
      this.redoStack.push(JSON.parse(JSON.stringify(this.resume)))
      if (this.redoStack.length > MAX_HISTORY) this.redoStack.shift()
      this.resume.splice(0, this.resume.length, ...prev)
      this.selectedId = null
    },

    redo() {
      const next = this.redoStack.pop()
      if (!next) return
      this.undoStack.push(JSON.parse(JSON.stringify(this.resume)))
      if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift()
      this.resume.splice(0, this.resume.length, ...next)
      this.selectedId = null
    },

    setPagination(plan: PagePlan, units: PageUnit[]) {
      this.pagePlan = plan
      this.pageUnits = units
    },
  },
})
