/** 策略总结：竞争力定位 / 能力差距 / 改进优先级 / 简历优化建议 / 求职风险。 */

import { computed, ref } from 'vue'
import type { PanelRow, PaneModule } from '@/types/market'
import { toCategoryModules } from './dims'
import {
  STRATEGY_SECTIONS,
  STRATEGY_SECTION_KEYS,
  readStrategyPositioning,
  readStrategySection,
} from './strategy'
import { emptySummary, type CategoryCard, type CategoryRunSnapshot } from './types'

export function useStrategyCategory(options: { rows: () => PanelRow[] }) {
  const { rows } = options
  const moduleKey = ref('')

  /** 结构化快照：每块一行，行内带完整数据。 */
  function dataOf(key: string): Record<string, unknown> | undefined {
    return rows().find((row) => row.key === `strategy:${key}`)?.data
  }

  /** 旧快照只有按 kind 拆分的结论行。 */
  function isStructured(): boolean {
    return Boolean(dataOf('positioning')) || STRATEGY_SECTION_KEYS.some((key) => Boolean(dataOf(key)))
  }

  /** 旧快照的模块分组，保留给已保存的历史结果。 */
  function legacyModules(): PaneModule[] {
    const clean = rows().filter((row) => row.kind !== 'divider')
    const positioning = clean.filter((row) => row.kind === 'fact' && row.label === '定位')
    const steps = clean.filter((row) => row.kind === 'step')
    const gaps = clean.filter((row) => row.kind === 'pair')
    const writing = clean.filter((row) => row.kind === 'fact' && row.label === '写法提示')
    const risks = clean.filter((row) => row.kind === 'fact' && row.label === '风险')
    const used = new Set<PanelRow>([...positioning, ...steps, ...gaps, ...writing, ...risks])
    const other = clean.filter((row) => !used.has(row))
    const list: PaneModule[] = []
    // 模块切换卡已经写了标题，行内不再重复「定位」标签。
    if (positioning.length)
      list.push({
        key: 'positioning',
        label: '策略定位',
        meta: '',
        rows: positioning.map((row) => ({ ...row, label: '' })),
      })
    if (steps.length) list.push({ key: 'steps', label: '优先行动', meta: '', rows: steps })
    if (gaps.length) list.push({ key: 'gaps', label: '待补缺口', meta: '', rows: gaps })
    // 写法提示和风险各成一框，条目本身不再重复带「写法提示 / 风险」标签。
    if (writing.length)
      list.push({
        key: 'writing',
        label: '写法提示',
        meta: '',
        rows: writing.map((row) => ({ ...row, label: '' })),
      })
    if (risks.length)
      list.push({
        key: 'risks',
        label: '风险',
        meta: '',
        rows: risks.map((row) => ({ ...row, label: '' })),
      })
    if (other.length) list.push({ key: 'other', label: '补充建议', meta: '', rows: other })
    return list
  }

  function structuredModules(): PaneModule[] {
    const list: PaneModule[] = []
    const positioningData = dataOf('positioning')
    if (positioningData) {
      const positioning = readStrategyPositioning(positioningData)
      if (positioning.blocks.length) {
        list.push({ key: 'positioning', label: '竞争力定位', meta: '', rows: [], data: positioningData })
      }
    }
    for (const section of STRATEGY_SECTIONS) {
      const data = dataOf(section.key)
      if (!data) continue
      const view = readStrategySection(section.key, data)
      if (!view.count) continue
      list.push({
        key: section.key,
        label: section.label,
        meta: `${view.count} 项`,
        rows: [],
        data,
      })
    }
    return list
  }

  const paneModules = computed<PaneModule[]>(() =>
    isStructured() ? structuredModules() : legacyModules(),
  )

  const modules = computed(() => toCategoryModules(paneModules.value))
  const activeModule = computed(
    () => paneModules.value.find((mod) => mod.key === moduleKey.value) || paneModules.value[0] || null,
  )
  const moduleRows = computed(() => activeModule.value?.rows || [])
  const activeModuleKey = computed(() => activeModule.value?.key || '')

  const ownRows = computed(() => rows().filter((row) => row.kind !== 'divider'))

  /** 结论条数：结构化按定位文字 + 各类条目计，旧快照按结论行计。 */
  const totalCount = computed(() => {
    if (!isStructured()) return ownRows.value.length
    let count = readStrategyPositioning(dataOf('positioning')).count
    for (const section of STRATEGY_SECTIONS) {
      const data = dataOf(section.key)
      if (data) count += readStrategySection(section.key, data).count
    }
    return count
  })

  /** 策略卡：定位作为导语，只展示有内容的类别数量。 */
  const summary = computed(() => {
    const view = emptySummary('metrics')
    if (isStructured()) {
      view.lead = readStrategyPositioning(dataOf('positioning')).blocks.find(
        (block) => block.key === 'career_positioning',
      )?.texts[0] || ''
      const stats: { label: string; value: string }[] = []
      for (const section of STRATEGY_SECTIONS) {
        const data = dataOf(section.key)
        const count = data ? readStrategySection(section.key, data).count : 0
        if (count) stats.push({ label: section.label, value: `${count} 项` })
      }
      view.stats = stats
      return view
    }

    const list = ownRows.value
    const legacyStats = [
      { label: '优先行动', value: list.filter((row) => row.kind === 'step').length },
      { label: '待补缺口', value: list.filter((row) => row.kind === 'pair').length },
      {
        label: '写法提示',
        value: list.filter((row) => row.kind === 'fact' && row.label === '写法提示').length,
      },
      { label: '风险', value: list.filter((row) => row.kind === 'fact' && row.label === '风险').length },
    ]
    view.stats = legacyStats
      .filter((stat) => stat.value > 0)
      .map((stat) => ({ label: stat.label, value: `${stat.value} 项` }))
    return view
  })

  const card = computed<CategoryCard>(() => ({
    key: 'strategy',
    icon: 'compass',
    title: '策略总结',
    subtitle: '市场结论与简历对照之后的行动建议',
    status: `${totalCount.value} 条`,
    note: isStructured() ? readStrategyPositioning(dataOf('positioning')).notes : '',
    summary: summary.value,
  }))

  const hasRows = computed(() => rows().length > 0)
  const emptyText = '等待策略总结 · 这里会显示定位、差距与行动优先级'

  function setModuleKey(key: string) {
    moduleKey.value = key
  }

  function reset() {
    moduleKey.value = ''
  }

  function snapshot() {
    return { strategyModule: moduleKey.value }
  }

  function restore(run: CategoryRunSnapshot) {
    const saved =
      typeof run.strategyModule === 'string' ? run.strategyModule : run.paneModuleState?.strategy
    moduleKey.value = typeof saved === 'string' ? saved : ''
  }

  return {
    moduleKey,
    modules,
    activeModule,
    activeModuleKey,
    moduleRows,
    card,
    hasRows,
    emptyText,
    setModuleKey,
    reset,
    snapshot,
    restore,
  }
}
