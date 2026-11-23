/** 动态方面：八个内容块的字段口径、读取与空值判断。 */

export type AspectSectionKey =
  | 'basic'
  | 'core'
  | 'directions'
  | 'performance'
  | 'advantages'
  | 'problems'
  | 'trends'
  | 'conclusion'

export interface AspectFieldDef {
  name: string
  label: string
  kind: 'text' | 'list'
}

export interface AspectSectionDef {
  key: AspectSectionKey
  label: string
  fields: AspectFieldDef[]
}

/** 页签顺序与后台 `_SECTIONS` 一致；只展示有内容的块。 */
export const ASPECT_SECTIONS: AspectSectionDef[] = [
  {
    key: 'basic',
    label: '基本情况',
    fields: [
      { name: 'background', label: '背景', kind: 'text' },
      { name: 'scope', label: '范围', kind: 'text' },
      { name: 'key_data', label: '关键数据', kind: 'list' },
    ],
  },
  {
    key: 'core',
    label: '核心内容',
    fields: [{ name: 'main_contents', label: '主要内容', kind: 'list' }],
  },
  {
    key: 'directions',
    label: '重点方向',
    fields: [{ name: 'directions', label: '重点方向', kind: 'list' }],
  },
  {
    key: 'performance',
    label: '具体表现',
    fields: [
      { name: 'performance_metrics', label: '具体指标', kind: 'list' },
      { name: 'typical_cases', label: '典型案例', kind: 'list' },
    ],
  },
  {
    key: 'advantages',
    label: '优势与特点',
    fields: [{ name: 'key_advantages', label: '主要优势', kind: 'list' }],
  },
  {
    key: 'problems',
    label: '存在问题',
    fields: [
      { name: 'key_problems', label: '主要问题', kind: 'list' },
      { name: 'risk_points', label: '潜在风险', kind: 'list' },
    ],
  },
  {
    key: 'trends',
    label: '发展趋势',
    fields: [
      { name: 'current_changes', label: '当前变化', kind: 'list' },
      { name: 'future_directions', label: '未来方向', kind: 'list' },
    ],
  },
  {
    key: 'conclusion',
    label: '综合分析',
    fields: [{ name: 'key_conclusions', label: '关键结论', kind: 'list' }],
  },
]

export const ASPECT_SECTION_KEYS = ASPECT_SECTIONS.map((section) => section.key)

export function isAspectSectionKey(value: string): value is AspectSectionKey {
  return ASPECT_SECTION_KEYS.includes(value as AspectSectionKey)
}

export interface AspectBlock {
  key: string
  label: string
  kind: 'text' | 'list'
  texts: string[]
}

export interface AspectSectionView {
  summary: string
  evidence: string[]
  blocks: AspectBlock[]
  /** 列表条目数。 */
  count: number
  /** 列表条目 + 汇总句，用于页签计数。 */
  total: number
  /** 多个字段时显示字段小标题；单字段块的页签名已经说明了内容。 */
  showLabels: boolean
}

export interface AspectOverviewView {
  scope: string
  summary: string
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const list: string[] = []
  for (const item of value) {
    const text = textOf(item)
    if (text && !list.includes(text)) list.push(text)
  }
  return list
}

/** 读取一个内容块；空字段直接跳过，前端不再判空。 */
export function readAspectSection(
  key: string,
  data?: Record<string, unknown>,
): AspectSectionView {
  const source = data || {}
  const def = ASPECT_SECTIONS.find((section) => section.key === key)
  const blocks: AspectBlock[] = []
  for (const field of def?.fields || []) {
    const raw = source[field.name]
    const texts = field.kind === 'list' ? stringList(raw) : [textOf(raw)].filter(Boolean)
    if (texts.length) {
      blocks.push({ key: field.name, label: field.label, kind: field.kind, texts })
    }
  }
  const summary = textOf(source.summary)
  const count = blocks.reduce((sum, block) => sum + block.texts.length, 0)
  return {
    summary,
    evidence: stringList(source.evidence_ids),
    blocks,
    count,
    total: count + (summary ? 1 : 0),
    showLabels: (def?.fields.length || 0) > 1,
  }
}

/** 概览块：用于类别汇总卡，不单独占一个页签。 */
export function readAspectOverview(data?: Record<string, unknown>): AspectOverviewView {
  const raw = data?.overview
  const overview =
    raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {}
  return {
    scope: textOf(overview.research_scope),
    summary: textOf(overview.research_summary),
  }
}
