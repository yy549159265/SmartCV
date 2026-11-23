/** 招聘矩阵（jobs）的结构化数据：后端按模块下发，前端直读每一块的 JSON。 */

export interface ResearchInfo {
  research_topic: string
  total_pages: number
  valid_pages: number
  invalid_pages: number
  companies: string[]
  coverage: 'complete' | 'partial' | 'insufficient'
}

export interface DataQuality {
  limitations: string[]
  statistics_note: string
  unverified_items: string[]
}

export interface CountStat {
  name: string
  count: number
  percentage: number
  evidence_ids: string[]
}

export interface SalaryRange {
  min: number | null
  max: number | null
  unit: string
  salary_months: number | null
  count: number
  evidence_ids: string[]
}

export interface SalaryMatrix {
  available_count: number
  unavailable_count: number
  salary_ranges: SalaryRange[]
  evidence: string
  summary: string
  evidence_ids: string[]
}

export interface JobDistribution {
  job_types: CountStat[]
  company_distribution: CountStat[]
  salary_matrix: SalaryMatrix | null
  summary: string
}

export interface TechnicalRequirement extends CountStat {
  requirement_level: 'must_have' | 'preferred' | 'common' | 'unknown'
  evidence: string
}

export interface TechnicalMatrix {
  technologies: TechnicalRequirement[]
  summary: string
}

export interface AbilityRequirement extends CountStat {
  description: string
  importance: 'high' | 'medium' | 'low'
}

export interface AbilityMatrix {
  abilities: AbilityRequirement[]
  ability_summary: string
}

export interface QualificationMatrix {
  education_requirements: CountStat[]
  experience_requirements: CountStat[]
  project_requirements: CountStat[]
  other_requirements: CountStat[]
  summary: string
}

export interface QualificationGroup {
  key: string
  label: string
  items: CountStat[]
}

export interface JobsResearchData {
  research_info: ResearchInfo
  data_quality: DataQuality
}

export const REQUIREMENT_LABEL: Record<string, string> = {
  must_have: '明确必备',
  preferred: '明确加分',
  common: '经常出现',
  unknown: '未明确',
}

export const IMPORTANCE_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
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

function strList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => text(item)).filter(Boolean)
    : []
}

function intOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.round(parsed) : null
}

function evidenceOf(value: Record<string, unknown>): string[] {
  return strList(value.evidence_ids)
}

function countStats(value: unknown): CountStat[] {
  const items = Array.isArray(value) ? value : []
  return items
    .map((item) => record(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      name: text(item.name),
      count: num(item.count),
      percentage: num(item.percentage),
      evidence_ids: evidenceOf(item),
    }))
    .filter((item) => item.name)
}

function readResearchInfo(value: unknown): ResearchInfo {
  const item = record(value) || {}
  const coverage = text(item.coverage)
  return {
    research_topic: text(item.research_topic),
    total_pages: num(item.total_pages),
    valid_pages: num(item.valid_pages),
    invalid_pages: num(item.invalid_pages),
    companies: strList(item.companies),
    coverage:
      coverage === 'complete' || coverage === 'partial' || coverage === 'insufficient'
        ? coverage
        : 'insufficient',
  }
}

function readDataQuality(value: unknown): DataQuality {
  const item = record(value) || {}
  return {
    limitations: strList(item.limitations),
    statistics_note: text(item.statistics_note),
    unverified_items: strList(item.unverified_items),
  }
}

function readSalaryRange(value: unknown): SalaryRange | null {
  const item = record(value)
  if (!item) return null
  const range: SalaryRange = {
    min: intOrNull(item.min),
    max: intOrNull(item.max),
    unit: text(item.unit) || 'CNY/month',
    salary_months: intOrNull(item.salary_months),
    count: num(item.count),
    evidence_ids: evidenceOf(item),
  }
  return range.min === null && range.max === null ? null : range
}

function readSalaryMatrix(value: unknown): SalaryMatrix | null {
  const item = record(value)
  if (!item) return null
  const ranges = (Array.isArray(item.salary_ranges) ? item.salary_ranges : [])
    .map(readSalaryRange)
    .filter((range): range is SalaryRange => Boolean(range))
  const matrix: SalaryMatrix = {
    available_count: num(item.available_count),
    unavailable_count: num(item.unavailable_count),
    salary_ranges: ranges,
    evidence: text(item.evidence),
    summary: text(item.summary),
    evidence_ids: evidenceOf(item),
  }
  return matrix
}

export function readJobsResearch(value: unknown): JobsResearchData | null {
  const item = record(value)
  if (!item) return null
  return {
    research_info: readResearchInfo(item.research_info),
    data_quality: readDataQuality(item.data_quality),
  }
}

export function readJobDistribution(value: unknown): JobDistribution | null {
  const item = record(value)
  if (!item) return null
  return {
    job_types: countStats(item.job_types),
    company_distribution: countStats(item.company_distribution),
    salary_matrix: readSalaryMatrix(item.salary_matrix),
    summary: text(item.summary),
  }
}

export function readTechnicalMatrix(value: unknown): TechnicalMatrix | null {
  const item = record(value)
  if (!item) return null
  const levels = ['must_have', 'preferred', 'common', 'unknown'] as const
  const technologies: TechnicalRequirement[] = (Array.isArray(item.technologies) ? item.technologies : [])
    .map((entry) => record(entry))
    .filter((entry): entry is Record<string, unknown> => Boolean(entry))
    .map((entry) => {
      const level = text(entry.requirement_level)
      return {
        name: text(entry.name),
        count: num(entry.count),
        percentage: num(entry.percentage),
        evidence_ids: evidenceOf(entry),
        requirement_level: levels.includes(level as (typeof levels)[number])
          ? (level as TechnicalRequirement['requirement_level'])
          : 'unknown',
        evidence: text(entry.evidence),
      }
    })
    .filter((entry) => entry.name)
  return { technologies, summary: text(item.summary) }
}

export function readAbilityMatrix(value: unknown): AbilityMatrix | null {
  const item = record(value)
  if (!item) return null
  const levels = ['high', 'medium', 'low'] as const
  const abilities: AbilityRequirement[] = (Array.isArray(item.abilities) ? item.abilities : [])
    .map((entry) => record(entry))
    .filter((entry): entry is Record<string, unknown> => Boolean(entry))
    .map((entry) => {
      const importance = text(entry.importance)
      return {
        name: text(entry.name),
        count: num(entry.count),
        percentage: num(entry.percentage),
        evidence_ids: evidenceOf(entry),
        description: text(entry.description),
        importance: levels.includes(importance as (typeof levels)[number])
          ? (importance as AbilityRequirement['importance'])
          : 'medium',
      }
    })
    .filter((entry) => entry.name)
  return { abilities, ability_summary: text(item.ability_summary) }
}

export function readQualificationMatrix(value: unknown): QualificationMatrix | null {
  const item = record(value)
  if (!item) return null
  return {
    education_requirements: countStats(item.education_requirements),
    experience_requirements: countStats(item.experience_requirements),
    project_requirements: countStats(item.project_requirements),
    other_requirements: countStats(item.other_requirements),
    summary: text(item.summary),
  }
}

export function qualificationGroups(matrix: QualificationMatrix | null): QualificationGroup[] {
  if (!matrix) return []
  return [
    { key: 'education', label: '学历要求', items: matrix.education_requirements },
    { key: 'experience', label: '工作经验', items: matrix.experience_requirements },
    { key: 'project', label: '项目背景', items: matrix.project_requirements },
    { key: 'other', label: '其他要求', items: matrix.other_requirements },
  ].filter((group) => group.items.length > 0)
}

export function distributionHasData(matrix: JobDistribution | null): boolean {
  if (!matrix) return false
  return Boolean(
    matrix.job_types.length ||
      matrix.company_distribution.length ||
      matrix.salary_matrix,
  )
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

/** 统一用「N 个页面 · 55.6%」，不出现 xxx/xxx 分式。 */
export function countText(item: CountStat): string {
  return `${item.count} 个页面 · ${formatPercent(item.percentage)}%`
}

export function barWidth(item: CountStat): string {
  const value = Math.max(0, Math.min(100, item.percentage))
  return `${value}%`
}

export function salaryUnit(unit: string): string {
  return { 'CNY/month': '元/月', 'CNY/year': '元/年', 'CNY/day': '元/天' }[unit] || unit || '元/月'
}

function money(value: number | null): string {
  return value === null ? '' : value.toLocaleString('zh-CN')
}

export function salaryRangeText(range: SalaryRange): string {
  const unit = salaryUnit(range.unit)
  if (range.min !== null && range.max !== null) {
    return `${money(range.min)}-${money(range.max)} ${unit}`
  }
  if (range.min !== null) return `${money(range.min)} ${unit} 起`
  if (range.max !== null) return `${money(range.max)} ${unit} 以内`
  return ''
}

export function salaryMetaText(range: SalaryRange): string {
  const parts: string[] = []
  if (range.salary_months) parts.push(`${range.salary_months} 薪`)
  if (range.count) parts.push(`${range.count} 个页面提及`)
  return parts.join(' · ')
}

export function dataQualityNote(quality: DataQuality | null): string {
  if (!quality) return ''
  const parts = [
    quality.statistics_note,
    ...quality.limitations,
    ...(quality.unverified_items.length
      ? [`未确认：${quality.unverified_items.join('、')}`]
      : []),
  ].filter(Boolean)
  return parts.join('；')
}
