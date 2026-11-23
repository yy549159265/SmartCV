/** 动态方面：每个维度一套「本维度分析 + 跨源分析」，共用一份模块选择状态。 */

import { reactive, type Ref } from 'vue'
import type { DimInfo, PanelRow, PaneModule, RowGroup } from '@/types/market'
import { ASPECT_SECTIONS, readAspectOverview, readAspectSection } from './aspect'
import { buildDynamicModules, splitRowGroups, toCategoryModules } from './dims'
import { dimShort } from './labels'
import {
  emptySummary,
  type CategoryCard,
  type CategoryModule,
  type CategoryRunSnapshot,
} from './types'

export interface DynamicCategoriesOptions {
  paneRows: Record<string, PanelRow[]>
  dims: Ref<DimInfo[]>
}

export function useDynamicCategories(options: DynamicCategoriesOptions) {
  const { paneRows, dims } = options
  /** 维度 id → 当前模块 key；各维度分别记忆自己选过的模块。 */
  const moduleKeys = reactive<Record<string, string>>({})

  /** 展示名：优先用本次调研的标签，其次退回内置中文名。 */
  function labelOf(tab: string): string {
    const dim = dims.value.find((item) => item.id === tab)
    return dim ? dimShort(dim.id, dim.label) : dimShort(tab)
  }

  /** 内容块行：键固定为 `${维度}:${短键}`，随行携带完整结构化数据。 */
  function sectionDataOf(tab: string, key: string): Record<string, unknown> | undefined {
    return (paneRows[tab] || []).find((row) => row.key === `${tab}:${key}`)?.data
  }

  /** 新快照有内容块数据；旧快照只有按 kind 拆分的结论行。 */
  function isStructured(tab: string): boolean {
    return ASPECT_SECTIONS.some((section) => Boolean(sectionDataOf(tab, section.key)))
  }

  function structuredModulesOf(tab: string): PaneModule[] {
    const list: PaneModule[] = []
    for (const section of ASPECT_SECTIONS) {
      const data = sectionDataOf(tab, section.key)
      if (!data) continue
      const view = readAspectSection(section.key, data)
      if (!view.total && !view.blocks.length) continue
      list.push({
        key: section.key,
        label: section.label,
        meta: view.total ? `${view.total} 条` : '',
        rows: [],
        data,
      })
    }
    const syn = (paneRows[tab] || []).filter((row) => row.synthesis && row.kind !== 'divider')
    if (syn.length) list.push({ key: 'syn', label: '跨源分析', meta: `${syn.length} 条`, rows: syn })
    return list
  }

  function modulesOf(tab: string): PaneModule[] {
    if (isStructured(tab)) return structuredModulesOf(tab)
    return buildDynamicModules(paneRows[tab] || [], labelOf(tab))
  }

  function activeModuleOf(tab: string): PaneModule | null {
    const modules = modulesOf(tab)
    return modules.find((mod) => mod.key === moduleKeys[tab]) || modules[0] || null
  }

  function modulesFor(tab: string): CategoryModule[] {
    return toCategoryModules(modulesOf(tab))
  }

  function moduleRowsOf(tab: string): PanelRow[] {
    return activeModuleOf(tab)?.rows || []
  }

  function rowGroupsOf(tab: string): RowGroup[] {
    return splitRowGroups(moduleRowsOf(tab), tab, activeModuleOf(tab)?.key || '', true)
  }

  function activeKeyOf(tab: string): string {
    return activeModuleOf(tab)?.key || ''
  }

  function evidenceCountOf(tab: string): number {
    const ids = new Set<string>()
    for (const row of paneRows[tab] || []) {
      for (const id of row.evidence || []) ids.add(id)
    }
    return ids.size
  }

  /** 结论条数：结构化快照按内容块的列表项 + 汇总句计，旧快照按结论行计。 */
  function conclusionCountOf(tab: string): number {
    if (!isStructured(tab)) {
      return (paneRows[tab] || []).filter((row) => row.kind !== 'divider' && !row.synthesis).length
    }
    return ASPECT_SECTIONS.reduce((sum, section) => {
      const data = sectionDataOf(tab, section.key)
      return sum + (data ? readAspectSection(section.key, data).total : 0)
    }, 0)
  }

  function summaryOf(tab: string) {
    const view = emptySummary('metrics')
    const syn = (paneRows[tab] || []).filter((row) => row.kind !== 'divider' && row.synthesis)
    const overview = readAspectOverview(sectionDataOf(tab, 'overview'))
    const conclusions = conclusionCountOf(tab)
    const evidence = evidenceCountOf(tab)
    const stats: { label: string; value: string }[] = []
    if (conclusions) stats.push({ label: '结论', value: `${conclusions} 条` })
    if (evidence) stats.push({ label: '来源', value: `${evidence} 条` })
    if (syn.length) stats.push({ label: '跨源', value: `${syn.length} 条` })
    view.lead = overview.summary
    view.stats = stats
    return view
  }

  function cardOf(tab: string): CategoryCard {
    const label = labelOf(tab)
    const count = conclusionCountOf(tab)
    const overview = readAspectOverview(sectionDataOf(tab, 'overview'))
    return {
      key: tab,
      icon: 'search',
      title: label,
      subtitle: `除了固定的招聘和技术调查，用户还想了解什么？`,
      status: `${count} 条`,
      note: overview.scope ? `调研范围：${overview.scope}` : '',
      summary: summaryOf(tab),
    }
  }

  function hasRowsOf(tab: string): boolean {
    return (paneRows[tab] || []).length > 0
  }

  function emptyTextOf(tab: string): string {
    const label = labelOf(tab)
    return `等待抽取${label} · 这里会显示${label}的调研结果`
  }

  function setModuleKey(tab: string, key: string) {
    moduleKeys[tab] = key
  }

  function reset() {
    Object.keys(moduleKeys).forEach((key) => delete moduleKeys[key])
  }

  function snapshot() {
    return { dimModules: { ...moduleKeys } }
  }

  function restore(run: CategoryRunSnapshot) {
    Object.keys(moduleKeys).forEach((key) => delete moduleKeys[key])
    const source =
      run.dimModules && typeof run.dimModules === 'object'
        ? (run.dimModules as Record<string, unknown>)
        : run.paneModuleState && typeof run.paneModuleState === 'object'
          ? (run.paneModuleState as Record<string, unknown>)
          : null
    if (!source) return
    for (const [key, value] of Object.entries(source)) {
      if (typeof value === 'string') moduleKeys[key] = value
    }
  }

  return {
    moduleKeys,
    modulesOf: modulesFor,
    activeModuleOf,
    moduleRowsOf,
    rowGroupsOf,
    activeKeyOf,
    cardOf,
    hasRowsOf,
    emptyTextOf,
    setModuleKey,
    reset,
    snapshot,
    restore,
  }
}
