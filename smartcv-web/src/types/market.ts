/** 市场洞察产出总线的共享数据结构。 */

export interface DimInfo {
  id: string
  label: string
}

export interface EvidenceLink {
  id: string
  title: string
  url: string
  site: string
  /** 搜索结果的发布时间；没有时为空字符串，不显示。 */
  published: string
  /** 该页属于哪个调研维度（jobs / trend / 动态方面 id），采集面板按它归组。 */
  kind?: string
  /** 用户补充网址时填写的标签；普通搜索结果为 null。 */
  userTag?: { direction?: string; note?: string } | null
}

/** 职业路径中的一个阶段；stage 只写时间段，role / focus 承载阶段说明。 */
export interface CareerStage {
  stage: string
  role: string
  focus: string
}

/** 简历画像里的一条坐标证据；section / line 由后端回填。 */
export interface ResumeEvidence {
  coordinate: string
  quote: string
  section: string
  line: number
  location: string
  verified: boolean
}

export interface PanelRow {
  key: string
  kind: 'q' | 'collect' | 'fact' | 'bar' | 'step' | 'pair' | 'divider'
  idx?: number
  q?: string
  site?: string
  got?: number
  total?: number
  name?: string
  label?: string
  text?: string
  /** fact 行的语义色：role / salary / requirement / company / trend / release / skill / meta / summary。 */
  tone?: string
  /** fact 行的醒目主值，如薪资区间、技能等级、趋势方向。 */
  value?: string
  /** fact 行的短标签片，如岗位变体、代表公司、简历坐标。 */
  chips?: string[]
  /** 画像行的分组标签片，如「个人贡献」「项目优势」「量化成果」，按组带标题展示。 */
  groups?: { label: string; items: string[] }[]
  /** 缺口类型名称，如「技能缺口」「成果表达」。 */
  type_label?: string
  /** 缺口严重程度名称，如「严重」「中等」「轻微」。 */
  severity_label?: string
  /** 简历画像行的坐标证据；section / line 由后端校验后回填。 */
  resume_evidence?: ResumeEvidence[]
  /** 职业路径的结构化阶段；旧快照没有该字段时由 chips 回退解析。 */
  stages?: CareerStage[]
  /** bar 行：是否硬性要求。 */
  must?: boolean
  /** bar 行：年限要求。 */
  years?: string
  /** 该条结论引用的证据编号，前端解析成可点击来源。 */
  evidence?: string[]
  /** collect 行：所属维度 id / 维度名 / 原始站点名（site 可能带维度前缀）。 */
  group?: string
  groupLabel?: string
  rawSite?: string
  /** collect 行：抓取失败（既无正文也无摘要）的页数与原因。 */
  skipped?: number
  skipReasons?: string[]
  count?: number
  pct?: number
  trend?: string
  top?: boolean
  step?: string
  desc?: string
  tag?: 'hit' | 'gap' | 'transfer'
  /** 跨源合成结论：在对应维度页签里单独成栏，不混进该维度自己的抽取结果。 */
  synthesis?: boolean
  /** 招聘矩阵等结构化模块的原始数据；由对应面板直接解析，不拆成通用行。 */
  data?: Record<string, unknown>
}

export interface CollectGroup {
  id: string
  label: string
  rows: PanelRow[]
  planned: number
  got: number
}

export interface DistRow {
  key: string
  label: string
  count: number
  pct: number
}

export interface CollectDistribution {
  total: number
  sites: number
  dims: DistRow[]
  siteRows: DistRow[]
  rest: DistRow | null
}

export interface PlanQuery {
  q: string
  index: number
}

export interface PlanGroup {
  kind: string
  label: string
  source: string
  queries: PlanQuery[]
}

export interface PaneModule {
  key: string
  label: string
  meta: string
  rows: PanelRow[]
  /** 结构化模块（如招聘矩阵的四个矩阵）随模块一起携带原始数据。 */
  data?: Record<string, unknown>
}

export interface RowGroup {
  key: string
  rows: PanelRow[]
  block: boolean
}

export interface TrendSkillRow {
  key: string
  name: string
  direction: 'up' | 'flat' | 'down'
  directionLabel: string
  note: string
  evidence: string[]
}

export interface TrendBucket {
  key: string
  label: string
  sub: string
  dated: boolean
  skills: { key: string; name: string; count: number; direction: string }[]
}

export interface TrendFocusRow extends TrendSkillRow {
  recent: number
  earlier: number
  hot: number
}

export interface TrendAnalysis {
  dated: boolean
  focus: TrendFocusRow[]
  changes: TrendSkillRow[]
  up: number
  down: number
}

export interface TrendReleaseGroup {
  key: string
  tech: string
  rows: PanelRow[]
}

export interface PortraitBlock {
  key: string
  /** 能力分组标题；空字符串表示该块直接挂在章节下。 */
  label: string
  rows: PanelRow[]
}

export interface PortraitSection {
  key: string
  label: string
  count: number
  blocks: PortraitBlock[]
}
