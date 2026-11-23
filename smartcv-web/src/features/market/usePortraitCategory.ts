/** 简历画像：汇总卡展示自述 / 年限与技能等级，明细按后端章节分组。 */

import { computed, ref, watch } from 'vue'
import type { PanelRow, PortraitBlock, PortraitSection } from '@/types/market'
import {
  emptySummary,
  type CategoryCard,
  type CategoryModule,
  type CategoryRunSnapshot,
  type GapView,
  type ProjectView,
  type SkillView,
} from './types'

export type PortraitView = 'career' | 'skills' | 'hits' | 'gaps'

/** 技能画像展示的章节；项目画像与两类缺口在 visibleSections 里单独处理。 */
const SECTION_KEYS: Record<'skills', string[]> = {
  skills: ['profile:section:technical'],
}

/** 页签名；明细里出现同名标题时不再重复显示。 */
const TAB_LABELS: Record<PortraitView, string> = {
  career: '职业画像',
  skills: '技能画像',
  hits: '项目画像',
  gaps: '缺口画像',
}

const LEVEL_ORDER: Record<string, number> = { 精通: 0, 熟练: 1, 熟悉: 2, 了解: 3, 提及: 4 }

/** 缺口先按类型分组，再按严重程度排序；顺序与后端枚举一致。 */
const GAP_TYPE_ORDER: Record<string, number> = {
  技能缺口: 0,
  经验缺口: 1,
  深度不足: 2,
  证据不足: 3,
}
const SEVERITY_ORDER: Record<string, number> = { 严重: 0, 中等: 1, 轻微: 2 }
const WEAKNESS_TYPE_ORDER: Record<string, number> = {
  成果表达: 0,
  项目描述: 1,
  职责边界: 2,
  技术描述: 3,
  结构重点: 4,
}

/** 旧快照可能直接存了模型枚举，统一转成中文；中文值原样保留。 */
const GAP_TYPE_LABEL: Record<string, string> = {
  skill: '技能缺口',
  experience: '经验缺口',
  depth: '深度不足',
  evidence: '证据不足',
  技能缺口: '技能缺口',
  经验缺口: '经验缺口',
  深度不足: '深度不足',
  证据不足: '证据不足',
}
const SEVERITY_LABEL: Record<string, string> = {
  high: '严重',
  medium: '中等',
  low: '轻微',
  严重: '严重',
  中等: '中等',
  轻微: '轻微',
}
const WEAKNESS_TYPE_LABEL: Record<string, string> = {
  result_expression: '成果表达',
  project_description: '项目描述',
  responsibility: '职责边界',
  technical_depth: '技术描述',
  structure: '结构重点',
  成果表达: '成果表达',
  项目描述: '项目描述',
  职责边界: '职责边界',
  技术描述: '技术描述',
  结构重点: '结构重点',
}

/** 旧行的正文末尾可能残留「（枚举 · 枚举）」，拆成标题上的两个中文徽标。 */
function normalizeGapRow(row: PanelRow): PanelRow {
  const rawLabel = row.label || ''
  // 只有英文枚举才从标题推断类型；中文缺口名可能恰好叫「深度不足」，不能当成枚举。
  const labelType = /^[a-z_]+$/.test(rawLabel) ? GAP_TYPE_LABEL[rawLabel] || '' : ''
  let typeLabel = GAP_TYPE_LABEL[row.type_label || ''] || row.type_label || labelType
  let severityLabel = SEVERITY_LABEL[row.severity_label || ''] || row.severity_label || ''
  let text = row.text || ''
  const suffix = text.match(/（([^（）]+)）\s*$/)
  if (suffix && suffix.index !== undefined) {
    const [rawType = '', rawSeverity = ''] = suffix[1].split('·').map((part) => part.trim())
    const mappedType = GAP_TYPE_LABEL[rawType] || ''
    const mappedSeverity = SEVERITY_LABEL[rawSeverity] || ''
    if (mappedType || mappedSeverity) {
      if (!typeLabel) typeLabel = mappedType
      if (!severityLabel) severityLabel = mappedSeverity
      text = text.slice(0, suffix.index).trim()
    }
  }
  // 行标题本身就是枚举时换成中文，避免把 depth / evidence 直接暴露给用户。
  return {
    ...row,
    label: labelType || rawLabel,
    text,
    type_label: typeLabel || undefined,
    severity_label: severityLabel || undefined,
  }
}

/** 简历缺口没有独立名称，直接把类型名当标题；兼容旧行统一写的「简历表达」。 */
function normalizeWeaknessRow(row: PanelRow): PanelRow {
  const rawLabel = row.label || ''
  const mapped =
    WEAKNESS_TYPE_LABEL[row.type_label || ''] ||
    row.type_label ||
    WEAKNESS_TYPE_LABEL[rawLabel] ||
    ''
  return {
    ...row,
    label: mapped || rawLabel,
    type_label: mapped || undefined,
  }
}

function sortGapRows(list: PanelRow[]): PanelRow[] {
  // 旧行没有 type_label 时，标题本身可能就是中文类型名，排序仍按它归类。
  const typeOf = (row: PanelRow) => {
    if (row.type_label) return row.type_label
    return GAP_TYPE_ORDER[row.label || ''] !== undefined ? row.label || '' : ''
  }
  return [...list].sort((a, b) => {
    const byType = (GAP_TYPE_ORDER[typeOf(a)] ?? 99) - (GAP_TYPE_ORDER[typeOf(b)] ?? 99)
    if (byType) return byType
    return (
      (SEVERITY_ORDER[a.severity_label || ''] ?? 99) -
      (SEVERITY_ORDER[b.severity_label || ''] ?? 99)
    )
  })
}

function sortWeaknessRows(list: PanelRow[]): PanelRow[] {
  return [...list].sort((a, b) => {
    const aType = a.type_label || a.label || ''
    const bType = b.type_label || b.label || ''
    return (WEAKNESS_TYPE_ORDER[aType] ?? 99) - (WEAKNESS_TYPE_ORDER[bType] ?? 99)
  })
}

export function usePortraitCategory(options: { rows: () => PanelRow[] }) {
  const { rows } = options
  const view = ref<PortraitView>('career')
  /** 技能画像内部再分「技能总结 / 技能图谱」，默认先看图谱。 */
  const skillView = ref<SkillView>('map')
  /** 项目画像内部再分「项目总结 / 项目价值」，默认先看价值明细。 */
  const projectView = ref<ProjectView>('value')
  /** 缺口画像内部再分「能力缺口 / 简历缺口」，默认先看能力缺口。 */
  const gapView = ref<GapView>('capability')

  const summaryRow = computed(() => rows().find((row) => row.tone === 'summary') || null)
  /** 职业定位 / 级别 / 标签 / 路径：合成「职业画像」页签的内容。 */
  const metaRows = computed(() =>
    rows().filter((row) => row.tone === 'meta' && row.key.startsWith('profile:career:')),
  )
  /** 技能按熟练度从高到低排序，同级保持模型给出的顺序。 */
  const skills = computed(() =>
    rows()
      .filter((row) => row.tone === 'skill')
      .sort((a, b) => (LEVEL_ORDER[a.value || ''] ?? 4) - (LEVEL_ORDER[b.value || ''] ?? 4)),
  )
  /**
   * 画像明细按后端 divider 分组：
   * - `profile:section:*` 开启一个章节标题（技能 / 项目 / 竞争优势 / 能力缺口 / 简历缺口）；
   * - `profile:group:*` 在章节内开启能力分组，只有技能行归入分组；
   * - 首个标题之前的职业竞争力行归「职业画像」页签，不重复进章节明细。
   */
  const sections = computed<PortraitSection[]>(() => {
    const list: PortraitSection[] = []
    let section: PortraitSection | null = null

    const sectionBlock = (target: PortraitSection): PortraitBlock => {
      let block = target.blocks.find((item) => item.key === `${target.key}:rows`)
      if (!block) {
        block = { key: `${target.key}:rows`, label: '', rows: [] }
        target.blocks.push(block)
      }
      return block
    }

    for (const row of rows()) {
      if (row.kind === 'divider') {
        if (row.key.startsWith('profile:group:') && section) {
          section.blocks.push({ key: row.key, label: row.label || '', rows: [] })
        } else {
          section = { key: row.key, label: row.label || '', count: 0, blocks: [] }
          list.push(section)
        }
        continue
      }
      if (!section) continue
      // 技能行的 key 带分组序号，直接对到 group divider，避免空分组串行。
      const skillGroup = row.key.startsWith('profile:skill:')
        ? section.blocks.find((block) => block.key === `profile:group:${row.key.split(':')[2]}`)
        : undefined
      const target = skillGroup || sectionBlock(section)
      target.rows.push(row)
      section.count += 1
    }

    return list
      .map((item) => {
        const filled = item.blocks.filter((block) => block.rows.length > 0)
        const rowsBlock = filled.find((block) => block.key === `${item.key}:rows`)
        return {
          ...item,
          blocks: rowsBlock ? [...filled.filter((block) => block !== rowsBlock), rowsBlock] : filled,
        }
      })
      .filter((item) => item.count > 0)
  })

  /** 能力缺口 / 简历缺口按行 key 判断，兼容旧快照合并在一个章节里的情况。 */
  const hasGapRows = computed(() =>
    rows().some((row) => row.kind !== 'divider' && row.key.startsWith('profile:gap:')),
  )
  const hasWeaknessRows = computed(() =>
    rows().some((row) => row.kind !== 'divider' && row.key.startsWith('profile:weakness:')),
  )

  /** 横向页签：职业画像在最前，其余按明细章节是否生成来决定显隐。 */
  const modules = computed<CategoryModule[]>(() => {
    const list: CategoryModule[] = []
    const hasSection = (key: string) => sections.value.some((section) => section.key === key)
    if (metaRows.value.length)
      list.push({ key: 'career', label: '职业画像', tabLabel: '职业画像', meta: '', rows: [] })
    if (hasSection('profile:section:technical'))
      list.push({ key: 'skills', label: '技能画像', tabLabel: '技能画像', meta: '', rows: [] })
    if (hasSection('profile:section:project') || hasSection('profile:section:advantage'))
      list.push({ key: 'hits', label: '项目画像', tabLabel: '项目画像', meta: '', rows: [] })
    if (hasGapRows.value || hasWeaknessRows.value)
      list.push({ key: 'gaps', label: '缺口画像', tabLabel: '缺口画像', meta: '', rows: [] })
    return list
  })

  // 画像模块是分批到达的：当前页签还没生成时先停在第一个可用页签。
  watch(modules, (list) => {
    if (!list.length) return
    if (!list.some((module) => module.key === view.value)) {
      view.value = list[0].key as PortraitView
    }
  })

  /** 项目画像按「项目总结 / 项目价值」切换，两个视图都来自同一项目章节。 */
  const visibleSections = computed<PortraitSection[]>(() => {
    const current = view.value
    if (current === 'career') {
      if (!metaRows.value.length) return []
      return [
        {
          key: 'profile:section:career',
          // 页签已经写着「职业画像」，明细里不再重复一次标题。
          label: '',
          count: metaRows.value.length,
          blocks: [
            {
              key: 'profile:section:career:rows',
              label: '',
              rows: metaRows.value,
            },
          ],
        },
      ]
    }
    // 项目画像只展示项目章节；没有项目章节时退回竞争优势，避免整块空白。
    if (current === 'hits') {
      const chosen =
        sections.value.find((section) => section.key === 'profile:section:project') ||
        sections.value.find((section) => section.key === 'profile:section:advantage')
      return chosen ? [{ ...chosen, label: '' }] : []
    }
    // 缺口画像一个页签、两个子视图：旧快照合并在 profile:section:potential，
    // 这里统一按行 key 拆成两个块，由 PortraitPane 按 gapView 选择展示。
    if (current === 'gaps') {
      const gaps = sortGapRows(
        rows()
          .filter((row) => row.kind !== 'divider' && row.key.startsWith('profile:gap:'))
          .map(normalizeGapRow),
      )
      const weaknesses = sortWeaknessRows(
        rows()
          .filter((row) => row.kind !== 'divider' && row.key.startsWith('profile:weakness:'))
          .map(normalizeWeaknessRow),
      )
      return [
        {
          key: 'profile:section:gaps',
          label: '',
          count: gaps.length + weaknesses.length,
          blocks: [
            { key: 'profile:section:gaps:capability', label: '', rows: gaps },
            { key: 'profile:section:gaps:resume', label: '', rows: weaknesses },
          ],
        },
      ]
    }
    const keys = SECTION_KEYS[current]
    const tabLabel = TAB_LABELS[current]
    return sections.value
      .filter((section) => keys.includes(section.key))
      .map((section) => (section.label === tabLabel ? { ...section, label: '' } : section))
  })

  /** 画像卡只展示个人简介；技能等级分布在「技能画像」页签里看。 */
  const summary = computed(() => {
    const card = emptySummary('portrait')
    card.text =
      summaryRow.value?.text || '简历画像完成后，这里会显示从简历原文提炼的一段自述。'
    return card
  })

  const card = computed<CategoryCard>(() => ({
    key: 'portrait',
    icon: 'user-round',
    title: '简历画像',
    subtitle: '来自简历原文的对照结果',
    status: `${skills.value.length} 项技能`,
    note: '',
    summary: summary.value,
  }))

  const hasRows = computed(() => rows().length > 0)
  const emptyText = '等待简历画像 · 这里会对照你的简历'

  function setModuleKey(key: string) {
    view.value = key as PortraitView
  }

  function setSkillView(value: SkillView) {
    skillView.value = value
  }

  function setProjectView(value: ProjectView) {
    projectView.value = value
  }

  function setGapView(value: GapView) {
    gapView.value = value
  }

  function reset() {
    view.value = 'career'
    skillView.value = 'map'
    projectView.value = 'value'
    gapView.value = 'capability'
  }

  function snapshot() {
    return {
      portraitView: view.value,
      portraitSkillView: skillView.value,
      portraitProjectView: projectView.value,
      portraitGapView: gapView.value,
    }
  }

  function restore(run: CategoryRunSnapshot) {
    const saved = String(run.portraitView || '')
    const views: PortraitView[] = ['career', 'skills', 'hits', 'gaps']
    view.value = views.includes(saved as PortraitView) ? (saved as PortraitView) : 'career'
    skillView.value = run.portraitSkillView === 'summary' ? 'summary' : 'map'
    projectView.value = run.portraitProjectView === 'summary' ? 'summary' : 'value'
    gapView.value = run.portraitGapView === 'resume' ? 'resume' : 'capability'
  }

  return {
    view,
    modules,
    activeModuleKey: view,
    skillView,
    setSkillView,
    projectView,
    setProjectView,
    gapView,
    setGapView,
    summaryRow,
    metaRows,
    skills,
    sections: visibleSections,
    card,
    hasRows,
    emptyText,
    setModuleKey,
    reset,
    snapshot,
    restore,
  }
}
