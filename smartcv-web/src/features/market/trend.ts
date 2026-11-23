/** 技术趋势（trend）：后端按「总览 + 五块矩阵」下发，前端直读每一块的结构化 JSON。 */

export interface TrendOverview {
  total_technologies: number
  high_frequency_count: number
  emerging_count: number
  application_scenario_count: number
  top_technologies: string[]
  top_category: string
  time_range: string
  research_summary: string
}

export interface CategoryStat {
  name: string
  technology_count: number
  mention_count: number
  percentage: number
  evidence_ids: string[]
}

export interface CategoryDistribution {
  items: CategoryStat[]
  summary: string
}

export interface FishboneTechnology {
  name: string
  total_count: number
  monthly_counts: number[]
  percentage: number
  evidence: string
  evidence_ids: string[]
}

export interface FishboneBranch {
  category: string
  technologies: FishboneTechnology[]
}

export interface TechnologyFrequency {
  time_range: string
  months: string[]
  fishbone: {
    center: string
    branches: FishboneBranch[]
  }
  summary: string
}

export interface FrameworkItem {
  name: string
  type: string
  category: string
  description: string
  related_technologies: string[]
  evidence: string
  evidence_ids: string[]
}

export interface FrameworkEcosystem {
  items: FrameworkItem[]
  summary: string
}

export type TrendType = 'rising' | 'stable' | 'declining' | 'emerging'

export interface TrendSignal {
  name: string
  category: string
  trend_type: TrendType
  description: string
  time_range: string
  change_points: string[]
  evidence: string
  evidence_ids: string[]
}

export interface TechnologyProblem {
  name: string
  category: string
  description: string
  impact: string
  related_technologies: string[]
  evidence: string
  evidence_ids: string[]
}

export interface TechnologyTrends {
  trends: TrendSignal[]
  problems: TechnologyProblem[]
  summary: string
}

export interface ScenarioStat {
  name: string
  count: number
  percentage: number
  related_technologies: string[]
  evidence: string
  evidence_ids: string[]
}

export interface ScenarioTrendItem {
  name: string
  monthly_counts: number[]
  trend: 'rising' | 'stable' | 'declining'
  evidence: string
  evidence_ids: string[]
}

export interface TechnologyApplications {
  total_scenarios: number
  total_mentions: number
  scenario_ranking: {
    items: ScenarioStat[]
    summary: string
  }
  scenario_trends: {
    months: string[]
    items: ScenarioTrendItem[]
    summary: string
  }
}

export const TREND_TYPE_LABEL: Record<string, string> = {
  rising: '上升',
  stable: '稳定',
  declining: '下降',
  emerging: '新兴',
}

export const SCENARIO_TREND_LABEL: Record<string, string> = {
  rising: '上升',
  stable: '稳定',
  declining: '下降',
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function num(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function int(value: unknown): number {
  return Math.max(0, Math.round(num(value)))
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : []
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record).filter((item): item is Record<string, unknown> => Boolean(item)) : []
}

function evidenceIds(value: unknown): string[] {
  return texts(value)
}

export function readTrendOverview(value: unknown): TrendOverview | null {
  const root = record(value)
  if (!root) return null
  const data = record(root.overview) || root
  if (!('total_technologies' in data) && !('research_summary' in data)) return null
  return {
    total_technologies: int(data.total_technologies),
    high_frequency_count: int(data.high_frequency_count),
    emerging_count: int(data.emerging_count),
    application_scenario_count: int(data.application_scenario_count),
    top_technologies: texts(data.top_technologies),
    top_category: text(data.top_category),
    time_range: text(data.time_range),
    research_summary: text(data.research_summary),
  }
}

export function readCategoryDistribution(value: unknown): CategoryDistribution | null {
  const data = record(value)
  if (!data) return null
  return {
    items: records(data.items).map((item) => ({
      name: text(item.name),
      technology_count: int(item.technology_count),
      mention_count: int(item.mention_count),
      percentage: num(item.percentage),
      evidence_ids: evidenceIds(item.evidence_ids),
    })).filter((item) => item.name),
    summary: text(data.summary),
  }
}

export function readTechnologyFrequency(value: unknown): TechnologyFrequency | null {
  const data = record(value)
  if (!data) return null
  const fishbone = record(data.fishbone) || {}
  return {
    time_range: text(data.time_range),
    months: texts(data.months),
    fishbone: {
      center: text(fishbone.center),
      branches: records(fishbone.branches).map((branch) => ({
        category: text(branch.category),
        technologies: records(branch.technologies).map((item) => ({
          name: text(item.name),
          total_count: int(item.total_count),
          monthly_counts: Array.isArray(item.monthly_counts) ? item.monthly_counts.map(int) : [],
          percentage: num(item.percentage),
          evidence: text(item.evidence),
          evidence_ids: evidenceIds(item.evidence_ids),
        })).filter((item) => item.name),
      })).filter((branch) => branch.category),
    },
    summary: text(data.summary),
  }
}

export function readFrameworkEcosystem(value: unknown): FrameworkEcosystem | null {
  const data = record(value)
  if (!data) return null
  return {
    items: records(data.items).map((item) => ({
      name: text(item.name),
      type: text(item.type),
      category: text(item.category),
      description: text(item.description),
      related_technologies: texts(item.related_technologies),
      evidence: text(item.evidence),
      evidence_ids: evidenceIds(item.evidence_ids),
    })).filter((item) => item.name),
    summary: text(data.summary),
  }
}

export function readTechnologyTrends(value: unknown): TechnologyTrends | null {
  const data = record(value)
  if (!data) return null
  return {
    trends: records(data.trends).map((item) => ({
      name: text(item.name),
      category: text(item.category),
      trend_type: (text(item.trend_type) || 'stable') as TrendType,
      description: text(item.description),
      time_range: text(item.time_range),
      change_points: texts(item.change_points),
      evidence: text(item.evidence),
      evidence_ids: evidenceIds(item.evidence_ids),
    })).filter((item) => item.name),
    problems: records(data.problems).map((item) => ({
      name: text(item.name),
      category: text(item.category),
      description: text(item.description),
      impact: text(item.impact),
      related_technologies: texts(item.related_technologies),
      evidence: text(item.evidence),
      evidence_ids: evidenceIds(item.evidence_ids),
    })).filter((item) => item.name),
    summary: text(data.summary),
  }
}

export function readTechnologyApplications(value: unknown): TechnologyApplications | null {
  const data = record(value)
  if (!data) return null
  const ranking = record(data.scenario_ranking) || {}
  const trends = record(data.scenario_trends) || {}
  return {
    total_scenarios: int(data.total_scenarios),
    total_mentions: int(data.total_mentions),
    scenario_ranking: {
      items: records(ranking.items).map((item) => ({
        name: text(item.name),
        count: int(item.count),
        percentage: num(item.percentage),
        related_technologies: texts(item.related_technologies),
        evidence: text(item.evidence),
        evidence_ids: evidenceIds(item.evidence_ids),
      })).filter((item) => item.name),
      summary: text(ranking.summary),
    },
    scenario_trends: {
      months: texts(trends.months),
      items: records(trends.items).map((item) => ({
        name: text(item.name),
        monthly_counts: Array.isArray(item.monthly_counts) ? item.monthly_counts.map(int) : [],
        trend: (text(item.trend) || 'stable') as ScenarioTrendItem['trend'],
        evidence: text(item.evidence),
        evidence_ids: evidenceIds(item.evidence_ids),
      })).filter((item) => item.name),
      summary: text(trends.summary),
    },
  }
}

/** 进度条宽度：保留最小可见宽度，同时不越过 100%。 */
export function trendBarWidth(percentage: number): string {
  return `${Math.max(2, Math.min(100, percentage))}%`
}

export function trendPercentText(percentage: number): string {
  return `${percentage.toFixed(1)}%`
}

/** 月份轴文字：2026-06 → 2026.06。 */
export function trendMonthLabel(month: string): string {
  return month.replace('-', '.')
}

/** 月度柱高：按当前序列的最大值归一，至少留 2px 可见高度。 */
export function trendSparkHeight(count: number, max: number): string {
  if (count <= 0) return '2px'
  return `${Math.max(2, Math.round((count / Math.max(1, max)) * 30))}px`
}
