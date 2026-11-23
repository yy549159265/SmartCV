/** 策略总结：定位 / 能力差距 / 改进优先级 / 简历优化建议 / 求职风险的字段口径与读取。 */

export type StrategySectionKey = 'gaps' | 'priorities' | 'writing' | 'risks'

export interface StrategyFieldDef {
  name: string
  label: string
  kind: 'text' | 'list'
}

export interface StrategySectionDef {
  key: StrategySectionKey
  label: string
  fields: StrategyFieldDef[]
}

export const STRATEGY_SECTIONS: StrategySectionDef[] = [
  {
    key: 'gaps',
    label: '能力差距',
    fields: [
      { name: 'current_level', label: '简历现状', kind: 'text' },
      { name: 'gap_analysis', label: '差距分析', kind: 'text' },
      { name: 'improvement_direction', label: '提升方向', kind: 'text' },
      { name: 'resume_locations', label: '简历位置', kind: 'list' },
    ],
  },
  {
    key: 'priorities',
    label: '改进优先级',
    fields: [
      { name: 'reason', label: '优先原因', kind: 'text' },
      { name: 'expected_outcome', label: '预期结果', kind: 'text' },
      { name: 'related_gaps', label: '关联差距', kind: 'list' },
    ],
  },
  {
    key: 'writing',
    label: '简历优化建议',
    fields: [
      { name: 'problem', label: '当前问题', kind: 'text' },
      { name: 'optimization', label: '优化方案', kind: 'text' },
      { name: 'reference_requirement', label: '对应要求', kind: 'text' },
      { name: 'suggested_keywords', label: '建议关键词', kind: 'list' },
    ],
  },
  {
    key: 'risks',
    label: '求职风险',
    fields: [
      { name: 'impact', label: '潜在影响', kind: 'text' },
      { name: 'response', label: '应对策略', kind: 'text' },
    ],
  },
]

export const STRATEGY_SECTION_KEYS = STRATEGY_SECTIONS.map((section) => section.key)

/** 定位块的展示字段；空值直接跳过。 */
const POSITIONING_FIELDS: StrategyFieldDef[] = [
  { name: 'career_positioning', label: '职业定位', kind: 'text' },
  { name: 'market_level', label: '市场竞争力', kind: 'text' },
  { name: 'job_match', label: '岗位匹配度', kind: 'text' },
  { name: 'competitive_advantages', label: '核心优势', kind: 'list' },
  { name: 'competitive_disadvantages', label: '主要劣势', kind: 'list' },
]

const PRIORITY_LABEL: Record<string, string> = {
  high: '高优先级',
  medium: '中优先级',
  low: '低优先级',
}

export interface StrategyTextBlock {
  key: string
  label: string
  kind: 'text' | 'list'
  texts: string[]
}

export interface StrategyPositioningView {
  blocks: StrategyTextBlock[]
  notes: string
  /** 定位块里的文字条目数，不把备注算进去。 */
  count: number
}

export interface StrategyItemView {
  key: string
  title: string
  badge: string
  tone: 'high' | 'medium' | 'low' | 'tag'
  fields: StrategyTextBlock[]
  evidence: string[]
}

export interface StrategySectionView {
  items: StrategyItemView[]
  count: number
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
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

function readFields(source: Record<string, unknown>, fields: StrategyFieldDef[]): StrategyTextBlock[] {
  const blocks: StrategyTextBlock[] = []
  for (const field of fields) {
    const raw = source[field.name]
    const texts = field.kind === 'list' ? stringList(raw) : [textOf(raw)].filter(Boolean)
    if (texts.length) {
      blocks.push({ key: field.name, label: field.label, kind: field.kind, texts })
    }
  }
  return blocks
}

/** 概览块：竞争力定位 + 备注，用于汇总卡与定位页签。 */
export function readStrategyPositioning(data?: Record<string, unknown>): StrategyPositioningView {
  const source = recordOf(data?.positioning)
  const blocks = readFields(source, POSITIONING_FIELDS)
  return {
    blocks,
    notes: textOf(data?.notes),
    count: blocks.reduce((sum, block) => sum + block.texts.length, 0),
  }
}

/** 读取一个列表块；每个条目只保留有内容的字段。 */
export function readStrategySection(
  key: string,
  data?: Record<string, unknown>,
): StrategySectionView {
  const def = STRATEGY_SECTIONS.find((section) => section.key === key)
  const rawItems = Array.isArray(data?.items) ? (data?.items as unknown[]) : []
  const items: StrategyItemView[] = []

  rawItems.forEach((raw, index) => {
    const source = recordOf(raw)
    const fields = def ? readFields(source, def.fields) : []
    let title = ''
    let badge = ''
    let tone: StrategyItemView['tone'] = 'tag'

    if (key === 'gaps') {
      title = textOf(source.requirement)
      const priority = textOf(source.priority)
      badge = PRIORITY_LABEL[priority] || ''
      tone = priority === 'high' || priority === 'medium' || priority === 'low' ? priority : 'tag'
    } else if (key === 'priorities') {
      title = textOf(source.task)
      const rank = Number(source.rank || 0)
      badge = rank > 0 ? `优先级 ${rank}` : `优先级 ${index + 1}`
    } else if (key === 'writing') {
      title = textOf(source.resume_location)
    } else if (key === 'risks') {
      title = textOf(source.risk) || textOf(source.risk_type)
      badge = textOf(source.risk_type)
    }

    if (!title && !fields.length) return
    if (!title) title = def ? def.label : '策略建议'
    items.push({
      key: `${key}:${index}`,
      title,
      badge,
      tone,
      fields,
      evidence: stringList(source.evidence_ids),
    })
  })

  return { items, count: items.length }
}
