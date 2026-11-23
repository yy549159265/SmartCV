/** 产出总线各类别共用的卡片 / 模块数据结构。 */

import type { PanelRow } from '@/types/market'

/** 类别视图在结果快照里的字段；paneModuleState 兼容旧快照。 */
export interface CategoryRunSnapshot {
  planView?: unknown
  collectView?: unknown
  distView?: unknown
  collectOpen?: unknown
  jobsModule?: unknown
  dimModules?: unknown
  trendView?: unknown
  portraitView?: unknown
  portraitSkillView?: unknown
  portraitProjectView?: unknown
  portraitGapView?: unknown
  strategyModule?: unknown
  paneModuleState?: Record<string, string>
}

/** 汇总卡内容：计划用步骤、画像用自述、其余用指标。 */
export interface SummaryView {
  type: 'steps' | 'metrics' | 'portrait'
  steps: { key: string; text: string }[]
  lead: string
  meter: number | null
  stats: { label: string; value: string }[]
  chips: string[]
  text: string
  meta: { label: string; value: string; chips: string[] }[]
  levels: { label: string; count: number; cls: string }[]
}

export function emptySummary(type: SummaryView['type']): SummaryView {
  return { type, steps: [], lead: '', meter: null, stats: [], chips: [], text: '', meta: [], levels: [] }
}

/** 技能画像明细的两种形态：总结文字 / 两列技能图谱。 */
export type SkillView = 'summary' | 'map'

/** 项目画像明细的两种形态：项目总结文字 / 项目价值列表。 */
export type ProjectView = 'summary' | 'value'

/** 缺口画像明细的两种形态：能力缺口 / 简历缺口。 */
export type GapView = 'capability' | 'resume'

/** 一个类别的模块（横向标签）：label 用于标题，tabLabel 用于窄条。 */
export interface CategoryModule {
  key: string
  label: string
  tabLabel: string
  meta: string
  rows: PanelRow[]
}

/** 类别汇总卡：标题、副标题、状态、说明都由各自的类别模块生成。 */
export interface CategoryCard {
  key: string
  icon: string
  title: string
  subtitle: string
  status: string
  note: string
  summary: SummaryView
}
