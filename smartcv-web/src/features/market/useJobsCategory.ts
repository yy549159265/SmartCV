/** 招聘矩阵：样本概况 + 岗位分布 / 技术需求 / 能力需求 / 任职要求 + 跨源分析。 */

import { computed, ref } from 'vue'
import type { PanelRow, PaneModule, RowGroup } from '@/types/market'
import { buildJobModules, splitRowGroups, toCategoryModules } from './dims'
import { dimShort } from './labels'
import { emptySummary, type CategoryCard, type CategoryModule, type CategoryRunSnapshot } from './types'
import {
  dataQualityNote,
  distributionHasData,
  qualificationGroups,
  readAbilityMatrix,
  readJobDistribution,
  readJobsResearch,
  readQualificationMatrix,
  readTechnicalMatrix,
} from './jobs'

const RESEARCH_KEY = 'jobs:research'
const DISTRIBUTION_KEY = 'jobs:distribution'
const TECHNICAL_KEY = 'jobs:technical'
const ABILITY_KEY = 'jobs:ability'
const QUALIFICATION_KEY = 'jobs:qualification'
const MATRIX_KEYS = [RESEARCH_KEY, DISTRIBUTION_KEY, TECHNICAL_KEY, ABILITY_KEY, QUALIFICATION_KEY]

export function useJobsCategory(options: { rows: () => PanelRow[] }) {
  const { rows } = options
  const moduleKey = ref('')

  function rowData(key: string): Record<string, unknown> | undefined {
    return rows().find((row) => row.key === key)?.data
  }

  const researchRow = computed(() => rows().find((row) => row.key === RESEARCH_KEY && row.data))
  const research = computed(() => readJobsResearch(researchRow.value?.data))
  const distribution = computed(() => readJobDistribution(rowData(DISTRIBUTION_KEY)))
  const technical = computed(() => readTechnicalMatrix(rowData(TECHNICAL_KEY)))
  const ability = computed(() => readAbilityMatrix(rowData(ABILITY_KEY)))
  const qualification = computed(() => readQualificationMatrix(rowData(QUALIFICATION_KEY)))
  const qualificationGroupsValue = computed(() => qualificationGroups(qualification.value))

  /** 新快照带结构化矩阵；旧快照仍回退到按行拆分的模块。 */
  const structured = computed(
    () => Boolean(researchRow.value) || MATRIX_KEYS.some((key) => Boolean(rowData(key))),
  )

  const modules = computed<PaneModule[]>(() => {
    if (!structured.value) return buildJobModules(rows())

    const list: PaneModule[] = []
    if (distributionHasData(distribution.value) && distribution.value) {
      const count =
        distribution.value.job_types.length + distribution.value.company_distribution.length
      list.push({
        key: 'distribution',
        label: '岗位分布',
        meta: count ? `${count} 项` : '',
        rows: [],
        data: rowData(DISTRIBUTION_KEY),
      })
    }
    if (technical.value?.technologies.length) {
      list.push({
        key: 'technical',
        label: '技术需求',
        meta: `${technical.value.technologies.length} 项`,
        rows: [],
        data: rowData(TECHNICAL_KEY),
      })
    }
    if (ability.value?.abilities.length) {
      list.push({
        key: 'ability',
        label: '能力需求',
        meta: `${ability.value.abilities.length} 项`,
        rows: [],
        data: rowData(ABILITY_KEY),
      })
    }
    if (qualificationGroupsValue.value.length) {
      const count = qualificationGroupsValue.value.reduce((sum, group) => sum + group.items.length, 0)
      list.push({
        key: 'qualification',
        label: '任职要求',
        meta: `${count} 项`,
        rows: [],
        data: rowData(QUALIFICATION_KEY),
      })
    }

    const syn = rows().filter((row) => row.kind !== 'divider' && row.synthesis)
    if (syn.length) list.push({ key: 'syn', label: '跨源分析', meta: `${syn.length} 条`, rows: syn })
    return list
  })

  const activeModule = computed<PaneModule | null>(
    () => modules.value.find((mod) => mod.key === moduleKey.value) || modules.value[0] || null,
  )
  const moduleRows = computed(() => activeModule.value?.rows || [])
  const rowGroups = computed<RowGroup[]>(() =>
    splitRowGroups(moduleRows.value, 'jobs', activeModule.value?.key || '', false),
  )
  const tabs = computed(() => toCategoryModules(modules.value))
  const activeModuleKey = computed(() => activeModule.value?.key || '')
  /** 旧快照的技能模块仍沿用旧渲染，保留这两项给 FindingsPane。 */
  const skillRows = computed(
    () => modules.value.find((mod) => mod.key === 'skills')?.rows || [],
  )
  const mustHaveCount = computed(() => skillRows.value.filter((row) => row.must).length)

  const label = dimShort('jobs')
  const ownRows = computed(() =>
    rows().filter((row) => row.kind !== 'divider' && !row.synthesis),
  )
  const synRows = computed(() =>
    rows().filter((row) => row.kind !== 'divider' && row.synthesis),
  )

  const summary = computed(() => {
    const view = emptySummary('metrics')
    const data = research.value
    if (data) {
      const info = data.research_info
      view.lead = info.research_topic ? `调研方向：${info.research_topic}` : ''
      const stats: { label: string; value: string }[] = []
      if (info.valid_pages > 0) stats.push({ label: '有效页面', value: `${info.valid_pages} 个` })
      if (info.invalid_pages > 0) stats.push({ label: '无效页面', value: `${info.invalid_pages} 个` })
      if (info.companies.length) stats.push({ label: '涉及企业', value: `${info.companies.length} 家` })
      view.stats = stats
      view.chips = info.companies
      return view
    }

    const evidence = new Set<string>()
    for (const row of rows()) {
      for (const id of row.evidence || []) evidence.add(id)
    }
    view.stats = [
      { label: '结论', value: `${ownRows.value.length} 条` },
      { label: '来源', value: `${evidence.size} 条` },
      { label: '跨源', value: `${synRows.value.length} 条` },
    ]
    return view
  })

  const card = computed<CategoryCard>(() => {
    const info = research.value?.research_info
    const quality = research.value?.data_quality
    const legacyStatus = `${ownRows.value.length + synRows.value.length} 条`
    return {
      key: 'jobs',
      icon: 'briefcase',
      title: label,
      subtitle: '企业正在招聘什么样的人，需要什么能力？',
      status: info?.total_pages ? `共 ${info.total_pages} 个页面` : legacyStatus,
      note: dataQualityNote(quality || null),
      summary: summary.value,
    }
  })

  const hasRows = computed(() => rows().length > 0)
  const emptyText = `等待抽取${label} · 这里会显示${label}的调研结果`

  function setModuleKey(key: string) {
    moduleKey.value = key
  }

  function reset() {
    moduleKey.value = ''
  }

  function snapshot() {
    return { jobsModule: moduleKey.value }
  }

  function restore(run: CategoryRunSnapshot) {
    const saved = typeof run.jobsModule === 'string' ? run.jobsModule : run.paneModuleState?.jobs
    moduleKey.value = typeof saved === 'string' ? saved : ''
  }

  return {
    moduleKey,
    modules: tabs,
    activeModule,
    activeModuleKey,
    moduleRows,
    rowGroups,
    skillRows,
    mustHaveCount,
    card,
    hasRows,
    emptyText,
    setModuleKey,
    reset,
    snapshot,
    restore,
  }
}
