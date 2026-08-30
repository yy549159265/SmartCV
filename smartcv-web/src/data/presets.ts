/**
 * 预设模板配置 —— 组件库的内容全部来自这里
 *
 * 【重要】任务要求的核心概念：
 *   预设模板 = 「内容类型 + 默认内容 + 可选默认样式」的命名组合。
 *   例如"个人介绍"预设 = iconText 类型 + 一段默认文案，仅此而已。
 *   组件渲染时只认 content.type，从来不认预设名 —— 所以：
 *     ✅ 想新增/修改预设 → 只改这个文件，组件代码一行都不用动；
 *     ❌ 预设对象本身不是简历数据，拖进画布后会被"工厂函数"转成真正的内容实例。
 */
import type { Content, ContentData, Section, LayoutWindow, ContentStyle, SectionLayout, SectionStyle } from '@/types'
import { uid } from '@/utils/id'

/* ==================== 内容预设 ==================== */

/** 内容预设的结构 */
export interface ContentPreset {
  id: string
  /** 在组件库里显示的名字（组件代码里永远不会写死这些名字） */
  name: string
  /** 一句话说明，帮助使用者理解 */
  desc: string
  /** 组件库里的展示图标（emoji） */
  icon: string
  /** 该预设属于哪种通用类型 */
  type: Content['type']
  /** 默认内容 */
  content: ContentData
  /** 可选的默认样式 */
  style?: ContentStyle
  /** 可选：该预设默认是否"占整行"（见 types 里 Content.fullRow 的说明） */
  fullRow?: boolean
  /**
   * true = 不在组件库里展示（但仍可被章节预设组合引用）。
   */
  hidden?: boolean
}

/**
 * 【通用】内容 —— 与具体内容无关的 5 种原始形态。
 * 它们是"空白模板"：只带类型对应的占位内容，拖进章节后再自己填写。
 * （同样用预设结构承载，组件和拖拽逻辑零改动。）
 */
export const GENERIC_CONTENT_PRESETS: ContentPreset[] = [
  {
    id: 'generic-content-icontext',
    name: '图标文字',
    desc: '图标加文字，图标留空则只显示文字',
    icon: '🅰️',
    type: 'iconText',
    content: { icon: '', text: '' },
  },
  {
    id: 'generic-content-twocol',
    name: '分栏',
    desc: '多栏内容，栏数可增减，分隔符可改',
    icon: '↔️',
    type: 'twoColumn',
    content: { columns: ['', ''], separator: '|' },
  },
  {
    id: 'generic-content-timerange',
    name: '时间段',
    desc: '展示一段起止时间',
    icon: '⏱️',
    type: 'timeRange',
    content: { start: '', end: '' },
  },
  {
    id: 'generic-content-tag',
    name: '标签',
    desc: '展示一排标签',
    icon: '🏷️',
    type: 'tag',
    content: { tags: ['新标签'] },
  },
  {
    id: 'generic-content-list',
    name: '列表文字',
    desc: '圆点或数字列表，支持一键润色',
    icon: '☰',
    type: 'listText',
    content: { listType: 'bullet', items: [{ text: '' }] },
  },
  {
    id: 'generic-content-image',
    name: '图片',
    desc: '上传并展示一张图片',
    icon: '🖼️',
    type: 'image',
    content: { image: '', imageSize: 96, imageShape: 'rounded' },
  },
  {
    id: 'generic-content-spacer',
    name: '占位组件',
    desc: '空白占位，调正文字号可控制高度',
    icon: '🫥',
    type: 'spacer',
    content: {},
  },
]

/**
 * 【预设】内容 —— 「类型 + 默认内容」的命名组合。
 * 如"联系电话"预设的本质 = iconText 类型 + 一个默认号码。
 * 组件渲染时只认 content.type，从来不认预设名。
 */
export const CONTENT_PRESETS: ContentPreset[] = [
  {
    id: 'preset-content-phone',
    name: '联系电话',
    desc: '展示电话号码',
    icon: '📞',
    type: 'iconText',
    content: { icon: '📞', text: '138-0000-0000' },
  },
  {
    id: 'preset-content-email',
    name: '电子邮箱',
    desc: '展示邮箱地址',
    icon: '✉️',
    type: 'iconText',
    content: { icon: '✉️', text: 'zhangsan@example.com' },
  },
  {
    id: 'preset-content-location',
    name: '所在城市',
    desc: '展示所在城市',
    icon: '📍',
    type: 'iconText',
    content: { icon: '📍', text: '上海 · 浦东' },
  },
  {
    id: 'preset-content-education',
    name: '教育经历',
    desc: '分栏展示学校与专业学历',
    icon: '🎓',
    type: 'twoColumn',
    content: { columns: ['**XX 大学**', '计算机科学与技术 · 本科'], separator: '|' },
  },
  {
    id: 'preset-content-job-time',
    name: '工作时间段',
    desc: '展示工作起止时间',
    icon: '📅',
    type: 'timeRange',
    content: { start: '2022.07', end: '至今' },
  },
  {
    id: 'preset-content-duty',
    name: '工作职责',
    desc: '圆点列表，支持一键润色',
    icon: '📋',
    type: 'listText',
    content: {
      listType: 'bullet',
      items: [
        { text: '负责 XX 项目的**前端架构设计**与开发' },
        { text: '优化页面性能，首屏时间降低 40%' },
      ],
    },
  },
  {
    id: 'preset-content-skills',
    name: '技能标签',
    desc: '展示一排技能标签',
    icon: '🏷️',
    type: 'tag',
    content: { tags: ['Vue 3', 'TypeScript', 'Vite'] },
  },
  {
    id: 'preset-content-award',
    name: '荣誉奖项',
    desc: '数字列表展示荣誉奖项',
    icon: '🏆',
    type: 'listText',
    content: {
      listType: 'ordered',
      items: [{ text: '2023 年公司年度**最佳新人**' }, { text: '校级优秀毕业生' }],
    },
  },
  {
    id: 'preset-content-avatar',
    name: '头像',
    desc: '上传照片，常放在简历顶部',
    icon: '🧑',
    type: 'image',
    content: { image: '', imageSize: 96, imageShape: 'rounded' },
  },
]

/* ==================== 章节预设 ==================== */

/** 布局窗口预设：一个窗口 = 布局方向 + 若干内容预设 */
export interface LayoutWindowPreset {
  /** 该窗口内内容的排列方式 */
  layout: SectionLayout
  /** 窗口自带的内容预设 */
  contents?: ContentPreset[]
}

/** 章节预设的结构 */
export interface SectionPreset {
  id: string
  name: string
  desc: string
  icon: string
  /** 章节默认标题 */
  title: string
  /** 可选默认样式 */
  style?: SectionStyle
  /** 可选：章节自带的布局窗口（一个章节可以放多个窗口，每个独立选横/竖） */
  rows?: LayoutWindowPreset[]
}

/** 小工具：按 id 找内容预设（避免用数组下标引用，防止改顺序时弄错） */
const contentById = (id: string): ContentPreset => {
  const found = CONTENT_PRESETS.find((p) => p.id === id)
  if (!found) throw new Error(`未找到内容预设：${id}`)
  return found
}

/**
 * 【通用】章节—— 空白章节。
 */
export const GENERIC_SECTION_PRESETS: SectionPreset[] = [
  {
    id: 'preset-section-blank',
    name: '空白章节',
    desc: '空白的章节，可自由填充内容',
    icon: '⬜',
    title: '新章节',
    rows: [],
  },
]

/**
 * 【通用】布局 —— 窗口布局（直接拖进章节，章节里用 ＋上/下/左/右 或拖拽排列；
 * 左/右并排会自动形成横排，不需要单独的"容器"）。
 * 结构预设（columns / rows）= 横排/竖排 + N 个空白子窗口（2列 / 3列 / 2行 / 3行）。
 */
export interface RowPreset {
  id: string
  name: string
  desc: string
  icon: string
  /** 单个窗口时的默认方向 */
  layout: SectionLayout
  /** 可选：横向容器 + N 个子窗口（如 2 列 / 3 列） */
  columns?: number
  /** 可选：竖向容器 + N 个子窗口（如 2 行 / 3 行） */
  rows?: number
}

/** 通用布局：窗口布局 */
export const GENERIC_ROW_PRESETS: RowPreset[] = [
  {
    id: 'preset-row-layout',
    name: '窗口布局',
    desc: '拖入章节后，内容可在窗口内自由排列',
    icon: '🧩',
    layout: 'vertical',
  },
]

/** 预设布局：2列 / 3列 / 2行 / 3行 */
export const ROW_PRESETS: RowPreset[] = [
  {
    id: 'preset-row-2col',
    name: '2列',
    desc: '横向并排两个窗口',
    icon: '⫿',
    layout: 'horizontal',
    columns: 2,
  },
  {
    id: 'preset-row-3col',
    name: '3列',
    desc: '横向并排三个窗口',
    icon: '⫿',
    layout: 'horizontal',
    columns: 3,
  },
  {
    id: 'preset-row-2row',
    name: '2行',
    desc: '竖向堆叠两个窗口',
    icon: '≡',
    layout: 'vertical',
    rows: 2,
  },
  {
    id: 'preset-row-3row',
    name: '3行',
    desc: '竖向堆叠三个窗口',
    icon: '≡',
    layout: 'vertical',
    rows: 3,
  },
]

/** 由布局预设生成真正的布局窗口（结构预设 = 横排/竖排容器 + N 个空白子窗口） */
export function createRowFromPreset(preset: RowPreset): LayoutWindow {
  const makeLeaf = (): LayoutWindow => ({ id: uid(), layout: 'vertical', contents: [] })
  if (preset.columns) {
    return {
      id: uid(),
      layout: 'horizontal',
      contents: [],
      rows: Array.from({ length: preset.columns }, makeLeaf),
    }
  }
  if (preset.rows) {
    return {
      id: uid(),
      layout: 'vertical',
      contents: [],
      rows: Array.from({ length: preset.rows }, makeLeaf),
    }
  }
  return { id: uid(), layout: preset.layout, contents: [] }
}

/**
 * 【预设】章节 —— 带默认标题与布局窗口的章节。
 * 一个章节预设可以组合多个布局窗口，例如"工作经历章节" =
 * 两个竖向窗口（每个窗口 = 时间段 + 职责列表）。
 */
export const SECTION_PRESETS: SectionPreset[] = [
  {
    id: 'preset-section-intro',
    name: '个人介绍',
    desc: '一行展示职位、电话、地址',
    icon: '👤',
    title: '个人介绍',
    rows: [
      {
        layout: 'horizontal',
        contents: [
          {
            id: 'preset-content-job-title',
            name: '职位头衔',
            desc: '图标 + 职位',
            icon: '👔',
            type: 'iconText',
            content: { icon: '👔', text: '**前端工程师**' },
          },
          contentById('preset-content-phone'),
          contentById('preset-content-location'),
        ],
      },
    ],
  },
  {
    id: 'preset-section-contact',
    name: '联系方式',
    desc: '一行展示电话、邮箱、城市',
    icon: '📞',
    title: '联系方式',
    rows: [
      {
        layout: 'horizontal',
        contents: [contentById('preset-content-phone'), contentById('preset-content-email'), contentById('preset-content-location')],
      },
    ],
  },
  {
    id: 'preset-section-education',
    name: '教育经历',
    desc: '分栏展示多条教育经历',
    icon: '🎓',
    title: '教育经历',
    rows: [
      {
        layout: 'vertical',
        contents: [contentById('preset-content-education'), contentById('preset-content-education')],
      },
    ],
  },
  {
    id: 'preset-section-work',
    name: '工作经历',
    desc: '两个竖向窗口：时间段 + 工作职责',
    icon: '💼',
    title: '工作经历',
    rows: [
      {
        layout: 'vertical',
        contents: [contentById('preset-content-job-time'), contentById('preset-content-duty')],
      },
      {
        layout: 'vertical',
        contents: [contentById('preset-content-job-time'), contentById('preset-content-duty')],
      },
    ],
  },
  {
    id: 'preset-section-skill',
    name: '技能标签',
    desc: '横向排列的技能标签',
    icon: '🏷️',
    title: '专业技能',
    rows: [
      {
        layout: 'horizontal',
        contents: [contentById('preset-content-skills'), contentById('preset-content-skills'), contentById('preset-content-skills')],
      },
    ],
  },
  {
    id: 'preset-section-award',
    name: '荣誉奖项',
    desc: '数字列表的荣誉奖项',
    icon: '🏆',
    title: '荣誉奖项',
    rows: [
      {
        layout: 'vertical',
        contents: [contentById('preset-content-award'), contentById('preset-content-award')],
      },
    ],
  },
]

/* ==================== 类型判断与工厂函数 ==================== */

/** 深拷贝：预设内容都是纯 JSON 数据（字符串/数字/数组），直接序列化拷贝最省心 */
function deepClone<T>(data: T): T {
  return JSON.parse(JSON.stringify(data)) as T
}

/**
 * 工厂函数：由内容预设生成一个"真正的内容实例"。
 * 每次拖入都生成全新对象（新 id + 拷贝的默认内容），互不影响。
 */
export function createContentFromPreset(preset: ContentPreset): Content {
  return {
    id: uid(),
    kind: 'content',
    type: preset.type,
    content: deepClone(preset.content),
    style: { ...(preset.style ?? {}) },
  }
}

/**
 * 工厂函数：由章节预设生成一个"真正的章节实例"。
 * 如果预设自带布局窗口（rows），也一并生成（每个窗口 = 新 id + 拷贝的内容）。
 */
export function createSectionFromPreset(preset: SectionPreset): Section {
  return {
    id: uid(),
    kind: 'section',
    title: preset.title,
    style: { ...(preset.style ?? {}) },
    rows: (preset.rows ?? []).map((row) => ({
      id: uid(),
      layout: row.layout,
      contents: (row.contents ?? []).map((p) => createContentFromPreset(p)),
    })),
  }
}
