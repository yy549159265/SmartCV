import type { Content, ContentData, Section, LayoutWindow, ContentStyle, SectionLayout, SectionStyle } from '@/types'
import { uid } from '@/utils/id'
import { LIST_TEXT_ICON } from '@/data/icons'

export interface ContentPreset {
  id: string
  name: string
  desc: string
  icon: string
  type: Content['type']
  content: ContentData
  style?: ContentStyle
  fullRow?: boolean
  hidden?: boolean
}

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
    content: { tags: ['Vue 3', 'TypeScript', 'Vite'] },
  },
  {
    id: 'generic-content-list',
    name: '列表文字',
    desc: '圆点或数字列表，支持一键润色',
    icon: LIST_TEXT_ICON,
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
    id: 'preset-content-project-time',
    name: '项目时间段',
    desc: '分栏展示项目名称与起止时间',
    icon: '📁',
    type: 'twoColumn',
    content: { columns: ['**XX 项目**', '2023.03 - 2023.09'], separator: '|' },
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
]

export interface LayoutWindowPreset {
  layout: SectionLayout
  contents?: ContentPreset[]
  rows?: LayoutWindowPreset[]
}

export interface SectionPreset {
  id: string
  name: string
  desc: string
  icon: string
  title: string
  style?: SectionStyle
  rows?: LayoutWindowPreset[]
}

const contentById = (id: string): ContentPreset => {
  const found = CONTENT_PRESETS.find((p) => p.id === id)
  if (!found) throw new Error(`未找到内容预设：${id}`)
  return found
}

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

export interface RowPreset {
  id: string
  name: string
  desc: string
  icon: string
  layout: SectionLayout
  columns?: number
  rows?: number
}

export const GENERIC_ROW_PRESETS: RowPreset[] = [
  {
    id: 'preset-row-layout',
    name: '空白布局',
    desc: '空白的布局窗口，从零搭建页面结构',
    icon: '⬜',
    layout: 'vertical',
  },
]

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

function educationRow(suffix: string): LayoutWindowPreset {
  return {
    layout: 'horizontal',
    rows: [
      {
        layout: 'vertical',
        contents: [
          {
            id: `preset-content-school-${suffix}`,
            name: '学校',
            desc: '学校名称，可带标签',
            icon: '🎓',
            type: 'iconText',
            content: { icon: '', text: 'XX大学', tags: ['985', '211'] },
          },
        ],
      },
      {
        layout: 'vertical',
        contents: [
          {
            id: `preset-content-major-${suffix}`,
            name: '专业学历',
            desc: '专业与学历分栏展示',
            icon: '📘',
            type: 'twoColumn',
            content: { columns: ['计算机科学与技术 ', '硕士'], separator: '|' },
          },
        ],
      },
      {
        layout: 'vertical',
        contents: [
          {
            id: `preset-content-school-time-${suffix}`,
            name: '在校时间',
            desc: '展示在校起止时间',
            icon: '📅',
            type: 'timeRange',
            content: { start: '2026', end: '至今' },
          },
        ],
      },
    ],
  }
}

function workEntry(): LayoutWindowPreset {
  return {
    layout: 'vertical',
    contents: [
      {
        id: 'preset-content-work-time',
        name: '工作时间段',
        desc: '展示工作起止时间',
        icon: '📅',
        type: 'timeRange',
        content: { start: '2022.07', end: '至今' },
      },
      contentById('preset-content-duty'),
    ],
  }
}

function skillRow(key: string, title: string, items: string[]): LayoutWindowPreset {
  return {
    layout: 'vertical',
    contents: [
      {
        id: `preset-content-skill-title-${key}`,
        name: `${title}标题`,
        desc: '居中的技能分组标题',
        icon: '🛠️',
        type: 'iconText',
        content: { icon: '', text: title },
        style: { textAlign: 'center' },
      },
      {
        id: `preset-content-skill-list-${key}`,
        name: `${title}列表`,
        desc: '有序列表展示技能条目',
        icon: LIST_TEXT_ICON,
        type: 'listText',
        content: { listType: 'ordered', items: items.map((text) => ({ text, indent: 0 })) },
      },
    ],
  }
}

export const SECTION_PRESETS: SectionPreset[] = [
  {
    id: 'preset-section-intro',
    name: '个人简介',
    desc: '一行展示职位、电话、地址',
    icon: '👤',
    title: '个人简介',
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
    id: 'preset-section-education',
    name: '教育经历',
    desc: '每行展示学校、专业学历与在校时间',
    icon: '🎓',
    title: '教育经历',
    rows: [educationRow('1'), educationRow('2')],
  },
  {
    id: 'preset-section-work',
    name: '工作经历',
    desc: '公司名称 + 时间段与工作职责',
    icon: '💼',
    title: '工作经历',
    rows: [
      {
        layout: 'vertical',
        contents: [
          {
            id: 'preset-content-company',
            name: '公司名称',
            desc: '公司名称',
            icon: '🏢',
            type: 'iconText',
            content: { icon: '', text: 'XXX公司' },
          },
        ],
      },
      workEntry(),
      workEntry(),
    ],
  },
  {
    id: 'preset-section-project',
    name: '项目经历',
    desc: '分栏展示项目名称与时间，附项目职责',
    icon: '💻',
    title: '项目经历',
    rows: [
      {
        layout: 'vertical',
        contents: [contentById('preset-content-project-time'), contentById('preset-content-duty')],
      },
      {
        layout: 'vertical',
        contents: [contentById('preset-content-project-time'), contentById('preset-content-duty')],
      },
    ],
  },
  {
    id: 'preset-section-skill',
    name: '专业技能',
    desc: '工程技能与 LLM 技能两组',
    icon: '🛠️',
    title: '专业技能',
    rows: [
      skillRow('engineering', '工程技能', ['后端：', '前端：', '中间件：', '运维：']),
      skillRow('llm', 'LLM技能', ['框架', 'RAG', '记忆', '评测']),
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
        contents: [contentById('preset-content-award')],
      },
    ],
  },
]

function deepClone<T>(data: T): T {
  return JSON.parse(JSON.stringify(data)) as T
}

export function createContentFromPreset(preset: ContentPreset): Content {
  return {
    id: uid(),
    kind: 'content',
    type: preset.type,
    content: deepClone(preset.content),
    style: { ...(preset.style ?? {}) },
  }
}

function createWindowFromPreset(preset: LayoutWindowPreset): LayoutWindow {
  const window: LayoutWindow = {
    id: uid(),
    layout: preset.layout,
    contents: (preset.contents ?? []).map((p) => createContentFromPreset(p)),
  }
  if (preset.rows) {
    window.rows = preset.rows.map(createWindowFromPreset)
  }
  return window
}

export function createSectionFromPreset(preset: SectionPreset): Section {
  return {
    id: uid(),
    kind: 'section',
    title: preset.title,
    style: { ...(preset.style ?? {}) },
    rows: (preset.rows ?? []).map(createWindowFromPreset),
  }
}
