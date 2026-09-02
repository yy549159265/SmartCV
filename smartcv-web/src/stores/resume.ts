/**
 * 简历数据仓库（Pinia Store）—— 全应用【唯一数据源】
 *
 * 设计原则（任务要求）：
 *   编辑画布、右侧预览、样式面板读写的都是同一份数据（state.resume），
 *   改动数据 = 同步视图，不存在第二份拷贝。
 *
 * 数据结构（三层）：
 *   resume: Section[]       章节
 *     └─ rows: LayoutWindow[]      布局窗口（章节内可放多个，每个独立选横/竖）
 *          └─ contents: Content[]  内容单元
 *
 * 与拖拽的关系：拖拽用 vue-draggable-plus（内部 SortableJS），
 * 列表的 v-model 直接绑定这里的数组，排序即数据变更 —— 数据只有这一份。
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

/** 撤销历史最多保留多少步（再多就丢最早的） */
const MAX_HISTORY = 50

/** 新建的"空白内容"默认内容（按类型给占位值） */
const EMPTY_CONTENT_DATA: Record<Content['type'], Content['content']> = {
  iconText: { icon: '', text: '' },
  twoColumn: { columns: ['', ''], separator: '|' },
  timeRange: { start: '', end: '' },
  tag: { tags: ['新标签'] },
  listText: { listType: 'bullet', items: [{ text: '' }] },
  image: { image: '', imageSize: 96, imageShape: 'rounded' },
  spacer: {},
}

/** 在整份简历里按 id 找某个内容的位置（章节 + 窗口 + 下标） */
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

/** 递归查找窗口（含嵌套容器窗口）里的内容 */
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

/**
 * 递归查找某个窗口及其"父级链"。
 * parentList = 装着它的数组（顶层 = 章节的 rows，嵌套 = 父容器的 rows）；
 * parentRow = 父容器窗口（顶层为 null）；
 * grandList / grandRow = 父容器的"父级"（横排里的窗口用它定位"排"）。
 */
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

/** findRowWithParent 的返回类型 */
type RowAncestry = NonNullable<ReturnType<typeof findRowWithParent>>

/**
 * 按"落点位置"把新窗口放到目标窗口附近（拖拽排列的共用逻辑）：
 *  - 目标是【容器】：左/上 = 子窗口最前，右/下 = 子窗口最后（插进容器内部）；
 *  - 目标是【叶子】：左/右 = 与它左右并排（已在横排里就插进同一排，
 *    否则包一层横向容器）；上/下 = 与它上下堆叠（已在横排里就新建一排，
 *    否则插进竖向列表的前/后）。
 */
function placeRowNear(found: RowAncestry, newRow: LayoutWindow, pos: 'top' | 'bottom' | 'left' | 'right', section: Section) {
  const { row, parentList, parentRow, grandList, index } = found

  // 目标是容器 → 插进容器内部
  if (row.rows) {
    if (pos === 'left' || pos === 'top') row.rows.unshift(newRow)
    else row.rows.push(newRow)
    return
  }

  // 目标是叶子窗口
  if (pos === 'left' || pos === 'right') {
    if (parentRow?.layout === 'horizontal') {
      // 已在横排里 → 并到这一排
      parentList.splice(pos === 'left' ? index : index + 1, 0, newRow)
    } else {
      // 竖向列表（容器/章节）→ 包一层横向容器，让它俩左右并排
      const container: LayoutWindow = {
        id: uid(),
        layout: 'horizontal',
        contents: [],
        rows: pos === 'left' ? [newRow, row] : [row, newRow],
      }
      parentList.splice(index, 1, container)
    }
  } else {
    // top / bottom
    if (parentRow?.layout === 'horizontal') {
      // 在横排里 → 上/下 = 新建一排
      const newRowContainer: LayoutWindow = { id: uid(), layout: 'horizontal', contents: [], rows: [newRow] }
      const rowList = grandList ?? section.rows
      const rowIndex = rowList.indexOf(parentRow)
      rowList.splice(pos === 'top' ? rowIndex : rowIndex + 1, 0, newRowContainer)
    } else {
      // 竖向列表（容器/章节）→ 插进前/后
      parentList.splice(pos === 'top' ? index : index + 1, 0, newRow)
    }
  }
}

/** 递归塌缩：任何"只剩一个子窗口"的容器都用它的子窗口替换自身 */
function normalizeRow(row: LayoutWindow): LayoutWindow {
  if (!row.rows || row.rows.length === 0) return row
  row.rows = row.rows.map(normalizeRow)
  if (row.rows.length === 1) return row.rows[0]
  return row
}

/** 判断 targetId 是否是 row 的后代（防止把容器窗口拖进它自己里面） */
function isDescendant(row: LayoutWindow, targetId: string): boolean {
  for (const child of row.rows ?? []) {
    if (child.id === targetId || isDescendant(child, targetId)) return true
  }
  return false
}

/** 找窗口内最深的"最后一个叶子窗口"（容器窗口不能直接放内容，落到最后的叶子上） */
function lastLeafRow(row: LayoutWindow): LayoutWindow {
  if (row.rows && row.rows.length > 0) return lastLeafRow(row.rows[row.rows.length - 1])
  return row
}

/** 深拷贝窗口并重新生成所有 id（复制章节时用） */
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

/* ---------- 导入 / 持久化 ---------- */

/** localStorage 里保存简历数据的键名 */
export const RESUME_STORAGE_KEY = 'smartcv-resume-data'

/** 全部合法的内容类型（导入时校验用） */
const VALID_CONTENT_TYPES = ['iconText', 'twoColumn', 'timeRange', 'tag', 'listText', 'image', 'spacer'] as const

function normalizeContentImport(raw: Record<string, unknown>): Content | undefined {
  const type = raw.type as Content['type']
  if (!VALID_CONTENT_TYPES.includes(type as (typeof VALID_CONTENT_TYPES)[number])) return undefined
  const content = (raw.content as Content['content']) ?? {}
  // 兼容旧数据：老版本的"分栏"用 left / right 两个字段，导入时自动转成新的 columns 数组
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
  // 兼容旧数据：老版本窗口挂的是 blocks 字段，新版本叫 contents —— 两种都接受
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
    // 空容器（rows: []）也要保留 rows 字段，否则导入后容器会退化成叶子窗口
    ...(Array.isArray(raw.rows) ? { rows: childRows } : {}),
    ...(raw.tight === true ? { tight: true } : {}),
  }
}

/**
 * 把任意数据规范化成简历结构（章节数组）。
 * 兼容旧版（章节直接挂 contents）、非法数据返回 null。
 * 用于"导入 JSON"和"从 localStorage 恢复"两条路径。
 */
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
      // 兼容旧版：章节直接挂 contents / blocks → 包进一个竖向窗口
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
      // 注意：标题只区分"没写 title 字段"和"写了"—— 空字符串就是空标题，
      // 不要自动填"新章节"（用户导出的空标题章节要原样保留）
      title: typeof raw.title === 'string' ? raw.title : '新章节',
      style: (raw.style as SectionStyle) ?? {},
      rows,
      ...(raw.pageBreakBefore === true ? { pageBreakBefore: true } : {}),
    })
  }
  // 注意：空数组也是合法状态（用户清空了简历），只有"结构非法"才返回 null
  return sections
}

/**
 * 应用启动时读取简历数据：
 * 读浏览器里保存的（用户上次编辑的内容）；没有（或损坏）就是空简历。
 * 默认永远是空，不填充任何示例内容。
 */
function loadResumeFromStorage(): Section[] {
  try {
    const raw = localStorage.getItem(RESUME_STORAGE_KEY)
    if (raw) {
      const normalized = normalizeResumeData(JSON.parse(raw))
      if (normalized) return normalized
    }
  } catch {
    /* localStorage 不可用或数据损坏 → 空简历 */
  }
  return []
}

export const useResumeStore = defineStore('resume', {
  state: () => ({
    /** 整份简历：章节数组（唯一数据源；启动时从 localStorage 恢复，没有就是空） */
    resume: loadResumeFromStorage() as Section[],
    /** 当前选中的内容 id（章节或内容） */
    selectedId: null as string | null,
    /**
     * 编辑画布里的"折叠"状态（纯编辑辅助，不属于简历内容，不会导出）：
     * 折叠后只显示标题/摘要，方便长简历在画布里的浏览和整理。
     * 右侧预览始终展示完整内容，不受折叠影响。
     */
    collapsedSectionIds: [] as string[],
    collapsedContentIds: [] as string[],
    /** 分页方案：由 composables/usePagination 测量后写入，画布和预览共用 */
    pagePlan: { pages: [], pageStartOffsets: [], totalHeight: 0 } as PagePlan,
    /** 页面单元列表：标题和顶层行各自是一个"可裁切单元"，预览和导出按它渲染，页数才一致 */
    pageUnits: [] as PageUnit[],
    /** 撤销栈：整份简历的深拷贝快照，栈顶是"最近一次改动前"的状态 */
    undoStack: [] as Section[][],
    /** 重做栈：被撤销掉的状态（出现新改动时清空） */
    redoStack: [] as Section[][],
  }),

  getters: {
    /** 选中的章节（没有则返回 undefined） */
    selectedSection(state): Section | undefined {
      return state.resume.find((g) => g.id === state.selectedId)
    },
    /** 选中的内容，及其所属的章节、布局窗口 */
    selectedContent(state): { section: Section; row: LayoutWindow; content: Content } | undefined {
      const found = findContent(state.resume, state.selectedId ?? '')
      return found ? { section: found.section, row: found.row, content: found.row.contents[found.index] } : undefined
    },
    /** 选中的布局窗口，及其所属的章节；没有则返回 undefined */
    selectedRow(state): { section: Section; row: LayoutWindow } | undefined {
      for (const g of state.resume) {
        const found = findRowWithParent(g.rows, state.selectedId ?? '')
        if (found) return { section: g, row: found.row }
      }
      return undefined
    },
    /** 按 id 查章节 */
    sectionById: (state) => (id: string) => state.resume.find((g) => g.id === id),
    /** 按 id 查页面单元 */
    unitById: (state) => (id: string) => state.pageUnits.find((u) => u.id === id),
    /** 某个窗口是不是「窗口容器」（容器只能放在章节上，不能放进窗口里） */
    isRowContainer: (state) => (sectionId: string, rowId: string) => {
      const section = state.resume.find((g) => g.id === sectionId)
      if (!section) return false
      return !!findRowWithParent(section.rows, rowId)?.row.rows
    },
    /** 章节是否折叠 */
    isSectionCollapsed: (state) => (id: string) => state.collapsedSectionIds.includes(id),
    /** 内容是否折叠 */
    isContentCollapsed: (state) => (id: string) => state.collapsedContentIds.includes(id),
  },

  actions: {
    /* ==================== 选中 ==================== */

    select(id: string | null) {
      this.selectedId = id
    },

    /* ==================== 折叠（编辑辅助，不参与导出） ==================== */

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

    /* ==================== 整体操作 ==================== */

    /** 清空整份简历 */
    clearAll() {
      this.resume.splice(0, this.resume.length)
      this.selectedId = null
      this.collapsedSectionIds = []
      this.collapsedContentIds = []
    },

    /**
     * 导入简历 JSON（配合"导入 JSON"按钮）：
     *  - 校验顶层必须是数组，逐个章节规范化；
     *  - 兼容旧版数据（章节直接挂 contents 的自动包进一个竖向窗口）；
     *  - 所有 id 重新生成（导入是整体替换，避免与现有数据冲突）；
     *  - 成功返回 true 并替换当前简历，失败返回 false（数据不动）。
     */
    importResume(data: unknown): boolean {
      const normalized = normalizeResumeData(data)
      if (!normalized) return false
      this.resume.splice(0, this.resume.length, ...normalized)
      this.selectedId = null
      this.collapsedSectionIds = []
      this.collapsedContentIds = []
      return true
    },

    /**
     * 把当前简历保存到浏览器 localStorage（"保存"按钮 / 自动持久化共用）。
     * 注意：应用里还挂了一个自动保存（main.ts 里监听 store 变化防抖写入），
     * 这个方法是手动触发的兜底。
     */
    saveToStorage(): void {
      try {
        localStorage.setItem(RESUME_STORAGE_KEY, JSON.stringify(this.resume))
      } catch {
        /* 空间不足等异常忽略，自动保存仍然会在下次变化时重试 */
      }
    },

    /* ==================== 章节增删改 ==================== */

    /** 新增一个章节；index 不传就加在末尾 */
    addSection(preset: SectionPreset, index?: number) {
      const section = createSectionFromPreset(preset)
      if (index === undefined || index < 0 || index > this.resume.length) {
        this.resume.push(section)
      } else {
        this.resume.splice(index, 0, section)
      }
      this.selectedId = section.id
    },

    /** 删除一个章节 */
    removeSection(id: string) {
      const i = this.resume.findIndex((g) => g.id === id)
      if (i >= 0) {
        this.resume.splice(i, 1)
        if (this.selectedId === id) this.selectedId = null
        // 清理折叠状态（章节没了，折叠标记也要跟着清理）
        this.collapsedSectionIds = this.collapsedSectionIds.filter((x) => x !== id)
      }
    },

    /** 复制一个章节（插在原位置后面；窗口树里的所有 id 都重新生成） */
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

    /** 修改章节的标题/强制分页/样式（style 里 undefined 的字段 = 清除该字段） */
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

    /**
     * 拖拽排序：把章节移到 toIndex 位置。
     * toIndex 是"删除前"的目标下标（由组件按当前列表算好），这里做越界修正。
     */
    moveSection(id: string, toIndex: number) {
      const fromIndex = this.resume.findIndex((g) => g.id === id)
      if (fromIndex < 0) return
      const [section] = this.resume.splice(fromIndex, 1)
      // 移除自己之后，原目标位置要回退一格
      let idx = fromIndex < toIndex ? toIndex - 1 : toIndex
      idx = Math.min(Math.max(idx, 0), this.resume.length)
      this.resume.splice(idx, 0, section)
      this.selectedId = section.id
    },

    /* ==================== 布局窗口（章节内部，可嵌套） ==================== */

    /** 新建一个空白"叶子"布局窗口 */
    createRow(layout: SectionLayout = 'vertical'): LayoutWindow {
      return { id: uid(), layout, contents: [] }
    },

    /** 在章节顶层新增一个空白布局窗口（默认竖向），返回新窗口 */
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

    /** 按"布局预设"（窗口布局 / 2列 / 3列 / 2行 / 3行）在章节顶层新增窗口 */
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

    /**
     * 把窗口按"落点位置"放到目标窗口附近（拖拽排列用，＋按钮已取消，只能拖拽）：
     *  - 目标是【容器】：左/上 = 子窗口最前，右/下 = 子窗口最后（插进容器内部）；
     *  - 目标是【叶子】：左/右 = 与它左右并排（已在横排里就插进同一排，
     *    否则包一层横向容器）；上/下 = 与它上下堆叠（已在横排里就新建一排，
     *    否则插进竖向列表的前/后）。
     */
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

    /**
     * 拖拽移动布局窗口（按落点位置排列，规则同 insertRowRelative）。
     * 防呆：不能把窗口拖进它自己的子树。
     */
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
      // 不能拖进自己的子树
      if (toRowId === rowId || isDescendant(src.row, toRowId)) return

      const toSection = this.resume.find((g) => g.id === toSectionId) ?? sourceSection
      const dst = findRowWithParent(toSection.rows, toRowId)
      if (!dst || dst.row.id === rowId) return

      // 先把被拖的窗口从原位置摘出来，再按落点放到位
      src.parentList.splice(src.index, 1)
      placeRowNear(dst, src.row, pos, toSection)

      // 移动后塌缩（源容器可能只剩一个子窗口）
      sourceSection.rows = sourceSection.rows.map(normalizeRow)
      if (toSection !== sourceSection) toSection.rows = toSection.rows.map(normalizeRow)
    },

    /** 删除一个布局窗口；父容器只剩一个子窗口时自动"塌缩"（用剩余子窗口替换容器） */
    removeRow(sectionId: string, rowId: string) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return
      const parentList = found.parentList ?? section.rows
      parentList.splice(found.index, 1)
      // 递归塌缩所有容器（容器只剩一个子窗口时用子窗口替换容器）
      section.rows = section.rows.map(normalizeRow)
      // 删掉的正好是选中窗口时，清掉选中（否则 selectedId 会指向一个不存在的窗口）
      if (this.selectedId === rowId) this.selectedId = null
    },

    /** 修改布局窗口的排列方式（叶子 = 内容方向；容器 = 子窗口方向） */
    setRowLayout(sectionId: string, rowId: string, layout: SectionLayout) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (found) found.row.layout = layout
    },

    /** 修改布局窗口的其他字段（如紧贴开关） */
    updateRow(sectionId: string, rowId: string, patch: { tight?: boolean }) {
      const section = this.resume.find((g) => g.id === sectionId)
      if (!section) return
      const found = findRowWithParent(section.rows, rowId)
      if (!found) return
      if (patch.tight === true) found.row.tight = true
      else if (patch.tight === false) delete found.row.tight
    },

    /**
     * 拖拽移动布局窗口：
     *  - toRowId 不传 → 移到目标章节顶层末尾；
     *  - toRowId 传入 → 移到目标窗口的前面（pos='before'）或后面（pos='after'）。
     * 防呆：不能把窗口拖进它自己的子树（容器拖进自己里面会死循环）。
     */
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
      // 不能拖进自己的子树
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

      // 移动后塌缩（源容器可能只剩一个子窗口）
      sourceSection.rows = sourceSection.rows.map(normalizeRow)
      if (toSection !== sourceSection) toSection.rows = toSection.rows.map(normalizeRow)
    },

    /* ==================== 内容增删改 ==================== */

    /** 向指定窗口新增一个内容；index 不传就加在末尾（容器窗口会自动落到最后的叶子窗口） */
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

    /** 向指定窗口新增一个"空白内容"（指定类型） */
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

    /** 删除一个内容（自动在窗口里查找） */
    removeContent(sectionId: string, contentId: string) {
      const found = findContent(this.resume, contentId)
      if (!found) return
      found.row.contents.splice(found.index, 1)
      if (this.selectedId === contentId) this.selectedId = null
      this.collapsedContentIds = this.collapsedContentIds.filter((x) => x !== contentId)
    },

    /** 复制一个内容（插在原位置后面） */
    duplicateContent(sectionId: string, contentId: string) {
      const found = findContent(this.resume, contentId)
      if (!found) return
      const copy = JSON.parse(JSON.stringify(found.row.contents[found.index])) as Content
      copy.id = uid()
      found.row.contents.splice(found.index + 1, 0, copy)
      this.selectedId = copy.id
    },

    /**
     * 拖拽移动内容：从 fromSectionId 章节的 fromRowId 窗口，移到 toSectionId 章节的
     * toRowId 窗口的 toIndex 位置。同窗口内移动时，移除自己后目标位置自动回退一格。
     */
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

    /** 修改内容的内容、样式和紧贴开关（style 里 undefined 的字段 = 清除该字段，恢复继承） */
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

    /* ==================== 撤销 / 重做 ==================== */

    /**
     * 把"当前这份简历"深拷贝压入撤销栈，作为一步可撤销的快照。
     * 由 main.ts 的 $onAction 在每次改动前调用（结构操作每次一步；
     * 文字编辑按字段分组，同字段连续输入只在开头调一次）。
     * 出现新改动 = 旧的重做记录作废，清空 redoStack。
     */
    pushSnapshot() {
      this.undoStack.push(JSON.parse(JSON.stringify(this.resume)))
      if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift()
      this.redoStack = []
    },

    /** 撤销：弹回最近一步快照，当前状态压入重做栈（可重做） */
    undo() {
      const prev = this.undoStack.pop()
      if (!prev) return
      this.redoStack.push(JSON.parse(JSON.stringify(this.resume)))
      if (this.redoStack.length > MAX_HISTORY) this.redoStack.shift()
      this.resume.splice(0, this.resume.length, ...prev)
      this.selectedId = null
    },

    /** 重做：恢复被撤销的一步 */
    redo() {
      const next = this.redoStack.pop()
      if (!next) return
      this.undoStack.push(JSON.parse(JSON.stringify(this.resume)))
      if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift()
      this.resume.splice(0, this.resume.length, ...next)
      this.selectedId = null
    },

    /* ==================== 分页 ==================== */

    /** 写入分页方案（由 usePagination 测量后调用） */
    setPagination(plan: PagePlan, units: PageUnit[]) {
      this.pagePlan = plan
      this.pageUnits = units
    },
  },
})
