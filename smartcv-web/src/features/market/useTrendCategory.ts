/** 技术趋势：总览汇总卡 + 五个矩阵页签；旧快照仍沿用时间鱼骨等旧模块。 */

import { computed, ref, watch } from 'vue'
import type {
  EvidenceLink,
  PaneModule,
  PanelRow,
  TrendAnalysis,
  TrendBucket,
  TrendReleaseGroup,
  TrendSkillRow,
} from '@/types/market'
import { toCategoryModules } from './dims'
import {
  emptySummary,
  type CategoryCard,
  type CategoryModule,
  type CategoryRunSnapshot,
} from './types'
import {
  readCategoryDistribution,
  readFrameworkEcosystem,
  readTechnologyApplications,
  readTechnologyFrequency,
  readTechnologyTrends,
  readTrendOverview,
} from './trend'

export type TrendView =
  | 'category'
  | 'frequency'
  | 'framework'
  | 'trends'
  | 'applications'
  | 'syn'
  | 'fish'
  | 'release'
  | 'focus'
  | 'changes'
  | 'extra'

const STRUCTURED_KEYS = [
  'trend:overview',
  'trend:category',
  'trend:frequency',
  'trend:framework',
  'trend:trends',
  'trend:applications',
] as const

const LEGACY_VIEWS: TrendView[] = ['fish', 'release', 'focus', 'changes', 'extra', 'syn']

const TREND_DIR_RANK: Record<string, number> = { up: 2, flat: 1, down: 0 }

/** 把发布时间裁成年月，作为鱼骨上的时间点。 */
function monthKey(value?: string): string {
  const match = (value || '').match(/(\d{4})[-/年.](\d{1,2})/)
  if (!match) return ''
  return `${match[1]}-${match[2].padStart(2, '0')}`
}

export function useTrendCategory(options: {
  rows: () => PanelRow[]
  evidenceLinks: Record<string, EvidenceLink>
}) {
  const { rows, evidenceLinks } = options
  const view = ref<TrendView>('category')

  function rowData(key: string): Record<string, unknown> | undefined {
    return rows().find((row) => row.key === key)?.data
  }

  const overview = computed(() => readTrendOverview(rowData('trend:overview')))
  const distribution = computed(() => readCategoryDistribution(rowData('trend:category')))
  const frequency = computed(() => readTechnologyFrequency(rowData('trend:frequency')))
  const framework = computed(() => readFrameworkEcosystem(rowData('trend:framework')))
  const trends = computed(() => readTechnologyTrends(rowData('trend:trends')))
  const applications = computed(() => readTechnologyApplications(rowData('trend:applications')))

  /** 任意一块带结构化数据就进入新视图；旧快照继续走下面的行式模块。 */
  const structured = computed(() => STRUCTURED_KEYS.some((key) => Boolean(rowData(key))))

  const frequencyCount = computed(
    () =>
      frequency.value?.fishbone.branches.reduce((sum, branch) => sum + branch.technologies.length, 0) || 0,
  )

  const structuredModules = computed<PaneModule[]>(() => {
    const list: PaneModule[] = []
    if (distribution.value?.items.length) {
      list.push({
        key: 'category',
        label: '技术领域分布',
        meta: `${distribution.value.items.length} 个领域`,
        rows: [],
        data: rowData('trend:category'),
      })
    }
    if (frequencyCount.value) {
      list.push({
        key: 'frequency',
        label: '高频技术',
        meta: `${frequencyCount.value} 项`,
        rows: [],
        data: rowData('trend:frequency'),
      })
    }
    if (framework.value?.items.length) {
      list.push({
        key: 'framework',
        label: '技术生态',
        meta: `${framework.value.items.length} 项`,
        rows: [],
        data: rowData('trend:framework'),
      })
    }
    const trendTotal = (trends.value?.trends.length || 0) + (trends.value?.problems.length || 0)
    if (trendTotal) {
      list.push({
        key: 'trends',
        label: '趋势与问题',
        meta: `${trendTotal} 条`,
        rows: [],
        data: rowData('trend:trends'),
      })
    }
    const rankingCount = applications.value?.scenario_ranking.items.length || 0
    const scenarioTrendCount = applications.value?.scenario_trends.items.length || 0
    if (rankingCount || scenarioTrendCount) {
      list.push({
        key: 'applications',
        label: '应用与场景',
        meta: `${Math.max(rankingCount, scenarioTrendCount)} 个场景`,
        rows: [],
        data: rowData('trend:applications'),
      })
    }
    const syn = rows().filter((row) => row.synthesis && row.kind !== 'divider')
    if (syn.length) list.push({ key: 'syn', label: '跨源分析', meta: `${syn.length} 条`, rows: syn })
    return list
  })

  const activeModule = computed<PaneModule | null>(() => {
    if (!structured.value) return null
    return structuredModules.value.find((mod) => mod.key === view.value) || structuredModules.value[0] || null
  })

  // ---- 旧快照：时间鱼骨 + 版本动态 + 更新分析 ----

  const trendSkills = computed<TrendSkillRow[]>(() =>
    rows()
      .filter((row) => row.tone === 'trend')
      .map((row) => {
        const direction = row.trend === 'up' || row.trend === 'down' ? row.trend : 'flat'
        return {
          key: row.key,
          name: row.label || row.name || '未命名技能',
          direction,
          directionLabel:
            row.value || (direction === 'up' ? '上升' : direction === 'down' ? '下降' : '平稳'),
          note: row.text || '',
          evidence: row.evidence || [],
        }
      }),
  )

  const releaseRows = computed(() => rows().filter((row) => row.tone === 'release'))

  /** 版本动态按技术归集：后端每行 label 是技术名，同一技术的多条变化收在一组。 */
  const releaseGroups = computed<TrendReleaseGroup[]>(() => {
    const groups = new Map<string, TrendReleaseGroup>()
    for (const row of releaseRows.value) {
      // 旧快照里 label 固定是「版本」，没有技术名，统一收进兜底组。
      const tech = row.label && row.label !== '版本' ? row.label : '未标注技术'
      const key = `trend:release:${tech}`
      const group = groups.get(tech) || { key, tech, rows: [] }
      group.rows.push(row)
      groups.set(tech, group)
    }
    return [...groups.values()]
  })

  const extraRows = computed(() =>
    rows().filter(
      (row) =>
        !row.synthesis &&
        row.tone !== 'trend' &&
        row.tone !== 'release' &&
        (row.label || row.text),
    ),
  )

  /** 其他结论按 kind 分成 fact / bar / step / pair 四块，只留白分隔，不写类型标题。 */
  const TREND_OTHER_KIND_ORDER = ['fact', 'bar', 'step', 'pair']
  const otherGroups = computed(() => {
    const list = extraRows.value
    const known = new Set<string>(TREND_OTHER_KIND_ORDER)
    const groups = TREND_OTHER_KIND_ORDER.map((kind) => ({
      key: `trend:extra:${kind}`,
      rows: list.filter((row) => row.kind === kind),
      block: true,
    })).filter((group) => group.rows.length)
    const rest = list.filter((row) => !known.has(row.kind))
    if (rest.length) groups.push({ key: 'trend:extra:other', rows: rest, block: true })
    return groups
  })

  /** 跨源结论单独成模块展示。 */
  const synthesisRows = computed(() =>
    rows().filter((row) => row.synthesis && row.kind !== 'divider'),
  )

  const legacyModules = computed<{ key: TrendView; label: string; meta: string }[]>(() => {
    const list: { key: TrendView; label: string; meta: string }[] = []
    const hasSkills = trendSkills.value.length > 0
    if (hasSkills) list.push({ key: 'fish', label: '技能鱼骨', meta: '' })
    if (releaseRows.value.length) list.push({ key: 'release', label: '版本动态', meta: '' })
    if (hasSkills) {
      list.push(
        { key: 'focus', label: '近期关注', meta: '' },
        { key: 'changes', label: '变化信号', meta: '' },
      )
    }
    if (extraRows.value.length) list.push({ key: 'extra', label: '其他结论', meta: '' })
    if (synthesisRows.value.length)
      list.push({ key: 'syn', label: '跨源分析', meta: `${synthesisRows.value.length} 条` })
    return list
  })

  const modules = computed<CategoryModule[]>(() => {
    if (structured.value) return toCategoryModules(structuredModules.value)
    return legacyModules.value.map((mod) => ({
      key: mod.key,
      label: mod.label,
      tabLabel: mod.label,
      meta: mod.meta,
      rows: [],
    }))
  })

  const activeModuleKey = computed(() =>
    structured.value ? activeModule.value?.key || '' : view.value,
  )

  /** 每个时间点里出现频次最高的技能；来源没有日期时退回单点「本轮样本」。 */
  const timeline = computed<TrendBucket[]>(() => {
    const skills = trendSkills.value
    if (!skills.length) return []
    const buckets = new Map<string, Map<string, number>>()
    // 同一页面可能佐证多个技能，站点计数按页面去重。
    const bucketPages = new Map<string, Set<string>>()
    for (const skill of skills) {
      for (const id of skill.evidence) {
        const key = monthKey(evidenceLinks[id]?.published)
        if (!key) continue
        const bucket = buckets.get(key) || new Map<string, number>()
        bucket.set(skill.name, (bucket.get(skill.name) || 0) + 1)
        buckets.set(key, bucket)
        const pages = bucketPages.get(key) || new Set<string>()
        pages.add(id)
        bucketPages.set(key, pages)
      }
    }
    if (!buckets.size) {
      return [
        {
          key: 'sample',
          label: '本轮样本',
          sub: '来源未标注发布时间',
          dated: false,
          skills: skills
            .map((skill) => ({
              key: skill.key,
              name: skill.name,
              count: Math.max(1, skill.evidence.length),
              direction: skill.direction,
            }))
            .sort((a, b) => b.count - a.count),
        },
      ]
    }
    return [...buckets.keys()]
      .sort()
      .slice(-6)
      .map((key) => {
        const bucket = buckets.get(key)!
        const list = [...bucket.entries()]
          .map(([name, count]) => ({
            key: skills.find((skill) => skill.name === name)?.key || name,
            name,
            count,
            direction: skills.find((skill) => skill.name === name)?.direction || 'flat',
          }))
          .sort((a, b) => b.count - a.count)
        return {
          key,
          label: key.replace('-', '.'),
          sub: `${bucketPages.get(key)?.size ?? 0} 条证据`,
          dated: true,
          skills: list,
        }
      })
  })

  const timelineDated = computed(() => timeline.value.some((bucket) => bucket.dated))

  const analysis = computed<TrendAnalysis>(() => {
    const skills = trendSkills.value
    const buckets = timeline.value
    const dated = timelineDated.value
    const recentKeys = new Set(buckets.slice(-2).map((bucket) => bucket.key))
    const recent = new Map<string, number>()
    const earlier = new Map<string, number>()
    for (const bucket of buckets) {
      const target = recentKeys.has(bucket.key) ? recent : earlier
      for (const skill of bucket.skills) {
        target.set(skill.name, (target.get(skill.name) || 0) + skill.count)
      }
    }
    const focus = skills
      .map((skill) => ({
        ...skill,
        recent: recent.get(skill.name) || 0,
        earlier: earlier.get(skill.name) || 0,
        hot: dated ? recent.get(skill.name) || 0 : skill.evidence.length,
      }))
      .sort(
        (a, b) =>
          b.hot - a.hot ||
          (TREND_DIR_RANK[b.direction] || 0) - (TREND_DIR_RANK[a.direction] || 0) ||
          b.evidence.length - a.evidence.length,
      )
      .slice(0, 5)
    const changes = [...skills].sort(
      (a, b) =>
        (TREND_DIR_RANK[b.direction] || 0) - (TREND_DIR_RANK[a.direction] || 0) ||
        b.evidence.length - a.evidence.length,
    )
    const up = skills.filter((skill) => skill.direction === 'up')
    const down = skills.filter((skill) => skill.direction === 'down')
    return {
      dated,
      focus,
      changes: changes.slice(0, 6),
      up: up.length,
      down: down.length,
    }
  })

  // 新一轮开始时模块可能变少：当前页签不可用了就退回第一个可用模块。
  watch(modules, (list) => {
    if (!list.some((module) => module.key === view.value)) {
      view.value = (list[0]?.key as TrendView | undefined) || (structured.value ? 'category' : 'fish')
    }
  })

  const summary = computed(() => {
    const card = emptySummary('metrics')
    if (structured.value) {
      const data = overview.value
      const totalTechnologies =
        data?.total_technologies ||
        frequency.value?.fishbone.branches.reduce(
          (sum, branch) => sum + branch.technologies.length,
          0,
        ) ||
        0
      const highFrequency =
        data?.high_frequency_count ||
        frequency.value?.fishbone.branches.reduce(
          (sum, branch) => sum + branch.technologies.filter((item) => item.percentage >= 30).length,
          0,
        ) ||
        0
      const emerging =
        data?.emerging_count || trends.value?.trends.filter((item) => item.trend_type === 'emerging').length || 0
      const scenarios =
        data?.application_scenario_count ||
        Math.max(
          applications.value?.scenario_ranking.items.length || 0,
          applications.value?.scenario_trends.items.length || 0,
        )
      const stats: { label: string; value: string }[] = []
      if (totalTechnologies) stats.push({ label: '技术', value: `${totalTechnologies} 项` })
      if (highFrequency) stats.push({ label: '高频', value: `${highFrequency} 项` })
      if (emerging) stats.push({ label: '新兴', value: `${emerging} 项` })
      if (scenarios) stats.push({ label: '场景', value: `${scenarios} 个` })
      card.lead = data?.research_summary || ''
      card.stats = stats
      card.chips = data?.top_technologies || []
      card.meter =
        totalTechnologies && highFrequency
          ? Math.round((highFrequency / totalTechnologies) * 100)
          : null
      return card
    }

    card.stats = [
      { label: '技能', value: `${trendSkills.value.length} 项` },
      { label: '时间点', value: `${timeline.value.length} 个` },
      { label: '上升', value: `${analysis.value.up} 项` },
      { label: '回落', value: `${analysis.value.down} 项` },
    ]
    return card
  })

  const card = computed<CategoryCard>(() => {
    const data = overview.value
    const totalTechnologies =
      data?.total_technologies ||
      frequency.value?.fishbone.branches.reduce(
        (sum, branch) => sum + branch.technologies.length,
        0,
      ) ||
      0
    const noteParts: string[] = []
    if (data?.time_range) noteParts.push(`统计范围：${data.time_range}`)
    if (data?.top_category) noteParts.push(`集中领域：${data.top_category}`)
    return {
      key: 'trend',
      icon: 'git-branch',
      title: '技术趋势',
      subtitle: '新技术调研矩阵：这个领域正在研究和关注哪些技术？',
      status: structured.value
        ? totalTechnologies
          ? `${totalTechnologies} 项技术`
          : '技术趋势'
        : `${trendSkills.value.length} 项技能`,
      note: structured.value ? noteParts.join(' · ') : '',
      summary: summary.value,
    }
  })

  const hasRows = computed(() => rows().length > 0)
  const emptyText = '等待抽取技术趋势 · 这里会显示技术趋势与新技术调研矩阵'

  function setModuleKey(key: string) {
    view.value = key as TrendView
  }

  function reset() {
    view.value = structured.value ? 'category' : 'fish'
  }

  function snapshot() {
    return { trendView: view.value }
  }

  function restore(run: CategoryRunSnapshot) {
    const saved = String(run.trendView || '')
    if (structured.value) {
      const keys = structuredModules.value.map((mod) => mod.key)
      view.value =
        keys.includes(saved) ? (saved as TrendView) : ((keys[0] as TrendView | undefined) || 'category')
      return
    }
    // 旧快照里的 analysis 视图已拆成多个模块，恢复时退回「近期关注」。
    view.value =
      saved === 'analysis' ? 'focus' : LEGACY_VIEWS.includes(saved as TrendView) ? (saved as TrendView) : 'fish'
  }

  return {
    view,
    modules,
    activeModule,
    activeModuleKey,
    timeline,
    timelineDated,
    analysis,
    extraGroups: otherGroups,
    extraRows,
    releaseGroups,
    releaseRows,
    synthesisRows,
    card,
    hasRows,
    emptyText,
    setModuleKey,
    reset,
    snapshot,
    restore,
  }
}
