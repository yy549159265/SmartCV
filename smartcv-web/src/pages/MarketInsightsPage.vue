<script setup lang="ts">
/**
 * 市场洞察：真实 Agent 流水线 + market-insights.html 的布局/动效。
 *
 * 页面只让用户填「目标岗位」或选一份简历；城市、年限、时间范围等由 planner
 * 通过 ask_question 多轮反问补全。右侧标签栏 / 流程图 / 报告实时写作 / 光点飞行
 * 都沿用原型的行为，只是数据来自后端 SSE，不再有重播与速度演示。
 */

import {
  computed,
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import AskQuestionCard from '@/components/AskQuestionCard.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { DIM_META, TAB_LABEL, dimNodeText, dimShort } from '@/features/market/labels'
import CollectCategory from '@/features/market/CollectCategory.vue'
import DynamicCategory from '@/features/market/DynamicCategory.vue'
import JobsCategory from '@/features/market/JobsCategory.vue'
import PlanCategory from '@/features/market/PlanCategory.vue'
import PortraitCategory from '@/features/market/PortraitCategory.vue'
import StrategyCategory from '@/features/market/StrategyCategory.vue'
import TrendCategory from '@/features/market/TrendCategory.vue'
import { DIST_MODULE_KEY, useCollectCategory } from '@/features/market/useCollectCategory'
import { useDynamicCategories } from '@/features/market/useDynamicCategories'
import { useJobsCategory } from '@/features/market/useJobsCategory'
import { usePlanCategory } from '@/features/market/usePlanCategory'
import { usePortraitCategory } from '@/features/market/usePortraitCategory'
import { useStrategyCategory } from '@/features/market/useStrategyCategory'
import { useTrendCategory } from '@/features/market/useTrendCategory'
import type { CategoryRunSnapshot } from '@/features/market/types'
import {
  answerMarket,
  cancelMarket,
  inferMarketRoles,
  streamMarket,
  type MarketAnswer,
  type MarketEvent,
  type MarketRoleInference,
  type MarketRoleOption,
} from '@/api/market'
import { getProviderSettings, missingProviderFields, type ProviderSettings } from '@/api/provider'
import {
  DEFAULT_MARKET_MOTION,
  marketMotion,
  randomMotionStyle,
  withRandomDirection,
  type MotionChannel,
} from '@/composables/useMarketMotion'
import { collectorPayload, marketResearch, timeRangeLabel } from '@/composables/useMarketResearch'
import { resumeName } from '@/composables/useResumeName'
import { useDocumentsStore } from '@/stores/documents'
import { useMarketSourcesStore } from '@/stores/marketSources'
import { useResumeStore } from '@/stores/resume'
import type { QuestionItem } from '@/stores/review'
import type { CareerStage, DimInfo, EvidenceLink, PanelRow, ResumeEvidence } from '@/types/market'
import { message } from '@/utils/feedback'
import { linkTitle } from '@/utils/market'
import { renderMarkdown } from '@/utils/markdown'

// App.vue 的 keep-alive 按组件名缓存本页；显式声明，避免依赖文件名推断。
defineOptions({ name: 'MarketInsightsPage' })

/**
 * 节点 key 直接用后端语义 id：plan / collect / jobs / trend / 动态方面 / portrait / report。
 * 动态方面的数量和 id 由 planner 决定，因此这里不做联合类型限制。
 */
type NodeKey = string
type TabKey = string
/** 报告章节 id：固定章节 + 用户所选动态方面的 id，所以不设联合类型。 */
type SectionId = string

const DEFAULT_DIMS: DimInfo[] = [
  { id: 'jobs', label: '招聘矩阵' },
  { id: 'trend', label: '技术趋势' },
]

/** 动态方面各自成章，章节 id 就是维度 id；固定维度映射到固定章节。 */
function dimSection(dim: string): SectionId {
  return DIM_META[dim]?.section || dim
}

const activeDims = ref<DimInfo[]>(DEFAULT_DIMS.map((item) => ({ ...item })))

const NODE_ALIAS: Record<string, NodeKey | undefined> = {
  brief: 'plan',
  planner: 'plan',
  market: 'collect',
  collect: 'collect',
  profile: 'portrait',
  compose: 'report',
}

const SEC_SRC: Partial<Record<NodeKey, SectionId>> = {
  jobs: 'overview',
  trend: 'skills',
  strategy: 'conclusion',
  portrait: 'profile',
}

interface NodeState {
  state: 'idle' | 'running' | 'done' | 'error'
  text: string
  born: boolean
  unread: boolean
  progress: number
}

interface ReportSectionState {
  id: SectionId
  title: string
  fromKey: NodeKey
  hidden: boolean
  ready: boolean
  running: boolean
  status: 'idle' | 'running' | 'ready' | 'uncovered' | 'failed'
  draft: string
  prose: string
  sources: number
  sourceLinks: EvidenceLink[]
}

/** 浏览器里保留的一条历史报告：只存报告章节，不存整轮调研状态。 */
interface SavedReportSection {
  id: SectionId
  title: string
  hidden: boolean
  ready: boolean
  running: boolean
  status: ReportSectionState['status']
  draft: string
  prose: string
  sources: number
  sourceLinks: EvidenceLink[]
}

interface SavedReport {
  id: string
  savedAt: number
  targetRole: string
  sections: SavedReportSection[]
  ready: number
  total: number
}

const resumeStore = useResumeStore()
const documents = useDocumentsStore()
const marketSources = useMarketSourcesStore()

/** 目标岗位快捷项：收进输入框右侧的下拉里，不占版面；分研发岗位与 AI Agent 两组。 */
const ROLE_PRESET_GROUPS = [
  { label: '研发岗位', roles: ['前端工程师', '高级前端工程师', '全栈工程师', '后端工程师'] },
  { label: 'AI Agent', roles: ['AI Agent 前端工程师', 'AI Agent 全栈工程师'] },
]

const targetRole = ref('')
const direction = ref('')
const roleComboEl = ref<HTMLElement | null>(null)
const presetOpen = ref(false)

function pickRole(role: string) {
  targetRole.value = role
  presetOpen.value = false
}

/** 点面板外任意位置收起下拉。 */
function closePresetOnOutside(ev: PointerEvent) {
  if (!roleComboEl.value?.contains(ev.target as Node)) presetOpen.value = false
}

watch(presetOpen, (open) => {
  if (open) document.addEventListener('pointerdown', closePresetOnOutside, true)
  else document.removeEventListener('pointerdown', closePresetOnOutside, true)
})
const resumeChoice = ref('')
const roleOptions = ref<MarketRoleOption[]>([])
const roleInfo = ref<MarketRoleInference | null>(null)
const roleLoading = ref(false)
let roleSeq = 0
const collapsed = ref(false)
const running = ref(false)
const started = ref(false)
const finished = ref(false)
const errorText = ref('')
const statusText = ref('')
const taskId = ref('')
const activeTab = ref<TabKey>('collect')
/** 用户手动点过页签后不再自动跟随流程；新一轮调研开始时重置。 */
const tabPinned = ref(false)
const hasResume = ref(false)
const flashKey = ref<TabKey | null>(null)
const question = ref<QuestionItem | null>(null)
/** 策略没有独立流程节点，第一次收到策略结果时让页签按流程顺序出现。 */
const strategySeen = ref(false)

const nodeStates = reactive<Record<NodeKey, NodeState>>({
  plan: { state: 'idle', text: '等待开始', born: true, unread: false, progress: 0 },
  collect: { state: 'idle', text: '等待', born: false, unread: false, progress: 0 },
  jobs: { state: 'idle', text: '等待', born: false, unread: false, progress: 0 },
  trend: { state: 'idle', text: '等待', born: false, unread: false, progress: 0 },
  portrait: { state: 'idle', text: '等待', born: false, unread: false, progress: 0 },
  report: { state: 'idle', text: '等待', born: false, unread: false, progress: 0 },
})

const paneRows = reactive<Record<TabKey, PanelRow[]>>({
  plan: [],
  collect: [],
  jobs: [],
  trend: [],
  strategy: [],
  portrait: [],
})

/** 证据编号索引：collect 完成后一次性下发，面板行按 id 查链接。 */
const evidenceLinks = reactive<Record<string, EvidenceLink>>({})

const unread = reactive<Record<TabKey, number>>({
  plan: 0,
  collect: 0,
  jobs: 0,
  trend: 0,
  strategy: 0,
  portrait: 0,
})

const planDoc = ref<{ key: string; text: string }[]>([])
/** 检索清单：后端逐条下发，kind 是维度 id，source 标记这组词由 AI 生成还是代码兜底。 */
const planQueries = ref<{ q: string; kind: string; label: string; source: string }[]>([])
const planRunning = ref(false)
const resolvedBrief = ref<Record<string, string> | null>(null)
const collectPages = ref(0)
const collectPublished = ref(0)
const collectGroupsDone = ref(0)

/* ------------------------------------------------------------------ */
/* 通用模块切换：策略 / 岗位 / 其它维度                                  */
/* ------------------------------------------------------------------ */

/** 固定维度的证据前缀；其余维度由后端按顺序分配 E1、E2… */
const EVIDENCE_PREFIX_DIM: Record<string, string> = {
  J: 'jobs',
  T: 'trend',
}

/**
 * 证据编号 → 维度：固定维度用 J/T，动态维度是后端按顺序分配的 E1、E2…
 * 编号里的前缀顺序和 plan.result 下发的维度顺序一致，所以按序号回查 activeDims。
 */
/** 固定维度 id：证据前缀写死 J / T。 */
const FIXED_DIM_IDS = ['jobs', 'trend']

/**
 * 证据编号 → 维度：后端 sources.index 每条都带 kind，优先用它；
 * 查不到时退回去掉数字后的前缀，动态维度是 E1、E2…，按 plan.result 的维度顺序还原。
 */
function linkKind(link: EvidenceLink): string {
  if (link.kind) return link.kind
  const id = link.id || ''
  const head = id.charAt(0)
  if (EVIDENCE_PREFIX_DIM[head]) return EVIDENCE_PREFIX_DIM[head]
  const match = id.match(/^E(\d+)/)
  if (!match) return ''
  const dynamic = activeDims.value.filter((dim) => !FIXED_DIM_IDS.includes(dim.id))
  return dynamic[Number(match[1]) - 1]?.id || ''
}

/** 一条跨源结论引用到的维度：按证据编号找到对应页签，同一条结论会在每个相关页签里出现。 */
function synthesisTabs(evidence: string[]): TabKey[] {
  const dims = new Set<string>()
  for (const id of evidence) {
    const link = evidenceLinks[id]
    const dim = link ? linkKind(link) : linkKind({ id, title: '', url: '', site: '', published: '' })
    if (dim && activeDims.value.some((item) => item.id === dim)) dims.add(dim)
  }
  return [...dims] as TabKey[]
}

function newSection(id: SectionId, title: string, fromKey: NodeKey): ReportSectionState {
  return { id, title, fromKey, hidden: false, ready: false, running: false, status: 'idle', draft: '', prose: '', sources: 0, sourceLinks: [] }
}

/** 报告目录跟随本次选择的维度：岗位概览、技能要求、每个动态方面一章、简历对照、结论。 */
function applyReportSections(dims: DimInfo[]) {
  const fixed = new Set(['jobs', 'trend'])
  const next: ReportSectionState[] = [
    newSection('overview', '岗位概览', 'jobs'),
    newSection('skills', '技能要求', 'trend'),
    ...dims
      .filter((dim) => !fixed.has(dim.id))
      .map((dim) => newSection(dim.id, dim.label || dimShort(dim.id), dim.id)),
    { ...newSection('profile', '简历对照', 'portrait'), hidden: !hasResume.value },
    newSection('conclusion', '总结与建议', 'report'),
  ]
  reportSections.splice(0, reportSections.length, ...next)
}

const reportSections = reactive<ReportSectionState[]>([
  newSection('overview', '岗位概览', 'jobs'),
  newSection('skills', '技能要求', 'trend'),
  { ...newSection('profile', '简历对照', 'portrait'), hidden: true },
  newSection('conclusion', '总结与建议', 'report'),
])

const busShow = ref(false)
const busTag = ref('')
const busText = ref('')
const busUnwatched = ref(false)
const busHit = ref(false)

const canvasEl = ref<HTMLElement | null>(null)
/** 规划检索完成前不显示右侧产物面板（总线 + tab + 产物）和报告区。 */
const planReady = ref(false)
const reportOpen = ref(false)

watch(reportOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

function onReportKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') reportOpen.value = false
}

watch(reportOpen, (open) => {
  if (open) document.addEventListener('keydown', onReportKeydown)
  else document.removeEventListener('keydown', onReportKeydown)
})

const reportBodyEl = ref<HTMLElement | null>(null)
/** 当前聚焦的单章节 id；弹窗同一时间只展示一章。 */
const reportFocusSec = ref('')

const visibleReportSections = computed(() => reportSections.filter((s) => !s.hidden))

/* ------------------------------------------------------------------ */
/* 最近 3 次报告：报告正文单独存 localStorage，重新调研也不会覆盖。      */
/* ------------------------------------------------------------------ */

const REPORT_HISTORY_KEY = 'smartcv-market-reports'
const REPORT_HISTORY_LIMIT = 3
const reportHistory = ref<SavedReport[]>([])
const viewingReport = ref<SavedReport | null>(null)
const historyOpen = ref(false)
let historySaved = false

/** 点弹窗其它位置收起历史菜单；菜单内部已 @click.stop，不会误关。 */
function onHistoryOutside(ev: MouseEvent) {
  const target = ev.target as HTMLElement | null
  if (target?.closest('.report-history')) return
  historyOpen.value = false
}

watch(historyOpen, (open) => {
  if (open) document.addEventListener('click', onHistoryOutside)
  else document.removeEventListener('click', onHistoryOutside)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onHistoryOutside)
})

const displaySections = computed<SavedReportSection[] | ReportSectionState[]>(() =>
  viewingReport.value ? viewingReport.value.sections : reportSections,
)

const visibleDisplaySections = computed(() => displaySections.value.filter((s) => !s.hidden))

const displayProgressText = computed(() => {
  const saved = viewingReport.value
  if (saved) return `${saved.ready}/${saved.total} 就绪`
  return reportProgressText.value
})

const modalSections = computed(() => {
  const list = displaySections.value
  const focus = reportFocusSec.value
  const current = list.find((section) => section.id === focus && !section.hidden)
  if (current) return [current]
  const first = list.find((section) => !section.hidden)
  return first ? [first] : []
})

function focusSection(id: string) {
  reportFocusSec.value = id
  historyOpen.value = false
  nextTick(() => {
    reportBodyEl.value?.scrollTo({ top: 0 })
  })
}

function openReport() {
  viewingReport.value = null
  historyOpen.value = false
  reportFocusSec.value = visibleReportSections.value[0]?.id || ''
  reportOpen.value = true
}

function viewCurrentReport() {
  viewingReport.value = null
  historyOpen.value = false
  focusSection(visibleReportSections.value[0]?.id || '')
}

function viewHistoryReport(item: SavedReport) {
  viewingReport.value = item
  historyOpen.value = false
  focusSection(item.sections.find((section) => !section.hidden)?.id || '')
}

/** 左栏档案列表：打开某一份历史报告。 */
function openHistoryReport(item: SavedReport) {
  viewHistoryReport(item)
  reportOpen.value = true
}

function formatHistoryTime(value: number): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function loadReportHistory() {
  try {
    const raw = localStorage.getItem(REPORT_HISTORY_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw) as { v?: number; items?: unknown }
    if (!parsed || parsed.v !== 1 || !Array.isArray(parsed.items)) return
    reportHistory.value = (parsed.items as SavedReport[])
      .filter((item) => item && typeof item.id === 'string' && Array.isArray(item.sections))
      .slice(0, REPORT_HISTORY_LIMIT)
  } catch {
    /* 隐私模式 / 数据损坏：当作没有历史报告 */
  }
}

function persistReportHistory() {
  try {
    localStorage.setItem(REPORT_HISTORY_KEY, JSON.stringify({ v: 1, items: reportHistory.value }))
  } catch {
    /* 配额不足 / 隐私模式：放弃持久化，不影响当前报告 */
  }
}

/** 调研正常结束后把报告正文存进浏览器，只保留最近 3 次。 */
function saveReportToHistory() {
  if (historySaved) return
  const sections = visibleReportSections.value.filter((section) => section.ready || section.prose)
  if (!sections.length) return
  historySaved = true
  const item: SavedReport = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    savedAt: Date.now(),
    targetRole: targetRole.value.trim(),
    sections: plain(
      sections.map((section) => ({
        id: section.id,
        title: section.title,
        hidden: section.hidden,
        ready: section.ready,
        running: false,
        status: section.status,
        draft: '',
        prose: section.prose,
        sources: section.sources,
        sourceLinks: section.sourceLinks,
      })),
    ),
    ready: sections.filter((section) => section.ready).length,
    total: sections.length,
  }
  reportHistory.value = [item, ...reportHistory.value].slice(0, REPORT_HISTORY_LIMIT)
  persistReportHistory()
}
const edgesEl = ref<SVGSVGElement | null>(null)
const tabsEl = ref<HTMLElement | null>(null)
const flightSvg = ref<SVGSVGElement | null>(null)
const busEl = ref<HTMLElement | null>(null)
const askEl = ref<HTMLElement | null>(null)

/** 反问气泡锚定在流程里的「规划检索」节点上，坐标每次显示 / 尺寸变化时重算。 */
const askPos = reactive({
  left: 0,
  top: 0,
  width: 460,
  arrow: 24,
  side: 'top' as 'top' | 'bottom',
})

const hasCurrentResume = computed(() => resumeStore.resume.length > 0)
const backupFiles = computed(() => documents.files)
const tabs = computed(() => [
  { key: 'plan', label: '规划检索', needsResume: false },
  { key: 'collect', label: '采集页面', needsResume: false },
  ...activeDims.value.map((dim) => ({
    key: dim.id,
    label: dimShort(dim.id, dim.label),
    needsResume: false,
  })),
  { key: 'portrait', label: '简历画像', needsResume: true },
  { key: 'strategy', label: '策略总结', needsResume: false },
])
const visibleTabs = computed(() => tabs.value.filter((tab) => !tab.needsResume || hasResume.value))

/** 页签跟流程节点同步出现：节点尚未出生时先不显示，出现时按竖向顺序绘制。 */
function tabBorn(key: TabKey): boolean {
  if (key === 'plan') return planReady.value
  if (key === 'strategy') return strategySeen.value
  return Boolean(nodeStates[key]?.born)
}
const shownTabs = computed(() => visibleTabs.value.filter((tab) => tabBorn(tab.key)))
// 当前页签还没出生（比如刚开始只露出「计划」）时，切到已出现的最新页签，避免内容和页签对不上。
watch(shownTabs, (list) => {
  if (!list.length) return
  if (!list.some((tab) => tab.key === activeTab.value)) {
    activeTab.value = list[list.length - 1].key
  }
})

/** 顶层四类同级（规划检索 / 采集页面 / 简历画像 / 策略总结），只有采集下面的维度收在它自己那一组。 */
function railDepth(key: TabKey): number {
  return key === 'plan' || key === 'collect' || key === 'portrait' || key === 'strategy' ? 0 : 1
}

/** 类别状态只用四种说法：待开始 / 进行中 / N 项完成 / 失败，与参照稿逐条对应。 */
interface RailStatus {
  text: string
  tone: 'idle' | 'running' | 'done' | 'error'
}

/** 完成计数口径：分组按已完成的维度数算，叶子项一律 1 项。 */
function railDoneCount(key: TabKey): number {
  if (key !== 'collect') return 1
  const done = activeDims.value.filter((dim) => nodeStates[dim.id]?.state === 'done').length
  return done || 1
}

function railStatus(key: TabKey): RailStatus {
  if (key === 'strategy') {
    // 策略节点没有独立事件，按「是否已经拿到策略结论」判断，不新增流程状态。
    if (strategySeen.value) return { text: '1 项完成', tone: 'done' }
    if (paneRows.strategy?.length) return { text: '进行中', tone: 'running' }
    return { text: '待开始', tone: 'idle' }
  }
  const node = nodeStates[key]
  if (node?.state === 'running') return { text: '进行中', tone: 'running' }
  if (node?.state === 'error') return { text: '失败', tone: 'error' }
  if (node?.state === 'done') return { text: `${railDoneCount(key)} 项完成`, tone: 'done' }
  return { text: '待开始', tone: 'idle' }
}

interface RailItem {
  key: TabKey
  label: string
  status: RailStatus
  badge: number
}

interface RailGroup extends RailItem {
  /** 当前页签落在这一组里：整组浅底描边，组内当前项加粗。 */
  containsActive: boolean
  children: RailItem[]
}

/** 采集的维度挂在采集组下面；其余三类各自成组，顺序与流程一致。 */
const railGroups = computed<RailGroup[]>(() => {
  const groups: RailGroup[] = []
  shownTabs.value.forEach((tab) => {
    const item: RailItem = {
      key: tab.key,
      label: tab.label,
      status: railStatus(tab.key),
      badge: unread[tab.key] || 0,
    }
    if (railDepth(tab.key) === 1) {
      groups[groups.length - 1]?.children.push(item)
      return
    }
    groups.push({ ...item, containsActive: false, children: [] })
  })
  return groups.map((group) => ({
    ...group,
    containsActive:
      activeTab.value === group.key || group.children.some((item) => item.key === activeTab.value),
  }))
})
const canvasRows = computed(() => Math.max(4, activeDims.value.length + 1))
const graphNodes = computed(() => {
  const count = activeDims.value.length
  const rows = canvasRows.value
  const start = Math.max(1, Math.floor((rows - count) / 2) + 1)
  return [
    { key: 'plan', label: '规划检索', area: '2 / 1' },
    { key: 'collect', label: '采集页面', area: '2 / 2' },
    ...activeDims.value.map((dim, index) => ({
      key: dim.id,
      label: dimNodeText(dim.id, dim.label),
      area: `${start + index} / 3`,
    })),
    ...(hasResume.value ? [{ key: 'portrait', label: '简历画像', area: `${rows} / 1` }] : []),
    { key: 'report', label: '汇总报告', area: '2 / 4' },
  ]
})
const primaryDim = computed(() => activeDims.value[0]?.id || 'jobs')

const visibleSections = computed(() => reportSections.filter((section) => !section.hidden))
const readyCount = computed(() => visibleSections.value.filter((section) => section.ready).length)
const sectionTotal = computed(() => Math.max(1, visibleSections.value.length))
// 调研进行中也要能点「重新调研」：会先掐断当前这一轮再重新开始。
const canStart = computed(() => targetRole.value.trim() !== '' || resumeChoice.value !== '')

const resumeChoiceLabel = computed(() => {
  if (!resumeChoice.value) return '不提供简历'
  if (resumeChoice.value === '__current__') return `当前简历（${resumeName.value}）`
  return documents.files.find((file) => file.name === resumeChoice.value)?.title ?? resumeChoice.value
})

/** 简历反推出来的求职信息，展示的同时直接作为 MarketRequest 的 city / experience。 */
const roleTags = computed(() => {
  const info = roleInfo.value
  if (!info) return []
  return [
    { key: 'city', label: '求职城市', value: info.city },
    { key: 'experience', label: '工作年限', value: info.experience },
  ].filter((tag) => tag.value)
})

async function inferRoles() {
  if (roleLoading.value || running.value) return
  const provider = getProviderSettings()
  const missing = missingProviderFields(provider)
  if (missing.length) {
    message.warning(`请先在「高级设置」配置 ${missing.join('、')}`)
    return
  }
  const resolved = await resolveResume()
  if (!resolved.ok || !resolved.resume) return

  const seq = ++roleSeq
  roleLoading.value = true
  try {
    const result = await inferMarketRoles(resolved.resume, provider)
    if (seq !== roleSeq) return
    roleOptions.value = result.roles
    roleInfo.value = result
    if (!result.roles.length) message.warning('AI 没有返回可用岗位，请重试')
  } catch (err) {
    if (seq === roleSeq) message.error(err instanceof Error ? err.message : '岗位反推失败')
  } finally {
    if (seq === roleSeq) roleLoading.value = false
  }
}

function chooseRole(title: string) {
  targetRole.value = title
}

/** 收起后的基础信息：岗位单独一行，其余字段带标签，不用猜每段是什么。 */
const summaryRole = computed(
  () => resolvedBrief.value?.target_role || targetRole.value.trim() || '待确认岗位',
)
const summaryMeta = computed(() => {
  const brief = resolvedBrief.value
  const list: { label: string; value: string }[] = []
  const city = brief?.city || roleInfo.value?.city || ''
  if (city) list.push({ label: '城市', value: city })
  const window = planWindowText.value || timeRangeLabel(marketResearch.value.timeRange) || ''
  if (window) list.push({ label: '时间', value: window })
  const experience = brief?.experience || roleInfo.value?.experience || ''
  if (experience) list.push({ label: '经验', value: experience })
  const directionText = direction.value.trim()
  if (directionText) list.push({ label: '想了解', value: directionText })
  list.push({
    label: '简历',
    value: !resumeChoice.value
      ? '不提供'
      : resumeChoice.value === '__current__'
        ? resumeName.value
        : resumeChoiceLabel.value,
  })
  return list
})

const planTitle = computed(() => {
  const brief = resolvedBrief.value
  const role = brief?.target_role || targetRole.value || '目标岗位'
  return brief?.city ? `${role} @ ${brief.city}` : role
})

/** 规划阶段就把时间窗口（含后端算好的绝对区间）亮出来，说明本次数据的时间边界。 */
const planWindowText = computed(() => {
  const brief = resolvedBrief.value
  if (!brief?.time_window) return ''
  return brief.date_range ? `${brief.time_window}（${brief.date_range}）` : brief.time_window
})

/* ------------------------------------------------------------------ */
/* 产出总线七类内容：状态、汇总卡与模块选择都由各自模块管理              */
/* ------------------------------------------------------------------ */

const {
  moduleKey: planModuleKey,
  groups: planGroups,
  shownGroup: planShownGroup,
  modules: planModules,
  activeModuleKey: planActiveModuleKey,
  card: planCard,
  setModuleKey: setPlanModule,
  reset: resetPlan,
  snapshot: snapshotPlan,
  restore: restorePlan,
} = usePlanCategory({
  planDoc,
  planQueries,
  planRunning,
  dims: activeDims,
  title: planTitle,
})

const {
  view: collectView,
  modules: collectModules,
  shownGroups: collectShownGroups,
  distribution: collectDistribution,
  distView,
  open: collectOpen,
  card: collectCard,
  hasRows: collectHasRows,
  emptyText: collectEmptyText,
  sourcesOf: collectSources,
  sourceCountOf: collectSourceCount,
  numTitle: collectNumTitle,
  toggle: toggleCollect,
  setModuleKey: setCollectModule,
  setDistView: setCollectDistView,
  reset: resetCollect,
  snapshot: snapshotCollect,
  restore: restoreCollect,
} = useCollectCategory({
  rows: () => paneRows.collect,
  dims: activeDims,
  evidenceLinks,
  linkKind,
  planGroupCount: () => planGroups.value.length,
  pages: collectPages,
  published: collectPublished,
  windowText: planWindowText,
})

const {
  moduleKey: jobsModuleKey,
  modules: jobsModules,
  activeModuleKey: jobsActiveModuleKey,
  activeModule: jobsActiveModule,
  moduleRows: jobsModuleRows,
  rowGroups: jobsRowGroups,
  skillRows: jobSkillRows,
  mustHaveCount: jobMustHaveCount,
  card: jobsCard,
  hasRows: jobsHasRows,
  emptyText: jobsEmptyText,
  setModuleKey: setJobsModule,
  reset: resetJobs,
  snapshot: snapshotJobs,
  restore: restoreJobs,
} = useJobsCategory({ rows: () => paneRows.jobs })

/** 动态方面：除了固定的招聘信息 / 技术矩阵，其余维度都由后端按本轮选择下发。 */
const dynamicDims = computed(() =>
  activeDims.value.filter((dim) => !FIXED_DIM_IDS.includes(dim.id)),
)
const activeDynamicDim = computed(
  () => dynamicDims.value.find((dim) => dim.id === activeTab.value) || null,
)
const dynamic = useDynamicCategories({ paneRows, dims: activeDims })

const {
  view: trendView,
  modules: trendModules,
  activeModule: trendActiveModule,
  activeModuleKey: trendActiveModuleKey,
  timeline: trendTimeline,
  timelineDated: trendTimelineDated,
  analysis: trendAnalysis,
  extraGroups: trendOtherGroups,
  extraRows: trendExtraRows,
  releaseGroups: trendReleaseGroups,
  releaseRows: trendReleaseRows,
  synthesisRows: trendSynthesisRows,
  card: trendCard,
  hasRows: trendHasRows,
  emptyText: trendEmptyText,
  setModuleKey: setTrendModule,
  reset: resetTrend,
  snapshot: snapshotTrend,
  restore: restoreTrend,
} = useTrendCategory({ rows: () => paneRows.trend, evidenceLinks })

const {
  view: portraitView,
  modules: portraitModules,
  activeModuleKey: portraitActiveModuleKey,
  skillView: portraitSkillView,
  setSkillView: setPortraitSkillView,
  projectView: portraitProjectView,
  setProjectView: setPortraitProjectView,
  gapView: portraitGapView,
  setGapView: setPortraitGapView,
  sections: portraitSections,
  card: portraitCard,
  hasRows: portraitHasRows,
  emptyText: portraitEmptyText,
  setModuleKey: setPortraitModule,
  reset: resetPortrait,
  snapshot: snapshotPortrait,
  restore: restorePortrait,
} = usePortraitCategory({ rows: () => paneRows.portrait })

const {
  moduleKey: strategyModuleKey,
  modules: strategyModules,
  activeModuleKey: strategyActiveModuleKey,
  activeModule: strategyActiveModule,
  moduleRows: strategyModuleRows,
  card: strategyCard,
  hasRows: strategyHasRows,
  emptyText: strategyEmptyText,
  setModuleKey: setStrategyModule,
  reset: resetStrategy,
  snapshot: snapshotStrategy,
  restore: restoreStrategy,
} = useStrategyCategory({ rows: () => paneRows.strategy })

const reportProgressText = computed(() => `${readyCount.value}/${sectionTotal.value} 就绪`)

let controller: AbortController | null = null
// 校验 / 读简历期间的防连点开关；真正的运行状态看 running。
let starting = false
let resizeHandler: (() => void) | null = null

watch(hasResume, (value) => {
  if (restoringSnapshot) return
  applyResumeMode(value)
})
watch(resumeChoice, (value) => {
  if (restoringSnapshot) return
  hasResume.value = value !== ''
  roleSeq += 1
  roleOptions.value = []
  roleInfo.value = null
  roleLoading.value = false
})

/* ------------------------------------------------------------------ */
/* tabs + panes                                                        */
/* ------------------------------------------------------------------ */

function ensureNode(key: string) {
  if (!nodeStates[key]) {
    nodeStates[key] = { state: 'idle', text: '等待', born: false, unread: false, progress: 0 }
  }
  if (!paneRows[key]) paneRows[key] = []
  if (unread[key] === undefined) unread[key] = 0
  if (revealed[key] === undefined) revealed[key] = false
}

/** plan.result 到达后按后端 dims 重建动态节点 / 标签；多选时这里会一次建多个。 */
function applyDims(dims: DimInfo[]) {
  const next = dims.length ? dims : DEFAULT_DIMS.map((item) => ({ ...item }))
  activeDims.value = next
  const keep = new Set(['plan', 'collect', 'strategy', 'portrait', 'report', ...next.map((dim) => dim.id)])
  next.forEach((dim) => {
    ensureNode(dim.id)
    if (!nodeStates[dim.id].born) {
      nodeStates[dim.id].state = 'idle'
      nodeStates[dim.id].text = '等待'
    }
  })
  ;(Object.keys(nodeStates) as NodeKey[]).forEach((key) => {
    if (keep.has(key)) return
    delete nodeStates[key]
    delete paneRows[key]
    delete unread[key]
    delete revealed[key]
  })
  applyReportSections(next)
  if (!visibleTabs.value.some((tab) => tab.key === activeTab.value)) activeTab.value = 'collect'
  void nextTick(scheduleEdges)
}

function setActiveTab(key: TabKey) {
  ensureNode(key)
  activeTab.value = key
  tabPinned.value = true
  clearUnread(key)
  nodeStates[key].unread = false
}

function bumpUnread(key: TabKey) {
  ensureNode(key)
  if (key === activeTab.value) return
  unread[key] += 1
  nodeStates[key].unread = true
}

function clearUnread(key: TabKey) {
  unread[key] = 0
}

let flashTimer = 0
function flashTab(key: TabKey) {
  flashKey.value = key
  window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    if (flashKey.value === key) flashKey.value = null
  }, 420)
}

/* ------------------------------------------------------------------ */
/* resume mode                                                         */
/* ------------------------------------------------------------------ */

function applyResumeMode(value: boolean) {
  const profile = reportSections.find((section) => section.id === 'profile')
  if (profile) profile.hidden = !value
  if (!value && activeTab.value === 'portrait') activeTab.value = 'collect'
  if (!value) nodeStates.portrait.born = false
  // 规划跑完后才勾选简历：画像节点直接补进流程和页签，不等下一轮 revealGraph。
  if (value && planReady.value) nodeStates.portrait.born = true
  void nextTick(() => {
    scheduleEdges()
  })
}

/* ------------------------------------------------------------------ */
/* node state                                                          */
/* ------------------------------------------------------------------ */

function nodeEl(key: NodeKey): HTMLElement | null {
  return canvasEl.value?.querySelector<HTMLElement>(`[data-node="${key}"]`) ?? null
}

/** 动态维度可能不在 SEC_SRC 白名单里，按 DIM_META 兜底到对应报告章节。 */
function sectionOf(key: NodeKey): SectionId | undefined {
  if (SEC_SRC[key]) return SEC_SRC[key]
  if (activeDims.value.some((dim) => dim.id === key)) return dimSection(key)
  return undefined
}

function setNode(key: NodeKey, state: NodeState['state'], text?: string) {
  ensureNode(key)
  const node = nodeStates[key]
  node.state = state
  node.text = text || (state === 'running' ? '运行中' : state === 'done' ? '完成' : state === 'error' ? '失败' : '等待')
  if (state !== 'done') node.unread = false
  const section = sectionOf(key)
  if (state === 'running' && section) setSectionRunning(section, key)
  if (state === 'done' && section) markSectionReady(section, key)
  void nextTick(refreshEdges)
}

/* 回答完到计划生成之间可能有一段没有事件的空白：用秒表把这段时间可视化，
   否则规划节点一直停在「生成计划」，看起来就像卡死了。 */
let planWaitTimer = 0
let planWaitStart = 0
let planWaitBase = ''

function planWaitText(seconds: number): string {
  const base = planWaitBase || '正在生成检索计划…'
  return seconds > 0 ? `${base} · ${seconds}s` : base
}

/** 规划阶段的秒表：节点文字每秒走一次，任何阶段都不会再出现“静止不动”的假卡死。 */
function beginPlanWait(base = '正在生成检索计划…', updateStatus = true) {
  // 回答接口的响应可能比后端的 done 事件晚到：任务已经结束后不能再重启秒表，
  // 否则「已停止」会被覆盖回「正在生成检索计划」。
  if (!running.value || finished.value) return
  stopPlanWait()
  planWaitStart = Date.now()
  planWaitBase = base
  setNode('plan', 'running', planWaitText(0))
  if (updateStatus) statusText.value = '模型正在生成检索计划…'
  planWaitTimer = window.setInterval(() => {
    if (!running.value) {
      stopPlanWait()
      return
    }
    const seconds = Math.floor((Date.now() - planWaitStart) / 1000)
    setNode('plan', 'running', planWaitText(seconds))
    if (updateStatus && seconds >= 45) {
      statusText.value = `模型仍在生成检索计划（已等待 ${seconds}s），可点「重新调研」重开`
    }
  }, 1000)
}

function stopPlanWait() {
  if (planWaitTimer) {
    window.clearInterval(planWaitTimer)
    planWaitTimer = 0
  }
}

/** 后端一有新进展，已回答的卡片就让位，不再占着规划节点旁边。 */
function clearAnsweredQuestion() {
  if (question.value?.status === 'answered') question.value = null
}

function setSectionRunning(sectionId: SectionId, fromKey: NodeKey) {
  const section = reportSections.find((item) => item.id === sectionId)
  if (!section || section.hidden || section.ready) return
  section.running = true
  section.status = 'running'
  section.fromKey = fromKey
}

function markSectionReady(sectionId: SectionId, fromKey: NodeKey) {
  const section = reportSections.find((item) => item.id === sectionId)
  if (!section || section.hidden) return
  section.ready = true
  section.running = false
  if (section.status === 'idle' || section.status === 'running') section.status = 'ready'
  section.fromKey = fromKey
}

function sectionStateText(
  section: Pick<ReportSectionState, 'status' | 'ready' | 'running'> & { fromKey?: NodeKey },
): string {
  if (section.status === 'uncovered') return '素材不足'
  if (section.status === 'failed') return '已回退'
  if (section.ready) return '已就绪'
  if (section.running) return section.fromKey ? `${labelOf(section.fromKey)} 收集中…` : '收集中…'
  return '等待成稿'
}

function labelOf(key: NodeKey): string {
  if (DIM_META[key]) return DIM_META[key].node
  return { portrait: '简历画像', report: '报告' }[key] || ''
}

/* ------------------------------------------------------------------ */
/* graph reveal + edges                                                */
/* ------------------------------------------------------------------ */

let token = 0
const revealed = reactive<Record<NodeKey, boolean>>({
  plan: true,
  collect: false,
  jobs: false,
  trend: false,
  portrait: false,
  report: false,
})

function selectNode(key: NodeKey) {
  // 报告统一在弹窗里看，流程图节点就是入口按钮。
  if (key === 'report') {
    openReport()
    return
  }
  setActiveTab(key)
}

function popNode(key: NodeKey, delay: number, dur: number) {
  const node = nodeStates[key]
  const currentToken = token
  node.born = false
  window.setTimeout(() => {
    if (token !== currentToken || node.born) return
    node.born = true
    // 采集页签是右侧主视图：它刚出现、用户又没主动选过页签时跟过去，之后不再抢焦点。
    if (key === 'collect' && !tabPinned.value) activeTab.value = 'collect'
    const el = nodeEl(key)
    if (!el) return
    el.classList.add('drawing')
    window.setTimeout(() => el.classList.remove('drawing'), dur + 80)
  }, delay)
}

function drawEdgesTo(key: NodeKey, dur: number, delay: number) {
  const svg = edgesEl.value
  if (!svg) return
  const list = Array.from(svg.querySelectorAll<SVGPathElement>('.edge')).filter((path) => path.dataset.to === key)
  const currentToken = token
  list.forEach((path, index) => {
    const at = delay + index * 55
    path.dataset.draw = '0'
    window.setTimeout(() => {
      if (token !== currentToken) return
      const length = path.getTotalLength ? path.getTotalLength() : 0
      path.dataset.draw = '1'
      if (!length) return
      path.style.markerEnd = 'none'
      path.style.strokeDasharray = `${length} ${length}`
      path.style.strokeDashoffset = String(length)
      void path.getBoundingClientRect()
      path.style.transition = `stroke-dashoffset ${dur}ms cubic-bezier(0.2, 0.75, 0.25, 1)`
      path.style.strokeDashoffset = '0'
      window.setTimeout(() => {
        path.style.transition = ''
        path.style.strokeDasharray = ''
        path.style.strokeDashoffset = ''
        path.style.markerEnd = ''
        refreshEdges()
      }, dur + 30)
    }, at)
  })
}

function beat(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, ms)))
}

async function revealGraph() {
  const currentToken = token
  const draw = 340
  const wave = async (keys: NodeKey[], gap: number) => {
    keys.forEach((key, index) => {
      const delay = index * 60
      drawEdgesTo(key, draw, delay)
      popNode(key, delay + draw * 0.55, 460)
      revealed[key] = true
    })
    await beat(draw + Math.max(0, (keys.length - 1) * 60) + gap)
    if (token !== currentToken) return
  }

  await wave(['collect'], 90)
  if (token !== currentToken) return
  await wave(activeDims.value.map((dim) => dim.id), 110)
  if (token !== currentToken) return
  if (hasResume.value) {
    await wave(['portrait'], 90)
    if (token !== currentToken) return
  }
  await wave(['report'], 110)
}

let edgeRaf = 0
function scheduleEdges() {
  if (edgeRaf) return
  edgeRaf = window.requestAnimationFrame(() => {
    edgeRaf = 0
    layoutEdges()
  })
}

interface NodeBox {
  l: number
  r: number
  t: number
  b: number
  cx: number
  cy: number
}

function box(key: NodeKey): NodeBox | null {
  const el = nodeEl(key)
  const canvas = canvasEl.value
  if (!el || !canvas || !el.offsetParent) return null
  const c = canvas.getBoundingClientRect()
  const r = el.getBoundingClientRect()
  return {
    l: r.left - c.left,
    r: r.right - c.left,
    t: r.top - c.top,
    b: r.bottom - c.top,
    cx: (r.left + r.right) / 2 - c.left,
    cy: (r.top + r.bottom) / 2 - c.top,
  }
}

function curve(a: NodeBox, b: NodeBox, offA = 0, offB = 0): string {
  const sx = a.r
  const sy = a.cy + offA
  const ex = b.l
  const ey = b.cy + offB
  const dx = Math.max(24, (ex - sx) * 0.55)
  return `M ${sx} ${sy} C ${sx + dx} ${sy} ${ex - dx} ${ey} ${ex} ${ey}`
}

function straight(a: NodeBox, b: NodeBox, offA = 0, offB = 0): string {
  const sx = a.r
  const sy = a.cy + offA
  const ex = b.l
  const ey = b.cy + offB
  return `M ${sx} ${sy} L ${ex} ${ey}`
}

function addEdge(d: string, cls: string | null, fromKey: NodeKey, toKey: NodeKey): SVGPathElement | null {
  const svg = edgesEl.value
  if (!svg) return null
  const path = document.createElementNS(SVG_NS, 'path')
  path.setAttribute('d', d)
  path.setAttribute('class', `edge${cls ? ` ${cls}` : ''}`)
  path.setAttribute('marker-end', 'url(#arrow)')
  path.dataset.from = fromKey
  path.dataset.to = toKey
  svg.appendChild(path)
  return path
}

function layoutEdges() {
  const svg = edgesEl.value
  if (!svg) return
  svg.querySelectorAll('.edge, .edge-comet').forEach((element) => element.remove())

  const plan = box('plan')
  const collect = box('collect')
  const portrait = box('portrait')
  const report = box('report')
  if (!plan || !collect || !report) return

  addEdge(straight(plan, collect), null, 'plan', 'collect')

  const dims = activeDims.value
    .map((dim) => ({ id: dim.id, box: box(dim.id) }))
    .filter((item): item is { id: string; box: NodeBox } => item.box !== null)
  if (!dims.length) return

  dims.forEach((item, index) => {
    const offset = dims.length === 1 ? 0 : (index / (dims.length - 1) - 0.5) * 24
    addEdge(curve(collect, item.box, offset, 0), null, 'collect', item.id)
  })
  dims.forEach((item, index) => {
    const offset = dims.length === 1 ? 0 : (index / (dims.length - 1) - 0.5) * 22
    addEdge(curve(item.box, report, 0, offset), null, item.id, 'report')
  })

  if (portrait) {
    // 画的是数据依赖：画像只依赖规划结果（简报 + 简历），不依赖采集页面。
    // 执行上它在采集结束后和抽取 agent 同批并行，不等抽取、也不拖住抽取。
    addEdge(`M ${plan.cx} ${plan.b + 2} V ${portrait.t - 2}`, 'dashed', 'plan', 'portrait')

    const sx = portrait.r + 2
    const sy = portrait.cy
    const x2 = report.cx
    const r = 10
    addEdge(
      `M ${sx} ${sy} H ${x2 - r} Q ${x2} ${sy} ${x2} ${sy - r} V ${report.b + 3}`,
      'dashed',
      'portrait',
      'report',
    )
  }

  svg.querySelectorAll<SVGPathElement>('.edge').forEach((path) => {
    const target = path.dataset.to as NodeKey | undefined
    path.dataset.draw = target && revealed[target] ? '1' : '0'
  })

  refreshEdges()
}

const cometMap = new WeakMap<SVGPathElement, SVGPathElement>()
let flySeq = 0

function refreshEdges() {
  const svg = edgesEl.value
  if (!svg) return
  svg.querySelectorAll<SVGPathElement>('.edge').forEach((path) => {
    const from = path.dataset.from as NodeKey | undefined
    const to = path.dataset.to as NodeKey | undefined
    const fromEl = from ? nodeEl(from) : null
    const toEl = to ? nodeEl(to) : null
    const sa = fromEl?.dataset.state ?? ''
    const sb = toEl?.dataset.state ?? ''

    const active = sa === 'done' && sb === 'running'
    const done = sa === 'done' && sb === 'done'

    path.classList.toggle('active', active)
    path.classList.toggle('done', done)
    path.setAttribute('marker-end', active ? 'url(#arrowActive)' : done ? 'url(#arrowDone)' : 'url(#arrow)')
    syncComet(path, active)
  })
}

function syncComet(path: SVGPathElement, active: boolean) {
  let comet = cometMap.get(path)

  if (active && !comet) {
    const svg = edgesEl.value
    if (!svg) return
    comet = path.cloneNode(false) as SVGPathElement
    comet.removeAttribute('marker-end')
    comet.setAttribute('class', 'edge-comet')

    const bounds = path.getBBox()
    const gid = `comet-grad-${(flySeq += 1)}`
    const grad = document.createElementNS(SVG_NS, 'linearGradient')
    grad.setAttribute('id', gid)
    grad.setAttribute('gradientUnits', 'userSpaceOnUse')
    grad.setAttribute('x1', String(bounds.x))
    grad.setAttribute('y1', String(bounds.y))
    grad.setAttribute('x2', String(bounds.x + Math.max(1, bounds.width)))
    grad.setAttribute('y2', String(bounds.y + bounds.height))

    const s0 = document.createElementNS(SVG_NS, 'stop')
    s0.setAttribute('offset', '0')
    s0.setAttribute('stop-color', '#4753c7')
    s0.setAttribute('stop-opacity', '0.05')
    const s1 = document.createElementNS(SVG_NS, 'stop')
    s1.setAttribute('offset', '1')
    s1.setAttribute('stop-color', '#4753c7')
    s1.setAttribute('stop-opacity', '1')
    grad.appendChild(s0)
    grad.appendChild(s1)

    const defs = document.createElementNS(SVG_NS, 'defs')
    defs.appendChild(grad)
    comet.appendChild(defs)
    comet.style.stroke = `url(#${gid})`
    svg.appendChild(comet)
    cometMap.set(path, comet)
    return
  }

  if (!active && comet) {
    comet.remove()
    cometMap.delete(path)
  }
}

/* ------------------------------------------------------------------ */
/* report                                                              */
/* ------------------------------------------------------------------ */

/** 报告章节现在只在弹窗里渲染；弹窗没开时返回 null，飞行光点自然跳过。 */
function sectionEl(name: SectionId): HTMLElement | null {
  return document.querySelector<HTMLElement>(`.report-modal .rsec[data-sec="${name}"]`)
}

function setDraft(name: SectionId, text: string) {
  const section = reportSections.find((item) => item.id === name)
  if (!section || section.hidden) return
  section.draft = text
  flashSection(name)
}

function setProse(section: ReportSectionState, text: string, sources: number) {
  section.draft = ''
  section.prose = text
  section.sources = sources
  section.running = false
  section.ready = true
  if (section.status !== 'uncovered' && section.status !== 'failed') section.status = 'ready'
  flashSection(section.id)
}

function flashSection(name: SectionId) {
  const el = sectionEl(name)
  if (!el) return
  el.classList.add('flash')
  window.setTimeout(() => el.classList.remove('flash'), 700)
}

function draftFor(tab: TabKey): string {
  return summaryFromRows(tab)
}

/** 概览章节可能由 jobs + 多个动态方面共同供给，按当前维度列表合并草稿。 */
function overviewDraft(): string {
  const parts: string[] = []
  for (const dim of activeDims.value) {
    if (dimSection(dim.id) !== 'overview') continue
    const text = draftFor(dim.id)
    if (text && !parts.includes(text)) parts.push(text)
  }
  return parts.join(' · ').slice(0, 200)
}

/** 一行事实的纯文本摘要：标签、主值、正文、标签片都参与，空字段自动跳过。 */
function rowLine(row: PanelRow): string {
  return [row.label, row.value, row.text, ...(row.chips || [])]
    .map((part) => String(part || '').trim())
    .filter(Boolean)
    .join(' ')
}

function summaryFromRows(tab: TabKey): string {
  const rows = paneRows[tab] || []
  if (tab === 'jobs') {
    const facts = rows.filter((row) => row.kind === 'fact').slice(0, 2).map(rowLine)
    const bars = rows.filter((row) => row.kind === 'bar').slice(0, 3).map((row) => `${row.name} ${row.count}`)
    return [...facts, bars.join(' · ')].filter(Boolean).join(' · ').slice(0, 160)
  }
  if (tab === 'trend') {
    const bars = rows.filter((row) => row.kind === 'bar').slice(0, 4).map((row) => `${row.name} ${row.count}/${row.total}`)
    if (bars.length) return bars.join(' · ')
    return rows.filter((row) => row.kind === 'fact').slice(0, 3).map(rowLine).join(' · ').slice(0, 160)
  }
  if (tab === 'portrait') {
    const summary = rows.find((row) => row.tone === 'summary')
    const skills = rows.filter((row) => row.tone === 'skill').length
    const projects = rows.filter((row) => row.tone === 'project').length
    const hits = rows.filter((row) => row.kind === 'pair' && row.tag === 'hit').length
    const gaps = rows.filter((row) => row.kind === 'pair' && row.tag === 'gap').length
    return [
      summary?.text,
      `技能 ${skills} 项 · 项目 ${projects} 项 · 优势 ${hits} 项 · 缺口 ${gaps} 项`,
    ]
      .filter(Boolean)
      .join(' · ')
      .slice(0, 180)
  }
  // 动态方面：事实 + 比例条，没有条就取前两条事实。
  const facts = rows.filter((row) => row.kind === 'fact').slice(0, 2).map(rowLine)
  const bars = rows.filter((row) => row.kind === 'bar').slice(0, 3).map((row) => `${row.name} ${row.count}/${row.total}`)
  return [...facts, bars.join(' · ')].filter(Boolean).join(' · ').slice(0, 160)
}

/* ------------------------------------------------------------------ */
/* flight animation                                                    */
/* ------------------------------------------------------------------ */

const SVG_NS = 'http://www.w3.org/2000/svg'
const REDUCED = typeof window !== 'undefined' ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false
const MAX_FLIGHT = 8
let inFlight = 0
const flightQueue: { start: { x: number; y: number }; end: { x: number; y: number }; opts?: FlyOptions }[] = []
const planTimers: number[] = []

interface FlyOptions {
  bow?: number
  duct?: boolean
  /** 哪条链路：固定模式据此取颜色，随机模式忽略。 */
  channel?: MotionChannel
  color?: string
  tail?: number
  width?: number
  duration?: number
  alpha?: number
  /** 槽位满时排队等待，而不是直接丢弃（规划 query 需要 18 个都飞一次）。 */
  queue?: boolean
  onArrive?: () => void
}

function rectCenter(el: Element): { x: number; y: number } {
  const r = el.getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
}

function bottomPoint(el: Element): { x: number; y: number } {
  const r = el.getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.bottom - 2 }
}

function headPoint(el: Element): { x: number; y: number } {
  const r = el.getBoundingClientRect()
  return { x: r.left + 14, y: r.top + r.height / 2 }
}

function ductPath(start: { x: number; y: number }, end: { x: number; y: number }): string {
  const canvas = canvasEl.value
  const right = document.querySelector('.market-page .right')
  if (!canvas || !right) return arcPath(start, end)
  const ductY = canvas.getBoundingClientRect().bottom + 8
  const gx = right.getBoundingClientRect().left - 9
  const r = 10

  if (end.y >= ductY - 24) {
    return `M ${start.x} ${start.y} Q ${gx} ${start.y} ${end.x} ${end.y}`
  }

  return [
    `M ${start.x} ${start.y}`,
    `V ${ductY - r}`,
    `Q ${start.x} ${ductY} ${start.x + r} ${ductY}`,
    `H ${gx - r}`,
    `Q ${gx} ${ductY} ${gx} ${ductY - r}`,
    `V ${end.y + r}`,
    `Q ${gx} ${end.y} ${gx + r} ${end.y}`,
    `H ${end.x}`,
  ].join(' ')
}

function arcPath(start: { x: number; y: number }, end: { x: number; y: number }, bowOpt?: number): string {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const len = Math.hypot(dx, dy) || 1
  const bow = bowOpt == null ? Math.min(46, len * 0.24) : bowOpt
  const cx = (start.x + end.x) / 2 - (dy / len) * bow
  const cy = (start.y + end.y) / 2 + (dx / len) * bow
  return `M ${start.x} ${start.y} Q ${cx} ${cy} ${end.x} ${end.y}`
}

/**
 * 起飞前套用「高级设置 · 市场洞察」里的动效参数：
 * 固定模式统一用配置值；随机模式每个箭头单独抽颜色、拖尾长度和飞行时长。
 */
function withMotion(opts?: FlyOptions): FlyOptions {
  const next = { ...(opts || {}) }
  if (marketMotion.value.mode === 'random') {
    return { ...next, ...randomMotionStyle() }
  }
  const channel = next.channel
  // 设置页的数值是「基准值」，各链路按原有比例缩放，保留主链路短、成稿长的层次。
  const tailScale = marketMotion.value.tail / DEFAULT_MARKET_MOTION.tail
  const durationScale = marketMotion.value.duration / DEFAULT_MARKET_MOTION.duration
  return {
    ...next,
    color: (channel && marketMotion.value.colors[channel]) || next.color || '#4753c7',
    // 固定模式只固定颜色 / 长短 / 速度；方向默认逐条随机，避免所有箭头同向。
    bow: marketMotion.value.directionRandom !== false
      ? withRandomDirection(next.bow ?? 96)
      : next.bow,
    tail: Math.round((next.tail ?? DEFAULT_MARKET_MOTION.tail) * tailScale),
    duration: Math.round(
      (next.duration ?? DEFAULT_MARKET_MOTION.duration) * durationScale,
    ),
    width: marketMotion.value.width,
    alpha: next.alpha ?? marketMotion.value.alpha,
  }
}

function launchFlight(start: { x: number; y: number }, end: { x: number; y: number }, opts?: FlyOptions) {
  opts = withMotion(opts)
  const done = opts?.onArrive || (() => {})
  const svg = flightSvg.value
  if (!svg) {
    done()
    return
  }

  const from = start
  const to = end

  const d = opts?.duct ? ductPath(from, to) : arcPath(from, to, opts?.bow)
  const path = document.createElementNS(SVG_NS, 'path')
  path.setAttribute('d', d)
  path.setAttribute('class', 'fly-path')

  const color = opts?.color || '#4753c7'
  const gid = `fly-grad-${(flySeq += 1)}`
  const grad = document.createElementNS(SVG_NS, 'linearGradient')
  grad.setAttribute('id', gid)
  grad.setAttribute('gradientUnits', 'userSpaceOnUse')
  grad.setAttribute('x1', String(from.x))
  grad.setAttribute('y1', String(from.y))
  grad.setAttribute('x2', String(to.x))
  grad.setAttribute('y2', String(to.y))
  const st0 = document.createElementNS(SVG_NS, 'stop')
  st0.setAttribute('offset', '0')
  st0.setAttribute('stop-color', color)
  st0.setAttribute('stop-opacity', '0')
  const st1 = document.createElementNS(SVG_NS, 'stop')
  st1.setAttribute('offset', '1')
  st1.setAttribute('stop-color', color)
  st1.setAttribute('stop-opacity', '1')
  grad.appendChild(st0)
  grad.appendChild(st1)

  const defs = document.createElementNS(SVG_NS, 'defs')
  defs.appendChild(grad)
  svg.appendChild(defs)

  path.style.stroke = 'none'
  if (opts?.alpha) path.style.opacity = String(opts.alpha)

  const comet = document.createElementNS(SVG_NS, 'polygon')
  comet.setAttribute('class', 'fly-comet')
  comet.style.fill = `url(#${gid})`
  if (opts?.alpha) comet.style.opacity = String(opts.alpha)

  const head = document.createElementNS(SVG_NS, 'polygon')
  head.setAttribute('class', 'fly-head')
  head.style.fill = color

  svg.appendChild(path)
  svg.appendChild(comet)
  svg.appendChild(head)

  const total = path.getTotalLength()
  const seg = Math.min(opts?.tail || 220, total * 0.85)
  const maxW = opts?.width || 7
  inFlight += 1

  const duration = opts?.duration || Math.max(420, Math.min(760, total * 0.55))
  const t0 = performance.now()
  let finished = false

  function finish() {
    if (finished) return
    finished = true
    head.classList.add('done')
    comet.classList.add('done')
    window.setTimeout(() => {
      path.remove()
      comet.remove()
      head.remove()
      defs.remove()
    }, 220)
    inFlight -= 1
    drainFlights()
    done()
  }

  window.setTimeout(finish, duration + 900)

  const N = 16
  function frame(now: number) {
    if (finished) return
    const t = Math.min(1, (now - t0) / duration)
    const e = 1 - Math.pow(1 - t, 2.4)
    const headLen = total * e
    const hl = maxW * 2.2
    const hw = maxW * 1.4
    const headBase = Math.max(0, headLen - hl)
    const tailLen = Math.max(0, headBase - seg)
    const span = headBase - tailLen
    const left: string[] = []
    const right: string[] = []

    for (let i = 0; i <= N; i += 1) {
      const k = i / N
      const len = span > 0.4 ? tailLen + span * k : headBase
      const p = path.getPointAtLength(len)
      const p2 = path.getPointAtLength(Math.min(total, len + 0.8))
      let dx = p2.x - p.x
      let dy = p2.y - p.y
      const l = Math.hypot(dx, dy)
      if (l < 0.0001) {
        dx = to.x - from.x
        dy = to.y - from.y
      }
      const norm = Math.hypot(dx, dy) || 1
      const nx = -dy / norm
      const ny = dx / norm
      const w = maxW * (0.1 + 0.42 * k)
      left.push(`${(p.x + (nx * w) / 2).toFixed(2)},${(p.y + (ny * w) / 2).toFixed(2)}`)
      right.push(`${(p.x - (nx * w) / 2).toFixed(2)},${(p.y - (ny * w) / 2).toFixed(2)}`)
    }

    comet.setAttribute('points', span > 0.4 ? left.concat(right.reverse()).join(' ') : '')

    if (headLen < hl) {
      head.setAttribute('points', '')
    } else {
      const hp = path.getPointAtLength(headLen)
      const pp = path.getPointAtLength(Math.max(0, headLen - 2))
      let tx = hp.x - pp.x
      let ty = hp.y - pp.y
      const tl = Math.hypot(tx, ty)
      if (tl < 0.0001) {
        tx = to.x - from.x
        ty = to.y - from.y
      }
      const tn = Math.hypot(tx, ty) || 1
      tx /= tn
      ty /= tn
      const hx = -ty
      const hy = tx
      const bx = hp.x - tx * hl
      const by = hp.y - ty * hl
      head.setAttribute(
        'points',
        `${hp.x.toFixed(2)},${hp.y.toFixed(2)} ${(bx + (hx * hw) / 2).toFixed(2)},${(by + (hy * hw) / 2).toFixed(2)} ${(bx - (hx * hw) / 2).toFixed(2)},${(by - (hy * hw) / 2).toFixed(2)}`,
      )
    }

    if (t < 1) {
      requestAnimationFrame(frame)
      return
    }
    finish()
  }
  requestAnimationFrame(frame)
}

function fly(start: { x: number; y: number } | null, end: { x: number; y: number } | null, opts?: FlyOptions) {
  const done = opts?.onArrive || (() => {})
  if (REDUCED || !start || !end || !flightSvg.value) {
    done()
    return
  }
  if (inFlight >= MAX_FLIGHT) {
    if (opts?.queue) flightQueue.push({ start, end, opts })
    else done()
    return
  }
  launchFlight(start, end, opts)
}

function drainFlights() {
  while (inFlight < MAX_FLIGHT && flightQueue.length) {
    const job = flightQueue.shift()
    if (!job) break
    launchFlight(job.start, job.end, job.opts)
    if (!flightSvg.value) {
      flightQueue.length = 0
      break
    }
  }
}

function clearFlights() {
  flightQueue.length = 0
}

/* ------------------------------------------------------------------ */
/* bus + emit                                                          */
/* ------------------------------------------------------------------ */

let busTimer = 0
function noteBus(key: string, text: string, watched: boolean) {
  busTag.value = TAB_LABEL[key] || key
  busText.value = text
  busUnwatched.value = !watched
  busShow.value = true
  busHit.value = true
  window.clearTimeout(busTimer)
  busTimer = window.setTimeout(() => {
    busHit.value = false
  }, 320)
}

let highlightTimer = 0
const highlight = reactive({ tab: '' as TabKey | '', key: '' })

function markHighlight(tab: TabKey, key: string) {
  highlight.tab = tab
  highlight.key = key
  window.clearTimeout(highlightTimer)
  highlightTimer = window.setTimeout(() => {
    if (highlight.key === key) {
      highlight.key = ''
      highlight.tab = ''
    }
  }, 700)
}

function tabEl(key: TabKey): HTMLElement | null {
  return tabsEl.value?.querySelector<HTMLElement>(`[data-tab="${key}"]`) ?? null
}

function reportHeading(name: SectionId): Element | null {
  return sectionEl(name)
}

function summaryOf(key: TabKey, row: PanelRow): string {
  if (key === 'plan') return row.q || ''
  if (key === 'collect') return `${row.site} ${row.got}/${row.total}`
  if (key === 'jobs') return row.kind === 'bar' ? `${row.name} ${row.count} 个` : rowLine(row)
  if (key === 'trend') return row.kind === 'bar' ? `${row.name} ${row.count}/${row.total}` : rowLine(row)
  return rowLine(row)
}

const CHUNK_GAP = 90
const chunkQueue: { key: TabKey; row: PanelRow }[] = []
let chunkTimer = 0
let chunkLastAt = -1e9

/**
 * 一条 chunk = 一个箭头。chunk 可能成批到达（抽取一次 4 条、画像一次十几条），
 * 这里按固定间隔逐条放行，避免同一帧起飞后叠成一个箭头。
 */
function emitChunk(key: TabKey, row: PanelRow) {
  bumpUnread(key)
  chunkQueue.push({ key, row })
  pumpChunks()
}

function pumpChunks() {
  if (chunkTimer || !chunkQueue.length) return
  const wait = Math.max(0, CHUNK_GAP - (performance.now() - chunkLastAt))
  chunkTimer = window.setTimeout(() => {
    chunkTimer = 0
    const job = chunkQueue.shift()
    if (!job) return
    chunkLastAt = performance.now()
    emitChunkNow(job.key, job.row)
    pumpChunks()
  }, wait)
}

function emitChunkNow(key: TabKey, row: PanelRow) {
  markHighlight(key, row.key)
  const start = nodeEl(key)
  const tab = tabEl(key)
  const sectionName = sectionOf(key)
  const section = sectionName ? sectionEl(sectionName) : null

  fly(start ? rectCenter(start) : null, tab ? { x: tab.getBoundingClientRect().left - 6, y: tab.getBoundingClientRect().top + tab.getBoundingClientRect().height / 2 } : null, {
    bow: 200,
    channel: 'bus',
    queue: true,
    onArrive: () => {
      const watched = activeTab.value === key
      noteBus(key, summaryOf(key, row), watched)
      if (watched) {
        clearUnread(key)
        flashTab(key)
      }
      if (!section || !tab) return
      const head = reportHeading(sectionName!)
      if (!head) return
      fly(rectCenter(tab), headPoint(head), {
        bow: 74,
        channel: 'report',
        onArrive: () => flashSection(sectionName!),
      })
    },
  })
}

function clearChunkQueue() {
  chunkQueue.length = 0
  chunkLastAt = -1e9
  if (chunkTimer) {
    window.clearTimeout(chunkTimer)
    chunkTimer = 0
  }
}

/* ------------------------------------------------------------------ */
/* pane rows                                                           */
/* ------------------------------------------------------------------ */

function upsertRow(tab: TabKey, row: PanelRow): PanelRow {
  ensureNode(tab)
  const rows = paneRows[tab]
  const index = rows.findIndex((item) => item.key === row.key)
  if (index >= 0) {
    rows[index] = { ...rows[index], ...row }
    return rows[index]
  }
  rows.push(row)
  return row
}

function appendPlanQuery(item: { q?: string; query?: string; kind?: string; label?: string; source?: string }) {
  const index = planQueries.value.length + 1
  const row: PanelRow = {
    key: `q${index}`,
    kind: 'q',
    idx: index,
    q: String(item.q || item.query || ''),
    label: String(item.label || ''),
  }
  planQueries.value.push({
    q: row.q || '',
    kind: String(item.kind || ''),
    label: String(item.label || ''),
    source: item.source === 'fallback' ? 'fallback' : 'ai',
  })
  emitChunk('plan', row)
}

function extractRow(tab: TabKey, item: Record<string, unknown>, index: number): PanelRow {
  const key = String(item.key || item.id || `${tab}:${index}`)
  const kind = String(item.kind || 'fact')
  const data =
    item.data && typeof item.data === 'object' && !Array.isArray(item.data)
      ? (item.data as Record<string, unknown>)
      : undefined
  const chips = Array.isArray(item.chips)
    ? item.chips.map((chip) => String(chip || '').trim()).filter(Boolean)
    : []
  const evidence = Array.isArray(item.evidence_ids)
    ? item.evidence_ids.map((id) => String(id || '').trim()).filter(Boolean)
    : []
  const resumeEvidence: ResumeEvidence[] = Array.isArray(item.resume_evidence)
    ? (item.resume_evidence as Record<string, unknown>[]).map((entry) => ({
        coordinate: String(entry.coordinate || ''),
        quote: String(entry.quote || ''),
        section: String(entry.section || ''),
        line: Number(entry.line || 0),
        location: String(entry.location || ''),
        verified: Boolean(entry.verified),
      }))
    : []
  const stages: CareerStage[] = Array.isArray(item.stages)
    ? (item.stages as Record<string, unknown>[])
        .map((entry) => ({
          stage: String(entry.stage || '').trim(),
          role: String(entry.role || '').trim(),
          focus: String(entry.focus || '').trim(),
        }))
        .filter((entry) => entry.stage || entry.role || entry.focus)
    : []
  const groups = Array.isArray(item.groups)
    ? (item.groups as Record<string, unknown>[])
        .map((entry) => ({
          label: String(entry.label || '').trim(),
          items: Array.isArray(entry.items)
            ? entry.items.map((value) => String(value || '').trim()).filter(Boolean)
            : [],
        }))
        .filter((entry) => entry.label && entry.items.length)
    : []
  // 旧版画像行只发了 label，类型留在 profile 的 type / gap_type 里；这里一并接住。
  const isWeaknessRow = key.startsWith('profile:weakness:')
  const isGapRow = key.startsWith('profile:gap:')
  const typeLabel = String(
    item.type_label ||
      (isWeaknessRow ? item.type : '') ||
      (isGapRow ? item.gap_type || item.type : '') ||
      '',
  ).trim()
  const severityLabel = String(
    item.severity_label || (isGapRow ? item.severity : '') || '',
  ).trim()
  if (kind === 'divider') {
    return {
      key,
      kind: 'divider',
      label: String(item.label || ''),
      text: String(item.text || ''),
    }
  }
  if (kind === 'bar') {
    const count = Number(item.count || 0)
    return {
      key,
      kind: 'bar',
      name: String(item.name || item.label || ''),
      label: String(item.label || ''),
      text: String(item.text || ''),
      must: Boolean(item.must ?? item.must_have),
      years: String(item.years || ''),
      count,
      total: Number(item.total || 0),
      pct: Number(item.pct || 0),
      trend: String(item.trend || ''),
      top: count >= 14,
      evidence,
    }
  }
  if (kind === 'step') {
    return {
      key,
      kind: 'step',
      step: String(item.step || item.label || ''),
      desc: String(item.text || ''),
      label: String(item.label || ''),
      text: String(item.text || ''),
      evidence,
    }
  }
  if (kind === 'pair') {
    const tagValue = String(item.tag || 'gap')
    return {
      key,
      kind: 'pair',
      tag: tagValue === 'hit' || tagValue === 'transfer' ? tagValue : 'gap',
      label: String(item.label || ''),
      text: String(item.text || ''),
      chips,
      groups,
      type_label: typeLabel,
      severity_label: severityLabel,
      resume_evidence: resumeEvidence,
      evidence,
    }
  }
  return {
    key,
    kind: 'fact',
    label: String(item.label || ''),
    tone: String(item.tone || ''),
    value: String(item.value || ''),
    text: String(item.text || ''),
    chips,
    groups,
    type_label: typeLabel,
    severity_label: severityLabel,
    resume_evidence: resumeEvidence,
    stages,
    name: String(item.name || ''),
    trend: String(item.trend || ''),
    evidence,
    data,
  }
}

/** 把 ISO 发布时间裁成 YYYY-MM-DD；解析不了就原样截断。 */
function shortDate(value?: string): string {
  const text = (value || '').trim()
  if (!text) return ''
  const match = text.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (match) return `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`
  return text.slice(0, 10)
}

/** 面板行引用到的来源（最多 3 条），编号查不到时直接跳过。 */
function linksOf(row: { evidence?: string[] }): EvidenceLink[] {
  return [...new Set(row.evidence || [])]
    .map((id) => evidenceLinks[id])
    .filter((link): link is EvidenceLink => Boolean(link))
    .slice(0, 3)
}

/** 超过 3 条时提示还有多少条来源。 */
function moreLinks(row: { evidence?: string[] }): number {
  const ids = [...new Set(row.evidence || [])].filter((id) => evidenceLinks[id])
  return Math.max(0, ids.length - 3)
}

/** 在页签里插入一条来源分隔线，只插一次。 */
function addDivider(tab: TabKey, key: string, label: string, text: string, synthesis = false) {
  if (paneRows[tab]?.some((row) => row.key === key)) return
  const row = upsertRow(tab, { key, kind: 'divider', label, text, synthesis })
  emitChunk(tab, row)
}

function applyExtractChunk(dim: string, items: Record<string, unknown>[]) {
  if (dim === 'synthesis') {
    items.forEach((item, index) => {
      const evidence = Array.isArray(item.evidence_ids)
        ? item.evidence_ids.map((id) => String(id || '').trim()).filter(Boolean)
        : []
      // 做不到归属维度（比如只有「来源差异」没有证据编号）时，仍放在主维度里，避免丢结论。
      const tabs = synthesisTabs(evidence)
      const targets = tabs.length ? tabs : [primaryDim.value]
      const baseKey = String(item.key || item.id || index)
      targets.forEach((tab) => {
        addDivider(tab, `${tab}:divider:synthesis`, '跨源分析', '与其它调研维度交叉验证得出的结论', true)
        const row = extractRow(tab, { ...item, key: `${tab}:synthesis:${baseKey}` }, index)
        row.synthesis = true
        upsertRow(tab, row)
        emitChunk(tab, row)
      })
    })
    setDraft('overview', overviewDraft())
    return
  }
  const tab = dim as TabKey

  ensureNode(tab)
  setNode(tab, 'running', '抽取中')
  items.forEach((item, index) => {
    const row = extractRow(tab, item, index)
    upsertRow(tab, row)
    emitChunk(tab, row)
  })
  const section = sectionOf(tab)
  if (section) setDraft(section, section === 'overview' ? overviewDraft() : draftFor(tab))
}

function applyProfileChunk(items: Record<string, unknown>[]) {
  setNode('portrait', 'running', '对照简历')
  items.forEach((item, index) => {
    const row = extractRow('portrait', item, index)
    upsertRow('portrait', row)
    // divider 只是明细标题，不参与右侧箭头与“新结果”提示。
    if (row.kind !== 'divider') emitChunk('portrait', row)
  })
  setDraft('profile', summaryFromRows('portrait'))
}

function applyStrategyChunk(items: Record<string, unknown>[]) {
  const tab: TabKey = 'strategy'
  // 策略没有流程图节点，收到第一条结果时让页签补进竖向列表。
  strategySeen.value = true
  items.forEach((item, index) => {
    const row = extractRow(tab, item, index)
    upsertRow(tab, row)
    emitChunk(tab, row)
  })
  const strategyText = items
    .map((item) => String(item.text || '').trim())
    .filter(Boolean)
    .slice(0, 2)
    .join(' · ')
  if (strategyText) setDraft('conclusion', strategyText.slice(0, 180))
}

/* ------------------------------------------------------------------ */
/* report sections                                                     */
/* ------------------------------------------------------------------ */

function reportStarted(ev: Record<string, unknown>) {
  const id = String(ev.section || '') as SectionId
  const section = reportSections.find((item) => item.id === id)
  if (!section) return
  section.running = true
  section.ready = false
  section.status = 'running'
  section.draft = ''
  section.prose = ''
  section.sources = 0
  section.sourceLinks = []
  setNode('report', 'running', '成稿中')

  const node = nodeEl('report')
  const head = reportHeading(id)
  if (node && head) {
    fly(bottomPoint(node), headPoint(head), {
      channel: 'flow',
    })
  }
}

function reportDelta(ev: Record<string, unknown>) {
  if (ev.stage !== 'compose') return
  if (ev.kind && ev.kind !== 'answer') return
  const id = String(ev.section || '') as SectionId
  const section = reportSections.find((item) => item.id === id)
  if (!section) return
  section.running = true
  setNode('report', 'running', '成稿中')
  section.draft = `${section.draft}${String(ev.text || '')}`
}

function reportSectionDone(ev: Record<string, unknown>) {
  const id = String(ev.id || ev.section || '') as SectionId
  const section = reportSections.find((item) => item.id === id)
  if (!section) return
  const status = String(ev.status || 'ready')
  section.status = status === 'uncovered' || status === 'failed' ? status : 'ready'
  const links = (Array.isArray(ev.sources) ? ev.sources : [])
    .map((item) => {
      const source = item as Record<string, unknown>
      const sourceId = String(source.id || '')
      const url = String(source.url || '')
      if (!sourceId || !url) return null
      return {
        id: sourceId,
        title: String(source.title || url),
        url,
        site: String(source.site || ''),
        published: String(source.published || ''),
      }
    })
    .filter((link): link is EvidenceLink => Boolean(link))
  section.sourceLinks = links
  setProse(section, String(ev.prose || ''), links.length)
}

/* ------------------------------------------------------------------ */
/* ask question                                                        */
/* ------------------------------------------------------------------ */

function planNodeEl(): HTMLElement | null {
  return canvasEl.value?.querySelector<HTMLElement>('[data-node="plan"]') ?? null
}

function positionAsk() {
  if (!question.value) return
  const node = planNodeEl()
  if (!node) return
  const rect = node.getBoundingClientRect()
  const width = Math.min(460, window.innerWidth - 32)
  const height = askEl.value?.offsetHeight || 0
  const gap = 14
  const margin = 12

  // 默认落在规划节点正下方，箭头朝上指向节点；下方放不下再翻到节点上方。
  let top = rect.bottom + gap
  let side: 'top' | 'bottom' = 'top'
  if (height && top + height > window.innerHeight - margin) {
    const above = rect.top - gap - height
    if (above >= margin) {
      top = above
      side = 'bottom'
    } else {
      // 上下都放不下时贴住可视区底部，至少让题目和选项完整露出来。
      top = window.innerHeight - margin - height
    }
  }
  if (height) top = Math.max(margin, Math.min(top, window.innerHeight - margin - height))

  askPos.left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin))
  askPos.top = top
  askPos.width = width
  askPos.arrow = Math.max(18, Math.min(width - 18, rect.left + rect.width / 2 - askPos.left))
  askPos.side = side
}

let askRaf = 0
/** 收起/展开配置、右侧面板出现、卡片换题变高后重新贴合规划节点。 */
function scheduleAskPosition() {
  if (askRaf) window.cancelAnimationFrame(askRaf)
  askRaf = window.requestAnimationFrame(() => {
    // 卡片高度常要等这一帧布局结束才稳定，补测一次。
    askRaf = window.requestAnimationFrame(() => {
      askRaf = 0
      positionAsk()
    })
  })
}

/** 规划节点被滚出可视区时先带回来，否则气泡只能落在屏幕外。 */
function revealPlanNode() {
  const node = planNodeEl()
  if (!node) return
  const rect = node.getBoundingClientRect()
  if (rect.top >= 64 && rect.bottom <= window.innerHeight - 8) return
  node.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

function showQuestion(ev: Record<string, unknown>) {
  stopPlanWait()
  const timeoutSeconds = Number(ev.timeoutSeconds || 240)
  question.value = {
    kind: 'question',
    questionId: String(ev.questionId || ''),
    title: String(ev.title || '需要确认几个信息'),
    questions: Array.isArray(ev.questions) ? (ev.questions as QuestionItem['questions']) : [],
    status: 'pending',
    answers: null,
    timeoutSeconds,
    expiresAt: Date.now() + timeoutSeconds * 1000,
  }
  statusText.value = '等待你确认信息'
  setNode('plan', 'running', '等待确认')
  void nextTick(() => {
    revealPlanNode()
    scheduleAskPosition()
  })
}

watch(
  () => question.value?.status,
  () => {
    if (question.value) void nextTick(scheduleAskPosition)
  },
)

// 收起 / 展开配置会整体重排左栏，规划节点随之移动，气泡必须跟着重新贴合。
watch([collapsed, planReady], () => {
  if (question.value) void nextTick(scheduleAskPosition)
})

// 多题切换、自定义输入展开都会改变卡片高度，高度一变就重新夹回可视区。
let askObserver: ResizeObserver | null = null
watch(askEl, (el) => {
  askObserver?.disconnect()
  askObserver = null
  if (!el) return
  askObserver = new ResizeObserver(scheduleAskPosition)
  askObserver.observe(el)
})

async function submitQuestion(questionId: string, answers: MarketAnswer[]) {
  const current = question.value
  if (!current || !taskId.value) {
    message.warning('调研任务已失效，请重新开始')
    return
  }
  current.status = 'submitting'
  try {
    await answerMarket(taskId.value, questionId, answers)
    current.status = 'answered'
    current.answers = answers
    // 回答提交成功就立刻切到「生成计划」并开始计时，不等下一个 SSE 事件，
    // 这样模型慢的时候用户也能看到时间在走。
    beginPlanWait()
    window.setTimeout(() => {
      if (question.value?.questionId === questionId && question.value?.status === 'answered') {
        question.value = null
      }
    }, 1200)
  } catch (err) {
    current.status = 'pending'
    message.error(err instanceof Error ? err.message : '提交回答失败')
  }
}

function closeQuestion(ev: Record<string, unknown>) {
  const current = question.value
  if (!current || current.questionId !== String(ev.questionId || '')) return
  current.status = 'expired'
  // 问题超时后端会带着默认答案继续跑，同样需要把「正在生成」的进度露出来。
  beginPlanWait()
  window.setTimeout(() => {
    if (question.value?.questionId === current.questionId) question.value = null
  }, 2200)
}

/* ------------------------------------------------------------------ */
/* SSE events                                                          */
/* ------------------------------------------------------------------ */

function nodeKeyOf(node: string): NodeKey | undefined {
  if (NODE_ALIAS[node]) return NODE_ALIAS[node]
  return activeDims.value.some((dim) => dim.id === node) ? node : undefined
}

function handleEvent(ev: MarketEvent) {
  const data = ev as Record<string, unknown>
  switch (ev.type) {
    case 'task':
      if (typeof data.taskId === 'string') taskId.value = data.taskId
      break

    case 'status':
      // 秒表只改节点文字，不碰状态文案，两者互不覆盖。
      clearAnsweredQuestion()
      if (typeof data.text === 'string' && data.text) statusText.value = data.text
      break

    case 'plan.step': {
      clearAnsweredQuestion()
      planRunning.value = true
      // 节点直接展示规划正在做的事；秒表不停，文字后面一直跟着已用时间。
      beginPlanWait(String(data.text || '正在生成检索计划…'), false)
      planDoc.value.push({ key: String(data.key || ''), text: String(data.text || '') })
      break
    }

    case 'plan.result': {
      stopPlanWait()
      clearAnsweredQuestion()
      planRunning.value = false
      // 规划完成（维度确定）后再露出报告区和产出总线，章节数才和本次调研一致。
      planReady.value = true
      const queries = Array.isArray(data.queries) ? data.queries : []
      setNode('plan', 'done', `${queries.length} 条 query`)
      if (data.brief && typeof data.brief === 'object') {
        resolvedBrief.value = data.brief as Record<string, string>
      }
      const dims = Array.isArray(data.dims)
        ? (data.dims as Record<string, unknown>[])
            .map((item) => ({ id: String(item.id || ''), label: String(item.label || '') }))
            .filter((item) => item.id)
        : []
      if (dims.length) applyDims(dims)
      // 每条 query 依次落下：行和箭头都按 120ms 错开，避免 18 个同时起飞叠成一个。
      const runToken = token
      planTimers.forEach((timer) => window.clearTimeout(timer))
      planTimers.length = 0
      queries.forEach((query, index) => {
        const item = query as Record<string, unknown>
        const timer = window.setTimeout(() => {
          if (token !== runToken) return
          appendPlanQuery({
            q: String(item.q || ''),
            kind: String(item.kind || ''),
            label: String(item.label || ''),
            source: String(item.source || ''),
          })
        }, index * 120)
        planTimers.push(timer)
      })
      void revealGraph()
      break
    }

    case 'node.enter': {
      const key = nodeKeyOf(String(data.node || ''))
      if (key && (key !== 'portrait' || hasResume.value)) setNode(key, 'running', String(data.label || '运行中'))
      if (data.node === 'synthesis') setDraft('overview', overviewDraft())
      break
    }

    case 'node.exit': {
      const key = nodeKeyOf(String(data.node || ''))
      if (key && (key !== 'portrait' || hasResume.value)) {
        const state = String(data.state || 'done') === 'error' ? 'error' : 'done'
        setNode(key, state, String(data.text || (state === 'error' ? '失败' : '完成')))
      }
      break
    }

    case 'sources.index': {
      const items = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : []
      items.forEach((item) => {
        const id = String(item.id || '')
        const url = String(item.url || '')
        if (!id || !url) return
        evidenceLinks[id] = {
          id,
          title: String(item.title || url),
          url,
          site: String(item.site || ''),
          published: String(item.published || ''),
          kind: String(item.kind || ''),
          userTag:
            item.userTag && typeof item.userTag === 'object'
              ? (item.userTag as EvidenceLink['userTag'])
              : null,
        }
      })
      break
    }

    case 'collect.skip': {
      const dim = String(data.group || '')
      const site = String(data.site || '未知站点')
      const label = dim ? dimShort(dim, activeDims.value.find((item) => item.id === dim)?.label || '') : ''
      const key = `${dim}:${site}`
      const existing = paneRows.collect.find((item) => item.key === key)
      const reasons = existing?.skipReasons ? [...existing.skipReasons] : []
      for (const part of String(data.reason || '').split('、')) {
        const reason = part.slice(0, 60)
        if (reason && !reasons.includes(reason) && reasons.length < 4) reasons.push(reason)
      }
      upsertRow('collect', {
        key,
        kind: 'collect',
        site: label ? `${label} · ${site}` : site,
        rawSite: site,
        group: dim,
        groupLabel: label,
        got: Number(data.got ?? existing?.got ?? 0),
        total: Number(data.total ?? existing?.total ?? 0),
        skipped: (existing?.skipped || 0) + Number(data.skipped ?? 1),
        skipReasons: reasons,
      })
      break
    }

    case 'collect.chunk': {
      const dim = String(data.group || data.kind || '')
      const site = String(data.site || '未知站点')
      const got = Number(data.got || 0)
      const total = Number(data.total || 0)
      const label = dim ? dimShort(dim, activeDims.value.find((item) => item.id === dim)?.label || '') : ''
      const row = upsertRow('collect', {
        key: `${dim}:${site}`,
        kind: 'collect',
        site: label ? `${label} · ${site}` : site,
        rawSite: site,
        group: dim,
        groupLabel: label,
        got,
        total,
      })
      setNode('collect', 'running', '采集中')
      emitChunk('collect', row)
      break
    }

    case 'collect.done': {
      const total = Number(data.total || 0)
      const planned = Number(data.planned || 0)
      const reason = String(data.reason || '')
      const denominator = Math.max(1, activeDims.value.length)
      collectPages.value += total
      collectPublished.value += Number(data.published || 0)
      collectGroupsDone.value = Math.min(denominator, collectGroupsDone.value + 1)
      nodeStates.collect.progress = (collectGroupsDone.value / denominator) * 100
      setNode('collect', 'running', `${collectPages.value} 页`)
      // 内置来源被启用却 0 页时，把这个维度单独标出来，避免看起来像搜索没搜到。
      if (reason) {
        const dim = String(data.group || '')
        const label = dim ? dimShort(dim, activeDims.value.find((item) => item.id === dim)?.label || '') : ''
        upsertRow('collect', {
          key: `${dim}:__builtin__`,
          kind: 'collect',
          site: label ? `${label} · 内置来源` : '内置来源',
          rawSite: '内置来源',
          group: dim,
          groupLabel: label,
          total: Math.max(planned, total),
          got: total,
          skipped: Math.max(0, planned - total),
          skipReasons: [reason.slice(0, 60)],
        })
      }
      break
    }

    case 'extract.chunk':
      applyExtractChunk(String(data.dim || ''), Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : [])
      break

    case 'extract.done': {
      const dim = String(data.dim || '')
      if (dim === 'synthesis') break
      const tab = dim
      if (!tab) break
      setNode(tab, 'done', `${Number(data.count || 0)} 条`)
      const section = sectionOf(tab)
      if (section) setDraft(section, section === 'overview' ? overviewDraft() : draftFor(tab))
      break
    }

    case 'profile.chunk':
      applyProfileChunk(Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : [])
      break

    case 'profile.done':
      setNode('portrait', 'done', `${Number(data.count || 0)} 项能力`)
      break

    case 'strategy.chunk':
      applyStrategyChunk(Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : [])
      break

    case 'strategy.done':
      strategySeen.value = true
      statusText.value = '策略总结完成'
      break

    case 'report.section.started':
      reportStarted(data)
      break

    case 'delta':
      reportDelta(data)
      break

    case 'report.section':
      reportSectionDone(data)
      break

    case 'report.done': {
      setNode('report', 'done', `${Number(data.count || 0)} 章`)
      reportSections.forEach((section) => {
        if (!section.hidden) {
          section.ready = true
          section.running = false
        }
      })
      break
    }

    case 'ask_question':
      showQuestion(data)
      break

    case 'ask_question_closed':
      closeQuestion(data)
      break

    case 'error':
      if (data.fatal) {
        errorText.value = String(data.message || '调研失败')
        finishRun('failed')
      } else if (data.message) {
        statusText.value = `${String(data.node || '')} ${String(data.message)}`.trim()
      }
      break

    case 'done':
      finishRun(String(data.status || 'done'), String(data.reason || ''))
      break
  }
}

function finishRun(status: string, reason = '') {
  stopPlanWait()
  running.value = false
  finished.value = true
  planRunning.value = false
  question.value = null
  if (status === 'failed') {
    statusText.value = '调研失败'
    if (!errorText.value) errorText.value = '调研失败，请稍后重试'
  } else if (status === 'cancelled') {
    // 规划阶段主动停止（例如没选调研重点），不是失败，也不显示「调研完成」。
    statusText.value = reason || '已停止本轮调研'
    // 规划节点如果还停在秒表状态，要改成终态，否则页面一直像在生成计划。
    if (nodeStates.plan.state === 'running') setNode('plan', 'error', '已停止')
  } else {
    statusText.value = '调研完成'
    saveReportToHistory()
  }
}

/* ------------------------------------------------------------------ */
/* reset + start                                                       */
/* ------------------------------------------------------------------ */

function resetState() {
  token += 1
  historySaved = false
  reportOpen.value = false
  viewingReport.value = null
  historyOpen.value = false
  stopPlanWait()
  running.value = false
  finished.value = false
  errorText.value = ''
  statusText.value = ''
  taskId.value = ''
  question.value = null
  presetOpen.value = false
  planReady.value = false
  tabPinned.value = false
  planDoc.value = []
  planQueries.value = []
  planRunning.value = false
  planTimers.forEach((timer) => window.clearTimeout(timer))
  planTimers.length = 0
  strategySeen.value = false
  clearFlights()
  clearChunkQueue()
  resolvedBrief.value = null
  collectPages.value = 0
  collectPublished.value = 0
  collectGroupsDone.value = 0

  activeDims.value = DEFAULT_DIMS.map((item) => ({ ...item }))
  applyReportSections(DEFAULT_DIMS)
  // strategy 也在标签页里，删掉它的 nodeStates/paneRows 会让模板 `paneRows[tab.key]`
  // 直接读到 undefined，渲染报错后整页停在上一帧——重开调研看起来就是“卡死”。
  const baseNodes = new Set(['plan', 'collect', 'jobs', 'trend', 'strategy', 'portrait', 'report'])
  ;(Object.keys(nodeStates) as NodeKey[]).forEach((key) => {
    if (!baseNodes.has(key)) {
      delete nodeStates[key]
      delete paneRows[key]
      delete unread[key]
      delete revealed[key]
      return
    }
    const node = nodeStates[key]
    node.state = 'idle'
    node.unread = false
    node.progress = 0
    node.born = key === 'plan'
  })
  nodeStates.plan.text = '等待开始'
  nodeStates.collect.text = '等待'
  nodeStates.jobs.text = '等待'
  nodeStates.trend.text = '等待'
  nodeStates.portrait.text = hasResume.value ? '等待' : '等待 -'
  nodeStates.report.text = '等待'
  if (nodeStates.strategy) nodeStates.strategy.text = '等待'

  ;(Object.keys(paneRows) as TabKey[]).forEach((key) => {
    paneRows[key].splice(0, paneRows[key].length)
    unread[key] = 0
  })
  // 新一轮调研回到各页签的默认卡片，避免沿用上一轮选过的模块。
  resetPlan()
  resetCollect()
  resetJobs()
  dynamic.reset()
  resetTrend()
  resetPortrait()
  resetStrategy()

  reportSections.forEach((section) => {
    section.ready = false
    section.running = false
    section.status = 'idle'
    section.draft = ''
    section.prose = ''
    section.sources = 0
    section.sourceLinks = []
    section.hidden = section.id === 'profile' ? !hasResume.value : false
  })
  Object.keys(evidenceLinks).forEach((key) => delete evidenceLinks[key])

  ;(Object.keys(revealed) as NodeKey[]).forEach((key) => {
    revealed[key] = key === 'plan'
  })

  busShow.value = false
  busTag.value = ''
  busText.value = ''
  busUnwatched.value = false
  busHit.value = false
  highlight.key = ''
  highlight.tab = ''
  activeTab.value = hasResume.value ? 'collect' : 'collect'
  void nextTick(() => {
    layoutEdges()
  })
}

/* ------------------------------------------------------------------ */
/* 结果快照：刷新 / 切页后恢复上一轮调研                                 */
/* ------------------------------------------------------------------ */

const SNAPSHOT_KEY = 'smartcv-market-run'
const SNAPSHOT_VERSION = 1

interface MarketSnapshot {
  v: number
  savedAt: number
  config: {
    targetRole: string
    direction: string
    resumeChoice: string
    collapsed: boolean
    roleInfo: MarketRoleInference | null
    roleOptions: MarketRoleOption[]
  }
  run: {
    finished: boolean
    wasRunning: boolean
    statusText: string
    errorText: string
    hasResume: boolean
    planReady: boolean
    strategySeen: boolean
    planDoc: { key: string; text: string }[]
    planQueries: { q: string; kind: string; label: string; source: string }[]
    resolvedBrief: Record<string, string> | null
    collectPages: number
    collectPublished: number
    collectGroupsDone: number
    activeDims: DimInfo[]
    nodeStates: Record<string, NodeState>
    paneRows: Record<string, PanelRow[]>
    evidenceLinks: Record<string, EvidenceLink>
    reportSections: ReportSectionState[]
    activeTab: string
    tabPinned: boolean
  } & CategoryRunSnapshot
}

/** reactive 代理不能直接进 localStorage，先转成纯 JSON 数据。 */
function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/** 恢复快照期间暂停保存和联动 watcher，避免把恢复动作当成用户操作。 */
let restoringSnapshot = false
let snapshotTimer: number | null = null

function buildSnapshot(): MarketSnapshot {
  return {
    v: SNAPSHOT_VERSION,
    savedAt: Date.now(),
    config: {
      targetRole: targetRole.value,
      direction: direction.value,
      resumeChoice: resumeChoice.value,
      collapsed: collapsed.value,
      roleInfo: plain(roleInfo.value),
      roleOptions: plain(roleOptions.value),
    },
    run: {
      finished: finished.value,
      wasRunning: running.value,
      statusText: statusText.value,
      errorText: errorText.value,
      hasResume: hasResume.value,
      planReady: planReady.value,
      strategySeen: strategySeen.value,
      planDoc: plain(planDoc.value),
      planQueries: plain(planQueries.value),
      resolvedBrief: plain(resolvedBrief.value),
      collectPages: collectPages.value,
      collectPublished: collectPublished.value,
      collectGroupsDone: collectGroupsDone.value,
      activeDims: plain(activeDims.value),
      nodeStates: plain(nodeStates),
      paneRows: plain(paneRows),
      evidenceLinks: plain(evidenceLinks),
      reportSections: plain(reportSections),
      activeTab: activeTab.value,
      tabPinned: tabPinned.value,
      ...snapshotPlan(),
      ...snapshotCollect(),
      ...snapshotJobs(),
      ...dynamic.snapshot(),
      ...snapshotTrend(),
      ...snapshotPortrait(),
      ...snapshotStrategy(),
    },
  }
}

/** 只有已经产出内容（规划完成或流程结束）的调研才值得存，避免存下空壳。 */
function canSnapshot(): boolean {
  return started.value && (planReady.value || finished.value)
}

function clearSnapshot() {
  if (snapshotTimer !== null) {
    window.clearTimeout(snapshotTimer)
    snapshotTimer = null
  }
  try {
    localStorage.removeItem(SNAPSHOT_KEY)
  } catch {
    /* 隐私模式下 localStorage 不可用，忽略 */
  }
}

function saveSnapshotNow() {
  if (restoringSnapshot || !canSnapshot()) return
  try {
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(buildSnapshot()))
  } catch {
    /* 配额不足 / 隐私模式：放弃持久化，不影响本次调研 */
  }
}

/** SSE chunk 很密，合并成一次写盘；刷新时靠 pagehide 再补一次。 */
function scheduleSnapshotSave() {
  if (restoringSnapshot || !canSnapshot()) return
  if (snapshotTimer !== null) window.clearTimeout(snapshotTimer)
  snapshotTimer = window.setTimeout(() => {
    snapshotTimer = null
    saveSnapshotNow()
  }, 800)
}

/**
 * 把上次快照贴回页面。只恢复结果与选择，不重连后端任务：
 * 刷新时 SSE 已断，快照里仍在运行中的节点标注为「刷新中断」。
 */
function restoreSnapshot(): boolean {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(SNAPSHOT_KEY)
  } catch {
    return false
  }
  if (!raw) return false
  let data: MarketSnapshot
  try {
    data = JSON.parse(raw) as MarketSnapshot
  } catch {
    return false
  }
  if (!data || data.v !== SNAPSHOT_VERSION || !data.run) return false
  const run = data.run
  const cfg = data.config || ({} as MarketSnapshot['config'])
  const sections = Array.isArray(run.reportSections)
    ? run.reportSections.filter((section) => section && typeof section.id === 'string')
    : []
  if (!(run.planReady || run.finished)) return false
  if (!Array.isArray(run.activeDims) || !Array.isArray(run.paneRows?.jobs) || !sections.length) {
    return false
  }

  restoringSnapshot = true

  targetRole.value = typeof cfg.targetRole === 'string' ? cfg.targetRole : ''
  direction.value = typeof cfg.direction === 'string' ? cfg.direction : ''
  resumeChoice.value = typeof cfg.resumeChoice === 'string' ? cfg.resumeChoice : ''
  collapsed.value = Boolean(cfg.collapsed)
  roleInfo.value = cfg.roleInfo && typeof cfg.roleInfo === 'object' ? cfg.roleInfo : null
  roleOptions.value = Array.isArray(cfg.roleOptions)
    ? cfg.roleOptions.filter((item) => item && typeof item.title === 'string')
    : []

  started.value = true
  finished.value = true
  running.value = false
  planRunning.value = false
  question.value = null
  statusText.value = run.wasRunning
    ? '上次调研在刷新时中断，已保留当前结果'
    : typeof run.statusText === 'string' && run.statusText
      ? run.statusText
      : '调研完成'
  errorText.value = run.wasRunning ? '' : typeof run.errorText === 'string' ? run.errorText : ''
  hasResume.value = Boolean(run.hasResume)
  planReady.value = Boolean(run.planReady)
  strategySeen.value = Boolean(run.strategySeen)
  planDoc.value = Array.isArray(run.planDoc)
    ? run.planDoc.filter((item) => item && typeof item.text === 'string').map((item) => ({ key: String(item.key || ''), text: item.text }))
    : []
  planQueries.value = Array.isArray(run.planQueries)
    ? run.planQueries.filter((item) => item && typeof item.q === 'string')
    : []
  resolvedBrief.value = run.resolvedBrief && typeof run.resolvedBrief === 'object' ? run.resolvedBrief : null
  collectPages.value = Number(run.collectPages) || 0
  collectPublished.value = Number(run.collectPublished) || 0
  collectGroupsDone.value = Number(run.collectGroupsDone) || 0
  activeDims.value = run.activeDims.length
    ? run.activeDims
        .filter((dim) => dim && typeof dim.id === 'string')
        .map((dim) => ({ id: dim.id, label: typeof dim.label === 'string' ? dim.label : '' }))
    : DEFAULT_DIMS.map((item) => ({ ...item }))

  // 流程节点：保留了 previous run 的 born / 进度；运行中被刷新打断的节点不再显示为运行中。
  ;(Object.keys(nodeStates) as string[]).forEach((key) => delete nodeStates[key])
  const savedNodes = run.nodeStates && typeof run.nodeStates === 'object' ? run.nodeStates : {}
  Object.entries(savedNodes).forEach(([key, value]) => {
    if (!value || typeof value !== 'object') return
    const interrupted = value.state === 'running'
    nodeStates[key] = {
      state: interrupted ? 'error' : value.state === 'done' || value.state === 'error' ? value.state : 'idle',
      text: interrupted ? '刷新中断' : typeof value.text === 'string' ? value.text : '等待',
      born: Boolean(value.born),
      unread: false,
      progress: Number(value.progress) || 0,
    }
  })
  ;['plan', 'collect', 'jobs', 'trend', 'portrait', 'report'].forEach((key) => {
    if (!nodeStates[key]) {
      nodeStates[key] = { state: 'idle', text: '等待', born: key === 'plan', unread: false, progress: 0 }
    }
  })
  activeDims.value.forEach((dim) => {
    if (!nodeStates[dim.id]) {
      nodeStates[dim.id] = { state: 'idle', text: '等待', born: false, unread: false, progress: 0 }
    }
  })

  // 面板行、证据、未读：整表替换，保持 reactive 引用不变。
  ;(Object.keys(paneRows) as string[]).forEach((key) => paneRows[key].splice(0))
  Object.entries(run.paneRows).forEach(([key, rows]) => {
    if (!Array.isArray(rows)) return
    if (!paneRows[key]) paneRows[key] = []
    paneRows[key].splice(0, paneRows[key].length, ...rows)
  })
  ;['plan', 'collect', 'jobs', 'trend', 'strategy', 'portrait'].forEach((key) => {
    if (!Array.isArray(paneRows[key])) paneRows[key] = []
  })
  activeDims.value.forEach((dim) => {
    if (!Array.isArray(paneRows[dim.id])) paneRows[dim.id] = []
  })

  ;(Object.keys(evidenceLinks) as string[]).forEach((key) => delete evidenceLinks[key])
  Object.entries(run.evidenceLinks || {}).forEach(([key, link]) => {
    if (link && typeof link === 'object') evidenceLinks[key] = link
  })

  ;(Object.keys(unread) as string[]).forEach((key) => {
    unread[key] = 0
  })
  activeDims.value.forEach((dim) => {
    if (unread[dim.id] === undefined) unread[dim.id] = 0
  })

  // 有报告正文时一定让「汇总报告」节点出现：刷新可能发生在节点入场动画之前。
  if (sections.some((section) => section.ready || section.prose)) {
    nodeStates.report.born = true
  }

  reportSections.splice(
    0,
    reportSections.length,
    ...sections.map((section) => ({
      ...section,
      running: false,
      status:
        section.status === 'running'
          ? section.ready
            ? 'ready'
            : 'failed'
          : section.status || 'idle',
      sourceLinks: Array.isArray(section.sourceLinks) ? section.sourceLinks : [],
    })),
  )

  Object.keys(nodeStates).forEach((key) => {
    revealed[key] = Boolean(nodeStates[key]?.born)
  })
  restorePlan(run)
  restoreCollect(run)
  restoreJobs(run)
  dynamic.restore(run)
  restoreTrend(run)
  restorePortrait(run)
  restoreStrategy(run)

  tabPinned.value = Boolean(run.tabPinned)
  const savedTab = typeof run.activeTab === 'string' ? run.activeTab : 'collect'
  activeTab.value = shownTabs.value.some((tab) => tab.key === savedTab) ? savedTab : 'collect'

  // 等首轮 watcher 全部跑完再放开，恢复过程不会触发保存 / 联动。
  void nextTick(() => {
    restoringSnapshot = false
  })
  return true
}

// 调研过程中任何结果变化都进入快照；合并 800ms，避免每个 chunk 都写一遍。
watch(
  [
    targetRole,
    resumeChoice,
    collapsed,
    roleInfo,
    roleOptions,
    started,
    finished,
    running,
    statusText,
    errorText,
    hasResume,
    planReady,
    strategySeen,
    planDoc,
    planQueries,
    resolvedBrief,
    collectPages,
    collectPublished,
    collectGroupsDone,
    activeDims,
    nodeStates,
    paneRows,
    evidenceLinks,
    unread,
    reportSections,
    activeTab,
    tabPinned,
    planModuleKey,
    collectView,
    distView,
    collectOpen,
    jobsModuleKey,
    dynamic.moduleKeys,
    trendView,
    portraitView,
    portraitSkillView,
    portraitProjectView,
    portraitGapView,
    strategyModuleKey,
  ],
  () => scheduleSnapshotSave(),
  { deep: true },
)

async function resolveResume(): Promise<{ ok: boolean; resume: unknown[] | null }> {
  if (!resumeChoice.value) return { ok: true, resume: null }
  if (resumeChoice.value === '__current__') {
    if (!resumeStore.resume.length) {
      message.warning('当前简历还是空的，请先在编辑器里添加内容')
      return { ok: false, resume: null }
    }
    return { ok: true, resume: JSON.parse(JSON.stringify(resumeStore.resume)) as unknown[] }
  }
  const data = await documents.readFileSnapshot(resumeChoice.value)
  if (!Array.isArray(data)) {
    if (data === null) message.warning('无法读取备份简历，请确认已绑定备份文件夹并授权')
    else message.error('选中的文件不是合法的简历 JSON')
    return { ok: false, resume: null }
  }
  return { ok: true, resume: JSON.parse(JSON.stringify(data)) as unknown[] }
}

async function start() {
  // 任何一次点击都必须立刻清空重开：不做「正在准备，忽略这次点击」的拦截，
  // 旧的准备流程靠 token 作废，最后一次点击永远生效。
  if (!targetRole.value.trim() && !resumeChoice.value) {
    message.warning('请填写目标岗位，或选择一份简历')
    return
  }
  const provider: ProviderSettings = getProviderSettings()
  const missing = missingProviderFields(provider)
  if (missing.length) {
    message.warning(`请先在「高级设置」配置 ${missing.join('、')}`)
    return
  }

  // 点下去就立刻掐断旧的一轮、清空整页，不等读简历，也不等旧流结束。
  const previousTaskId = taskId.value
  const previous = controller
  controller = null
  previous?.abort()
  if (previousTaskId) void cancelMarket(previousTaskId).catch(() => undefined)

  // 新的一轮覆盖旧结果：旧快照同时作废，避免刷新后贴回上一轮。
  clearSnapshot()
  resetState()
  const runToken = token
  collapsed.value = true
  started.value = true
  running.value = true
  statusText.value = '正在启动调研…'
  setNode('plan', 'running', '正在启动调研…')

  starting = true
  let resolved: Awaited<ReturnType<typeof resolveResume>>
  try {
    resolved = await resolveResume()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '读取简历失败')
    if (token === runToken) {
      errorText.value = err instanceof Error ? err.message : '读取简历失败'
      running.value = false
      finished.value = true
      statusText.value = '调研失败'
    }
    return
  } finally {
    // 只护住「准备」这一段；开跑之后必须允许再次点击重开。
    starting = false
  }
  // 准备期间用户又点了一次重新调研：这一轮作废。
  if (token !== runToken) return
  if (!resolved.ok) {
    running.value = false
    finished.value = true
    statusText.value = '启动失败'
    return
  }

  // 来源库以备份文件夹里的 market-sources.json 为准，开跑前补一次读取，
  // 保证用户刚在设置里改的标签也能带进这一轮。
  await marketSources.load()
  if (token !== runToken) return

  hasResume.value = Boolean(resolved.resume)
  applyResumeMode(hasResume.value)
  if (!resolved.resume) nodeStates.portrait.text = '等待'

  controller = new AbortController()
  const signal = controller.signal
  let sawDone = false

  try {
    await streamMarket(
      {
        targetRole: targetRole.value.trim(),
        city: roleInfo.value?.city.trim() ?? '',
        experience: roleInfo.value?.experience.trim() ?? '',
        direction: direction.value.trim(),
        timeRange: marketResearch.value.timeRange,
        // 复制一份，避免请求对象和本地存储共享同一个引用。
        pagesPerDim: { ...marketResearch.value.pagesPerDim },
        urlsPerDim: marketResearch.value.urlsPerDim,
        fetchMode: marketResearch.value.fetchMode,
        collector: collectorPayload(marketResearch.value),
        sources: { ...marketResearch.value.sources },
        extraUrls: marketSources.payloadEntries,
        resume: resolved.resume,
        provider,
      },
      {
        // 旧流被 abort 后可能还有缓冲事件到达，按本轮 token 丢掉。
        onTaskId: (id) => {
          if (token === runToken) taskId.value = id
        },
        onEvent: (event) => {
          if (token !== runToken) return
          // 单个事件处理出错不能拖垮整条流，否则页面会停在最后一个已处理的事件上。
          try {
            handleEvent(event)
          } catch (err) {
            console.error('[market] 事件处理失败', event.type, err)
          }
          if (event.type === 'done') sawDone = true
        },
      },
      signal,
    )
    if (token === runToken && running.value && !signal.aborted) {
      if (sawDone) {
        finishRun('done')
      } else {
        // 流没有正常收尾就断了：不要把「连接中断」说成「调研完成」。
        stopPlanWait()
        running.value = false
        finished.value = true
        statusText.value = '连接已中断'
        errorText.value = '与后端的连接中断了，请点「重新调研」重新开始'
        if (taskId.value) void cancelMarket(taskId.value).catch(() => undefined)
      }
    }
  } catch (err) {
    if (signal.aborted || token !== runToken) return
    stopPlanWait()
    const text = err instanceof Error ? err.message : String(err)
    errorText.value = text
    running.value = false
    finished.value = true
    statusText.value = '调研失败'
    message.error(`市场洞察失败：${text}`)
    // 连接断了但后端任务可能还活着，顺手取消，避免占着模型空跑。
    if (taskId.value) void cancelMarket(taskId.value).catch(() => undefined)
  } finally {
    if (controller?.signal === signal) controller = null
  }
}

/* ------------------------------------------------------------------ */
/* lifecycle                                                           */
/* ------------------------------------------------------------------ */

onMounted(() => {
  loadReportHistory()
  void marketSources.load()
  // 刷新 / 切页回来先贴回上一轮结果；没有快照才走全新的初始状态。
  if (!restoreSnapshot()) {
    activeTab.value = 'collect'
    nodeStates.portrait.text = '等待'
    applyResumeMode(hasResume.value)
  }
  resizeHandler = () => {
    scheduleEdges()
    if (question.value) scheduleAskPosition()
  }
  window.addEventListener('resize', resizeHandler)
  // 小屏页面可滚动，气泡跟随规划节点重新定位。
  window.addEventListener('scroll', resizeHandler, true)
  // 刷新不等 800ms 的合并窗口，直接补写一次最新结果。
  window.addEventListener('pagehide', saveSnapshotNow)
  void nextTick(() => {
    layoutEdges()
  })
})

/**
 * keep-alive 缓存本页：切走时组件不销毁，SSE 连接保持，调研在后台继续跑。
 * 切回来时 DOM 重新挂回文档，之前量到的坐标全部作废，需要重画连线、重新贴合反问气泡。
 */
onActivated(() => {
  void nextTick(() => {
    layoutEdges()
    if (question.value) scheduleAskPosition()
  })
})

/** 离开页签只收起浮层（报告弹窗、历史菜单、岗位下拉），不影响正在跑的调研。 */
onDeactivated(() => {
  reportOpen.value = false
  historyOpen.value = false
  presetOpen.value = false
})

onBeforeUnmount(() => {
  saveSnapshotNow()
  if (snapshotTimer !== null) {
    window.clearTimeout(snapshotTimer)
    snapshotTimer = null
  }
  window.removeEventListener('pagehide', saveSnapshotNow)
  controller?.abort()
  document.removeEventListener('pointerdown', closePresetOnOutside, true)
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    window.removeEventListener('scroll', resizeHandler, true)
  }
  if (askRaf) window.cancelAnimationFrame(askRaf)
  askRaf = 0
  askObserver?.disconnect()
  askObserver = null
  stopPlanWait()
  window.clearTimeout(busTimer)
  window.clearTimeout(flashTimer)
  window.clearTimeout(highlightTimer)
  planTimers.forEach((timer) => window.clearTimeout(timer))
  planTimers.length = 0
  clearFlights()
  clearChunkQueue()
})
</script>

<template>
  <div class="market-page shell">
    <header class="topbar">
      <span class="tb-title">市场洞察</span>
      <span class="tb-tag">{{ running ? '调研中' : finished ? '已结束' : 'Agent 流水线' }}</span>
      <span v-if="errorText" class="tb-hint tb-error">{{ errorText }}</span>
      <span
        v-else-if="finished && !running && statusText && statusText !== '调研完成'"
        class="tb-hint"
      >{{ statusText }}</span>
    </header>

    <main class="grid" :class="{ 'plan-only': !planReady }">
      <section class="left">
        <div class="config" :data-collapsed="collapsed ? '1' : '0'">
          <div class="cfg-fields">
            <div class="field">
              <span>目标岗位</span>
              <div ref="roleComboEl" class="role-combo">
                <input
                  v-model="targetRole"
                  :disabled="running"
                  placeholder="例如：高级前端工程师"
                  aria-label="目标岗位"
                  @keyup.enter="start"
                  @keydown.esc="presetOpen = false"
                />
                <button
                  type="button"
                  class="role-combo-toggle"
                  :class="{ open: presetOpen }"
                  :disabled="running"
                  aria-label="选择常用岗位"
                  :aria-expanded="presetOpen"
                  @click="presetOpen = !presetOpen"
                >
                  <IconGlyph name="chevron-down" :size="13" />
                </button>
                <div v-if="presetOpen" class="role-menu">
                  <div v-for="group in ROLE_PRESET_GROUPS" :key="group.label" class="role-menu-group">
                    <span class="role-menu-label">{{ group.label }}</span>
                    <button
                      v-for="role in group.roles"
                      :key="role"
                      type="button"
                      class="role-menu-item"
                      :class="{ active: targetRole === role }"
                      @click="pickRole(role)"
                    >
                      <span>{{ role }}</span>
                      <IconGlyph v-if="targetRole === role" name="check" :size="12" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div class="field">
              <span>简历画像</span>
              <div class="field-control">
                <select v-model="resumeChoice" :disabled="running">
                  <option value="">不使用简历</option>
                  <option v-if="hasCurrentResume" value="__current__">当前简历（{{ resumeName }}）</option>
                  <option v-for="file in backupFiles" :key="file.name" :value="file.name">
                    {{ file.title }}
                  </option>
                </select>
                <span class="role-ai-wrap" title="使用AI 从简历反推">
                  <button
                    type="button"
                    class="role-ai-btn"
                    :class="{ idle: !resumeChoice, loading: roleLoading }"
                    :disabled="!resumeChoice || roleLoading || running"
                    aria-label="使用AI 从简历反推"
                    @click="inferRoles"
                  >
                    <IconGlyph name="sparkles" :size="14" />
                  </button>
                </span>
              </div>
            </div>
            <div class="field">
              <span>希望 AI 回答</span>
              <input
                v-model="direction"
                :disabled="running"
                placeholder="例如：这个岗位需要哪些能力？薪资大概多少？（选填）"
                aria-label="希望 AI 回答的内容"
                @keyup.enter="start"
              />
            </div>
            <div v-if="roleOptions.length || roleTags.length" class="role-infer">
              <div v-if="roleTags.length" class="role-tags">
                <span v-for="tag in roleTags" :key="tag.key" class="role-tag">
                  <span class="role-tag-label">{{ tag.label }}</span>
                  <span class="role-tag-value">{{ tag.value }}</span>
                </span>
              </div>
              <div v-if="roleOptions.length" class="role-chips">
                <button
                  v-for="option in roleOptions"
                  :key="option.title"
                  type="button"
                  class="role-chip"
                  :class="{ active: targetRole === option.title }"
                  :title="option.reason"
                  @click="chooseRole(option.title)"
                >
                  <span class="role-title">{{ option.title }}</span>
                  <span v-if="option.reason" class="role-reason">{{ option.reason }}</span>
                </button>
              </div>
            </div>
          </div>
          <div class="cfg-foot">
            <button
              v-if="started"
              type="button"
              class="btn"
              :disabled="running"
              @click="collapsed = true"
            >
              收起
            </button>
            <button
              type="button"
              class="btn primary"
              :disabled="!canStart"
              :title="running ? '会中断当前这一轮，按最新配置重新开始' : ''"
              @click="start"
            >
              {{ started ? '重新调研' : '开始调研' }}
            </button>
          </div>
          <div class="cfg-summary">
            <div class="cfg-summary-head">
              <span class="dot" :class="{ live: running }"></span>
              <span class="cfg-summary-role" :title="summaryRole">{{ summaryRole }}</span>
              <div class="cfg-summary-actions">
                <!-- 调研中也留一个出口：不用等这一轮跑完就能重新开始。 -->
                <button
                  v-if="started"
                  type="button"
                  class="link restart"
                  :title="running ? '中断当前这一轮，按同样配置重新开始' : '按当前配置再跑一轮'"
                  @click="start"
                >
                  重新调研
                </button>
                <button type="button" class="link" :disabled="running" @click="collapsed = false">修改</button>
              </div>
            </div>
            <div class="cfg-summary-meta">
              <span v-for="item in summaryMeta" :key="item.label" class="cfg-chip">
                <b>{{ item.label }}</b>{{ item.value }}
              </span>
            </div>
          </div>
        </div>

        <div class="flow">
          <div class="flow-head">
            <span class="flow-title">流程</span>
            <span class="flow-legend">
              <span class="legend-item"><i class="legend-line"></i>主链</span>
              <span class="legend-item"><i class="legend-line dashed"></i>依赖简历</span>
              <span class="legend-item"><i class="legend-dot running"></i>执行中</span>
              <span class="legend-item"><i class="legend-dot done"></i>已完成</span>
            </span>
          </div>

          <div
            ref="canvasEl"
            class="canvas"
            :data-resume="hasResume ? '1' : '0'"
            :style="{ gridTemplateRows: `repeat(${canvasRows}, 40px)` }"
          >
            <svg ref="edgesEl" class="edges" aria-hidden="true">
              <defs>
                <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse">
                  <path d="M0 0 L8 4 L0 8 z" fill="#d3d6df"></path>
                </marker>
                <marker id="arrowDone" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse">
                  <path d="M0 0 L8 4 L0 8 z" fill="#3f8f5a"></path>
                </marker>
                <marker id="arrowActive" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse">
                  <path d="M0 0 L8 4 L0 8 z" fill="#4753c7"></path>
                </marker>
              </defs>
            </svg>

            <button
              v-for="node in graphNodes"
              :key="node.key"
              type="button"
              class="gnode"
              :data-node="node.key"
              :data-state="nodeStates[node.key].state"
              :data-born="nodeStates[node.key].born ? '1' : '0'"
              :data-unread="nodeStates[node.key].unread ? '1' : undefined"
              :data-active="activeTab === node.key ? '1' : undefined"
              :style="{ gridArea: node.area }"
              @click="selectNode(node.key)"
            >
              <span class="gname">{{ node.label }}</span>
              <span class="gstate">{{ nodeStates[node.key].text }}</span>
              <span v-if="node.key === 'collect'" class="gbar">
                <i :style="{ width: `${nodeStates.collect.progress}%` }"></i>
              </span>
            </button>
          </div>
        </div>

        <!-- 报告改为弹窗后，左栏底部用调研档案填补空白，同时给出历史报告入口。 -->
        <section class="archive">
          <div class="archive-head">
            <span class="archive-title">调研档案</span>
            <span class="archive-note">
              {{ reportHistory.length ? `浏览器保留最近 ${reportHistory.length} 份` : '暂无历史报告' }}
            </span>
          </div>
          <button
            v-for="item in reportHistory"
            :key="item.id"
            type="button"
            class="archive-item"
            @click="openHistoryReport(item)"
          >
            <span class="archive-item-main">
              <span class="archive-role">{{ item.targetRole || '未命名调研' }}</span>
              <span class="archive-meta">{{ formatHistoryTime(item.savedAt) }} · {{ item.ready }} 章就绪</span>
            </span>
            <span class="archive-open">查看<IconGlyph name="arrow-right" :size="12" /></span>
          </button>
          <div v-if="!reportHistory.length" class="archive-empty">
            <IconGlyph name="history" :size="18" />
            <p>完成调研后，最近 3 份报告会保存在浏览器里，随时可以回来查看。</p>
          </div>
        </section>

      </section>

      <Teleport to="body">
        <div v-if="reportOpen" class="report-modal" @click.self="reportOpen = false">
          <div class="report-modal-panel" role="dialog" aria-modal="true" aria-label="调研报告">
            <header class="report-modal-head">
              <div class="report-modal-titlebox">
                <span class="report-modal-title">调研报告</span>
                <span class="report-modal-sub">
                  <template v-if="viewingReport">
                    历史 · {{ formatHistoryTime(viewingReport.savedAt) }} · {{ viewingReport.targetRole || '未命名调研' }} ·
                  </template>
                  {{ displayProgressText }}
                </span>
              </div>
              <div class="report-history" @click.stop>
                <button
                  type="button"
                  class="report-history-btn"
                  :class="{ active: historyOpen }"
                  :aria-expanded="historyOpen"
                  @click="historyOpen = !historyOpen"
                >
                  <IconGlyph name="history" :size="14" />
                  <span>最近报告</span>
                </button>
                <div v-if="historyOpen" class="report-history-menu">
                  <button
                    type="button"
                    class="report-history-item"
                    :class="{ active: !viewingReport }"
                    @click="viewCurrentReport"
                  >
                    <span class="rh-role">本次报告</span>
                    <span class="rh-time">{{ reportProgressText }}</span>
                  </button>
                  <button
                    v-for="item in reportHistory"
                    :key="item.id"
                    type="button"
                    class="report-history-item"
                    :class="{ active: viewingReport?.id === item.id }"
                    @click="viewHistoryReport(item)"
                  >
                    <span class="rh-role">{{ item.targetRole || '未命名调研' }}</span>
                    <span class="rh-time">
                      {{ formatHistoryTime(item.savedAt) }} · {{ item.ready }}/{{ item.total }} 就绪
                    </span>
                  </button>
                  <p v-if="!reportHistory.length" class="report-history-empty">
                    完成一次调研后，这里会保留最近 3 次报告。
                  </p>
                </div>
              </div>
              <button type="button" class="report-modal-close" aria-label="关闭报告" @click="reportOpen = false">
                <IconGlyph name="x" :size="16" />
              </button>
            </header>
            <div class="report-modal-main">
              <nav class="report-nav" aria-label="报告目录">
                <button
                  v-for="section in visibleDisplaySections"
                  :key="section.id"
                  type="button"
                  class="report-nav-item"
                  :class="{ active: reportFocusSec === section.id }"
                  :data-ready="section.ready ? '1' : '0'"
                  @click="focusSection(section.id)"
                >
                  <span class="report-nav-name">{{ section.title }}</span>
                  <span class="report-nav-state">{{ sectionStateText(section) }}</span>
                </button>
              </nav>
              <div ref="reportBodyEl" class="report-modal-body">
                <section
                  v-for="section in modalSections"
                  :key="section.id"
                  class="rsec"
                  :data-sec="section.id"
                  :data-ready="section.ready ? '1' : '0'"
                  :data-running="section.running ? '1' : '0'"
                  :hidden="section.hidden"
                >
                  <div v-if="!section.prose" class="rsec-draft" :class="{ has: !!section.draft }">
                    {{ section.draft }}
                  </div>
                  <div v-if="section.prose" class="rsec-prose md-body" v-html="renderMarkdown(section.prose)"></div>
                  <div v-if="section.prose && section.sourceLinks.length" class="rsec-src">
                    <span class="rsec-src-label">来源 {{ section.sourceLinks.length }} 条</span>
                    <a
                      v-for="src in section.sourceLinks"
                      :key="src.id"
                      class="rsec-src-link"
                      :href="src.url"
                      target="_blank"
                      rel="noopener noreferrer"
                      :title="linkTitle(src)"
                    >{{ src.id }} {{ src.site || src.title }}<span v-if="src.published" class="src-date">·{{ shortDate(src.published) }}</span></a>
                  </div>
                </section>
              </div>
            </div>
          </div>
        </div>
      </Teleport>

      <aside v-if="planReady" class="right">
        <div ref="busEl" class="bus" :class="{ hit: busHit }">
          <span class="bus-label">产出总线</span>
          <span class="bus-note" :class="{ show: busShow, unwatched: busUnwatched }">
            <span v-if="busTag" class="tag">{{ busTag }}</span>{{ busText }}
          </span>
        </div>
        <div class="right-body">
          <nav ref="tabsEl" class="cat-rail" aria-label="产出总线下类别">
            <TransitionGroup tag="div" name="tab-draw" class="cat-rail-list" appear>
              <section
                v-for="group in railGroups"
                :key="group.key"
                class="cat-group"
                :class="{ open: group.containsActive }"
              >
                <button
                  type="button"
                  class="cat-item top"
                  :class="{
                    active: activeTab === group.key,
                    flash: flashKey === group.key,
                    idle: group.status.tone === 'idle',
                  }"
                  :data-tab="group.key"
                  :aria-current="activeTab === group.key ? 'page' : undefined"
                  @click="setActiveTab(group.key)"
                >
                  <span class="label">{{ group.label }}</span>
                  <span v-if="group.badge" class="mini-badge">{{ group.badge }}</span>
                  <span class="cat-status" :class="group.status.tone">{{ group.status.text }}</span>
                </button>

                <div v-if="group.children.length" class="cat-children">
                  <button
                    v-for="child in group.children"
                    :key="child.key"
                    type="button"
                    class="cat-item child"
                    :class="{ active: activeTab === child.key, flash: flashKey === child.key }"
                    :data-tab="child.key"
                    :title="`${child.label} · ${child.status.text}`"
                    :aria-current="activeTab === child.key ? 'page' : undefined"
                    @click="setActiveTab(child.key)"
                  >
                    <span class="label">{{ child.label }}</span>
                    <span v-if="child.badge" class="mini-badge">{{ child.badge }}</span>
                  </button>
                </div>
              </section>
            </TransitionGroup>
          </nav>

          <PlanCategory
            v-if="activeTab === 'plan'"
            :card="planCard"
            :modules="planModules"
            :active-module-key="planActiveModuleKey"
            :group="planShownGroup"
            :running="planRunning"
            :highlight-key="highlight.tab === 'plan' ? highlight.key : ''"
            @select="setPlanModule"
          />

          <CollectCategory
            v-else-if="activeTab === 'collect'"
            :card="collectCard"
            :modules="collectModules"
            :active-module-key="collectView"
            :groups="collectShownGroups"
            :distribution="collectDistribution"
            :dist-key="DIST_MODULE_KEY"
            :dist-view="distView"
            :open="collectOpen"
            :highlight-key="highlight.tab === 'collect' ? highlight.key : ''"
            :has-rows="collectHasRows"
            :empty-text="collectEmptyText"
            :sources-of="collectSources"
            :source-count-of="collectSourceCount"
            :num-title="collectNumTitle"
            @select="setCollectModule"
            @toggle="toggleCollect"
            @update:dist-view="setCollectDistView"
          />

          <JobsCategory
            v-else-if="activeTab === 'jobs'"
            :card="jobsCard"
            :modules="jobsModules"
            :active-module-key="jobsActiveModuleKey"
            :active-module="jobsActiveModule"
            :module-rows="jobsModuleRows"
            :row-groups="jobsRowGroups"
            :job-skill-rows="jobSkillRows"
            :job-must-have-count="jobMustHaveCount"
            :has-rows="jobsHasRows"
            :empty-text="jobsEmptyText"
            :highlight-key="highlight.tab === 'jobs' ? highlight.key : ''"
            :links-of="linksOf"
            :more-links="moreLinks"
            @select="setJobsModule"
          />

          <TrendCategory
            v-else-if="activeTab === 'trend'"
            :card="trendCard"
            :modules="trendModules"
            :active-module="trendActiveModule"
            :active-module-key="trendActiveModuleKey"
            :view="trendView"
            :timeline="trendTimeline"
            :timeline-dated="trendTimelineDated"
            :analysis="trendAnalysis"
            :extra-groups="trendOtherGroups"
            :extra-rows="trendExtraRows"
            :release-groups="trendReleaseGroups"
            :release-rows="trendReleaseRows"
            :synthesis-rows="trendSynthesisRows"
            :has-rows="trendHasRows"
            :empty-text="trendEmptyText"
            :highlight-key="highlight.tab === 'trend' ? highlight.key : ''"
            :links-of="linksOf"
            :more-links="moreLinks"
            @select="setTrendModule"
          />

          <PortraitCategory
            v-else-if="activeTab === 'portrait'"
            :card="portraitCard"
            :modules="portraitModules"
            :active-module-key="portraitActiveModuleKey"
            :sections="portraitSections"
            :has-rows="portraitHasRows"
            :empty-text="portraitEmptyText"
            :skill-view="portraitSkillView"
            :project-view="portraitProjectView"
            :gap-view="portraitGapView"
            @select="setPortraitModule"
            @skill-view="setPortraitSkillView"
            @project-view="setPortraitProjectView"
            @gap-view="setPortraitGapView"
          />

          <StrategyCategory
            v-else-if="activeTab === 'strategy'"
            :card="strategyCard"
            :modules="strategyModules"
            :active-module-key="strategyActiveModuleKey"
            :active-module="strategyActiveModule"
            :module-rows="strategyModuleRows"
            :has-rows="strategyHasRows"
            :empty-text="strategyEmptyText"
            :highlight-key="highlight.tab === 'strategy' ? highlight.key : ''"
            :links-of="linksOf"
            :more-links="moreLinks"
            @select="setStrategyModule"
          />

          <DynamicCategory
            v-else-if="activeDynamicDim"
            :key="activeTab"
            :tab-key="activeTab"
            :card="dynamic.cardOf(activeTab)"
            :modules="dynamic.modulesOf(activeTab)"
            :active-module-key="dynamic.activeKeyOf(activeTab)"
            :active-module="dynamic.activeModuleOf(activeTab)"
            :module-rows="dynamic.moduleRowsOf(activeTab)"
            :row-groups="dynamic.rowGroupsOf(activeTab)"
            :has-rows="dynamic.hasRowsOf(activeTab)"
            :empty-text="dynamic.emptyTextOf(activeTab)"
            :highlight-key="highlight.tab === activeTab ? highlight.key : ''"
            :links-of="linksOf"
            :more-links="moreLinks"
            @select="dynamic.setModuleKey(activeTab, $event)"
          />
      </div>
      </aside>
    </main>

    <svg ref="flightSvg" class="flight" aria-hidden="true"></svg>

    <div
      v-if="question"
      ref="askEl"
      class="ask-overlay"
      :data-side="askPos.side"
      :style="{ left: `${askPos.left}px`, top: `${askPos.top}px`, width: `${askPos.width}px` }"
    >
      <span class="ask-arrow" :style="{ left: `${askPos.arrow}px` }" aria-hidden="true"></span>
      <AskQuestionCard :key="question.questionId" :item="question" @submit="submitQuestion" />
    </div>
  </div>
</template>

<style scoped>
.market-page {
  --panel: var(--panel-bg);
  --surface: var(--surface-soft);
  --text-2: var(--text-secondary);
  --text-3: var(--text-tertiary);
  --warn: var(--warning);
  --warn-soft: var(--warning-soft);
  --sans: var(--font-sans);
  --serif: var(--font-display);

  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--app-bg);
  color: var(--text);
  font-family: var(--sans);
}

.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

button,
input,
select {
  font-family: inherit;
}

:where(button, input, select, [tabindex]):focus-visible {
  outline: 2px solid rgba(71, 83, 199, 0.4);
  outline-offset: 2px;
}

/* ---------- top bar ---------- */
.topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 56px;
  padding: 0 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.tb-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.tb-tag {
  padding: 2px 7px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-3);
  background: var(--surface);
}
.tb-hint {
  margin-left: 6px;
  font-size: 12.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tb-hint.tb-error {
  color: var(--danger);
}

.btn {
  height: 32px;
  padding: 0 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text-2);
  font-size: 13.5px;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease),
    border-color 0.16s var(--ease);
}
.btn:hover {
  background: var(--surface);
  color: var(--text);
}
.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}
.btn.primary:hover {
  background: #3c46b2;
}
.btn:disabled {
  opacity: 0.55;
  cursor: default;
}

/* ---------- layout ---------- */
.grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(620px, 1fr);
  gap: 16px;
  padding: 14px 16px 16px;
}
/* 中等宽度：左侧流程是固定 4 列，不能被压得太窄，先把比例还给左栏。 */
@media (max-width: 1439px) {
  .grid {
    grid-template-columns: minmax(0, 1.55fr) minmax(450px, 1fr);
  }
}
/* 规划完成前右侧产物面板整体不出现，左侧占满一行。 */
.grid.plan-only {
  grid-template-columns: minmax(0, 1fr);
}
.left {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  /* 基础信息展开后经常比可视区高：左栏自己滚动，右侧产物面板保持固定。 */
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
  scrollbar-gutter: stable;
}

/* ---------- config ---------- */
.config {
  flex: none;
  padding: 16px 18px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.cfg-fields {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 280px));
  justify-content: start;
  gap: 12px 14px;
}
@media (max-width: 720px) {
  .cfg-fields {
    grid-template-columns: repeat(2, minmax(0, 280px));
  }
}
@media (max-width: 480px) {
  .cfg-fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.field.wide {
  grid-column: 1 / -1;
}
.field > span {
  font-size: 13px;
  color: var(--text-3);
}
.field input,
.field select {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font-size: 13.5px;
  min-width: 0;
}
.field input:focus,
.field select:focus {
  border-color: var(--primary);
  outline: none;
}
/* 目标岗位：输入框 + 右侧下拉，快捷岗位收进面板里 */
.role-combo {
  position: relative;
}
.role-combo input {
  padding-right: 32px;
}
.role-combo-toggle {
  position: absolute;
  top: 7px;
  right: 5px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.role-combo-toggle:hover:not(:disabled) {
  background: var(--surface);
  color: var(--primary);
}
.role-combo-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.role-combo-toggle svg {
  transition: transform 0.16s var(--ease);
}
.role-combo-toggle.open svg {
  transform: rotate(180deg);
}
.role-menu {
  position: absolute;
  z-index: 30;
  top: calc(100% + 5px);
  left: 0;
  right: 0;
  padding: 5px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: 0 12px 28px rgba(20, 24, 40, 0.14);
  animation: role-menu-in 0.14s var(--ease);
}
@keyframes role-menu-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.role-menu-group + .role-menu-group {
  margin-top: 5px;
  padding-top: 5px;
  border-top: 1px dashed var(--border);
}
.role-menu-label {
  display: block;
  padding: 2px 6px 3px;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-3);
}
.role-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 5px 6px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.role-menu-item:hover {
  background: var(--surface);
  color: var(--text);
}
.role-menu-item.active {
  background: var(--primary-faint);
  color: var(--primary);
}
.field-control {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.field-control select {
  flex: 1 1 0;
  width: auto;
  min-width: 0;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 2px;
}
.chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.chip:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}
.chip.active {
  border-color: var(--primary);
  background: var(--primary-faint);
  color: var(--primary);
}
.chip:disabled {
  opacity: 0.6;
  cursor: default;
}
.role-ai-wrap {
  display: inline-flex;
  flex: none;
}
.role-ai-btn {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--primary-faint);
  color: var(--primary);
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.role-ai-btn:hover:not(:disabled) {
  background: var(--primary-soft);
}
.role-ai-btn.idle,
.role-ai-btn:disabled {
  border-color: var(--border);
  background: var(--surface);
  color: var(--text-3);
  cursor: default;
}
.role-ai-btn:disabled {
  pointer-events: none;
}
.role-ai-btn.loading :deep(.icon-glyph) {
  animation: role-ai-spin 1.4s linear infinite;
}
@keyframes role-ai-spin {
  to {
    transform: rotate(360deg);
  }
}
.role-infer {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.role-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.role-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  font-size: 12.5px;
  line-height: 1.3;
}
.role-tag-label {
  font-size: 11.5px;
  color: var(--text-3);
}
.role-tag-value {
  color: var(--primary);
  font-weight: 600;
}
.role-chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.role-chip {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.role-chip:hover {
  border-color: var(--primary);
  background: var(--surface-soft);
}
.role-chip.active {
  border-color: var(--primary);
  box-shadow: inset 0 0 0 1px var(--primary);
}
.role-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.role-reason {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-3);
}
@media (max-width: 560px) {
  .role-chips {
    grid-template-columns: 1fr;
  }
}
.cfg-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  font-size: 12.5px;
  color: var(--text-3);
}
.cfg-foot .btn {
  flex: none;
}
.cfg-foot .btn.primary {
  margin-left: auto;
}
.cfg-summary {
  display: none;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  font-size: 13px;
  color: var(--text-2);
}
.cfg-summary-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cfg-summary-role {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--text);
}
.cfg-summary .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  flex: none;
}
.cfg-summary .dot.live {
  background: var(--primary);
  animation: cfgDotPulse 1.8s ease-in-out infinite;
}
@keyframes cfgDotPulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(71, 83, 199, 0.26);
  }
  50% {
    box-shadow: 0 0 0 3px rgba(71, 83, 199, 0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .cfg-summary .dot.live {
    animation: none;
  }
}
.cfg-summary-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  flex: none;
}
.cfg-summary .link {
  flex: none;
  border: none;
  background: none;
  padding: 0;
  font-size: 12.5px;
  color: var(--primary);
  cursor: pointer;
}
.cfg-summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
  min-width: 0;
}
.cfg-chip {
  display: inline-block;
  max-width: 100%;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cfg-chip b {
  margin-right: 4px;
  font-weight: 400;
  color: var(--text-3);
}
.cfg-summary .link:disabled {
  color: var(--text-3);
  cursor: not-allowed;
  opacity: 0.7;
}
.config[data-collapsed='1'] .cfg-fields,
.config[data-collapsed='1'] .cfg-foot {
  display: none;
}
.config[data-collapsed='1'] .cfg-summary {
  display: flex;
}

/* ---------- flow graph ---------- */
.flow {
  flex: none;
  padding: 14px 16px 16px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
/* 调研档案：左栏底部的历史报告列表，填补报告移入弹窗后的空白。 */
.archive {
  flex: 1;
  min-height: 150px;
  display: flex;
  flex-direction: column;
  padding: 14px 16px 16px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.archive-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 0 2px 8px;
}
.archive-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
}
.archive-note {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--text-3);
}
.archive-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.16s var(--ease);
}
.archive-item + .archive-item {
  margin-top: 2px;
}
.archive-item:hover {
  background: var(--primary-faint);
}
.archive-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.archive-role {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow-wrap: anywhere;
}
.archive-meta {
  font-size: 11.5px;
  color: var(--text-3);
  overflow-wrap: anywhere;
}
.archive-open {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11.5px;
  color: var(--text-3);
  transition: color 0.16s var(--ease);
}
.archive-item:hover .archive-open {
  color: var(--primary);
}
.archive-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px;
  border: 1px dashed var(--border-strong);
  border-radius: 9px;
  color: var(--text-3);
  text-align: center;
}
.archive-empty svg {
  flex: none;
  color: var(--border-strong);
}
.archive-empty p {
  max-width: 300px;
  margin: 0;
  font-size: 11.5px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.flow-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 2px 6px;
}
.flow-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
}
.flow-legend {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11.5px;
  color: var(--text-3);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.legend-line {
  width: 14px;
  height: 1px;
  background: var(--border-strong);
}
.legend-line.dashed {
  background: none;
  border-top: 1px dashed var(--border-strong);
  height: 0;
}
.legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  border: 1.5px solid var(--border-strong);
  background: var(--panel);
}
.legend-dot.running {
  border-color: var(--primary);
  background: var(--primary-faint);
}
.legend-dot.done {
  border-color: var(--success);
  background: var(--success-soft);
}

.canvas {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-template-rows: repeat(4, 40px);
  gap: 18px 22px;
  padding: 2px 4px 4px;
}
.edges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  z-index: 0;
}
:deep(.edge) {
  fill: none;
  stroke: var(--border-strong);
  stroke-width: 1.5;
  transition: stroke 0.3s var(--ease);
}
:deep(.edge.dashed) {
  stroke-dasharray: 4 4;
}
:deep(.edge[data-draw='0']) {
  opacity: 0;
}
:deep(.edge.done) {
  stroke: var(--success);
}
:deep(.edge.active) {
  stroke: #4753c7;
  stroke-dasharray: 6 6;
  animation: edge-run 0.55s linear infinite;
}
@keyframes edge-run {
  to {
    stroke-dashoffset: -12;
  }
}
@keyframes comet-run {
  from {
    stroke-dashoffset: 0;
  }
  to {
    stroke-dashoffset: -336;
  }
}
:deep(.edge-comet) {
  fill: none;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-dasharray: 96 240;
  animation: comet-run 1.15s linear infinite;
  pointer-events: none;
}

.gnode {
  position: relative;
  z-index: 1;
  align-self: center;
  justify-self: center;
  width: 100%;
  max-width: 172px;
  height: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  padding: 0 8px;
  border: 1.5px solid var(--border-strong);
  border-radius: 9px;
  background: var(--panel);
  text-align: center;
  cursor: pointer;
  overflow: hidden;
  transition:
    border-color 0.2s var(--ease),
    box-shadow 0.2s var(--ease),
    background 0.2s var(--ease),
    opacity 0.18s var(--ease);
}
.gnode:hover {
  border-color: #a9b2c9;
}
.gnode[data-born='0'] {
  opacity: 0;
  pointer-events: none;
}
.gnode.drawing {
  animation: node-draw 0.46s cubic-bezier(0.22, 0.8, 0.24, 1) both;
}
@keyframes node-draw {
  0% {
    opacity: 0;
    clip-path: inset(0 100% 0 0 round 9px);
  }
  55% {
    opacity: 1;
  }
  100% {
    opacity: 1;
    clip-path: inset(0 0 0 0 round 9px);
  }
}
.gnode[data-active='1'] {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-faint);
}
.gnode[data-state='running'] {
  border-color: var(--primary);
  background: var(--primary-faint);
  animation: node-pulse 1.5s ease-in-out infinite;
}
.gnode[data-state='done'] {
  border-color: var(--success);
  background: var(--success-soft);
  box-shadow:
    0 0 0 2px rgba(63, 143, 90, 0.14),
    0 0 16px rgba(63, 143, 90, 0.22);
}
.gnode[data-state='error'] {
  border-color: var(--warn);
  background: var(--warn-soft);
}
@keyframes node-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 2px rgba(71, 83, 199, 0.1);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(71, 83, 199, 0.16);
  }
}
.gnode[data-unread='1']::after {
  content: '';
  position: absolute;
  top: 5px;
  right: 5px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--primary);
}
.gname {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.gstate {
  font-size: 11.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.gnode[data-state='running'] .gstate {
  color: var(--primary);
}
.gnode[data-state='done'] .gstate {
  color: var(--success);
}
.gbar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--surface);
  opacity: 0;
  transition: opacity 0.16s var(--ease);
}
.gnode[data-state='running'] .gbar {
  opacity: 1;
}
.gbar i {
  display: block;
  height: 100%;
  width: 0;
  background: var(--primary);
  transition: width 0.24s var(--ease);
}
.canvas[data-resume='0'] .gnode[data-node='portrait'] {
  display: none;
}

/* ---------- report ---------- */
.rsec {
  position: relative;
  padding: 9px 0 11px;
  border-bottom: 1px dashed var(--border);
}
.rsec:last-child {
  border-bottom: none;
}
.rsec[hidden] {
  display: none;
}
.rsec-draft {
  margin-top: 5px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-3);
  opacity: 0;
  transition: opacity 0.24s var(--ease);
}
.rsec-draft.has {
  opacity: 1;
  color: var(--text-2);
}
.rsec-prose {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.78;
  color: var(--text-2);
}
.rsec-src {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--text-3);
}
.rsec-src-label {
  flex: none;
}
.rsec-src-link {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--primary-faint);
  color: var(--primary);
  text-decoration: none;
  overflow-wrap: anywhere;
}
.rsec-src-link:hover {
  background: var(--primary-soft);
}
/* ---------- report modal ---------- */
.report-modal {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
  background: rgba(15, 18, 30, 0.52);
  backdrop-filter: blur(3px);

  /* 弹窗被 Teleport 到 body，脱离了 .market-page，需自带这些局部变量 */
  --panel: #ffffff;
  --surface: #f4f5f8;
  --text-2: #596175;
  --text-3: #8a91a6;
  --primary-soft: #eceffb;
  --primary-faint: #f4f5fc;
  --success-soft: #edf4ef;
  --warn: #a6763f;
  --warn-soft: #f6efe4;
  --serif: var(--font-display);
  --sans: var(--font-sans);
}
.report-modal-panel {
  display: flex;
  flex-direction: column;
  width: min(1080px, 100%);
  max-height: 88vh;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 24px 64px rgba(15, 18, 30, 0.32);
  overflow: hidden;
}
.report-modal-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.report-modal-titlebox {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.report-modal-title {
  font-family: var(--serif);
  font-size: 16px;
  font-weight: 600;
}
.report-modal-sub {
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
/* 最近 3 次报告：弹窗头部下拉，只替换当前展示的报告正文。 */
.report-history {
  position: relative;
  flex: none;
  margin-left: auto;
}
.report-history-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition:
    border-color 0.2s var(--ease),
    color 0.2s var(--ease),
    background 0.2s var(--ease);
}
.report-history-btn:hover,
.report-history-btn.active {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-faint);
}
.report-history-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 10;
  width: 268px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--panel);
  box-shadow: 0 12px 32px rgba(15, 18, 30, 0.16);
}
.report-history-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 7px 9px;
  border: none;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.report-history-item:hover {
  background: var(--surface);
}
.report-history-item.active {
  background: var(--primary-faint);
}
.rh-role {
  font-size: 12.5px;
  color: var(--text);
  overflow-wrap: anywhere;
}
.rh-time {
  font-size: 11px;
  color: var(--text-3);
  overflow-wrap: anywhere;
}
.report-history-item.active .rh-role {
  color: var(--primary);
}
.report-history-empty {
  margin: 6px 8px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-3);
}
.report-modal-close {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  cursor: pointer;
  transition: border-color 0.2s var(--ease), color 0.2s var(--ease), background 0.2s var(--ease);
}
.report-modal-close:hover {
  border-color: var(--danger);
  color: var(--danger);
  background: var(--danger-soft);
}
.report-modal-main {
  flex: 1;
  min-height: 0;
  display: flex;
}
.report-nav {
  flex: none;
  width: 176px;
  overflow: auto;
  padding: 10px 8px 12px;
  border-right: 1px solid var(--border);
  background: var(--surface);
}
.report-nav-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.16s var(--ease), color 0.16s var(--ease);
}
.report-nav-item:hover {
  background: var(--panel);
}
.report-nav-item.active {
  background: var(--primary-faint);
}
.report-nav-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.report-nav-item.active .report-nav-name {
  color: var(--primary);
  font-weight: 600;
}
.report-nav-state {
  flex: none;
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}
.report-nav-item[data-ready='1'] .report-nav-state {
  color: var(--success);
}
.report-modal-body {
  flex: 1;
  min-width: 0;
  overflow: auto;
  padding: 8px 26px 28px;
}
.report-modal-body .rsec {
  padding: 16px 0 18px;
  scroll-margin-top: 10px;
}
.report-modal-body .rsec-prose {
  font-size: 15px;
  line-height: 1.82;
}
.report-modal-body .rsec-src {
  max-width: 100%;
}

/* ---------- right column ---------- */
.right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.bus {
  position: relative;
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 12px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  overflow: hidden;
}
.bus-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  font-size: 11.5px;
  color: var(--text-3);
  letter-spacing: 0.02em;
}
.bus-label::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--border-strong);
  transition:
    background 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.bus.hit .bus-label::before {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.14);
}
.bus-note {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0;
  transition: opacity 0.18s var(--ease);
}
.bus-note.show {
  opacity: 1;
}
.bus-note .tag {
  display: inline-block;
  margin-right: 6px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11.5px;
}
.bus-note.unwatched .tag {
  background: var(--surface);
  color: var(--text-3);
  box-shadow: inset 0 0 0 1px var(--border);
}
.right-body {
  flex: 1;
  min-height: 0;
  display: flex;
}
/* 竖排类别：产出总线下的每个类别都在这里，顺序与流程一致。
   一组一个圆角容器，当前组整组浅靛蓝底 + 细描边，状态右对齐。 */
.cat-rail {
  flex: none;
  width: 168px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 8px;
  background: var(--panel);
  border-right: 1px solid var(--border);
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}
.cat-rail-list {
  display: contents;
}
/* 页签跟着流程节点逐条出现；从上往下“画”出来，保持竖向排版。 */
.tab-draw-enter-active {
  animation: tab-draw-in 0.4s cubic-bezier(0.22, 0.8, 0.24, 1) both;
}
.tab-draw-leave-active {
  display: none;
}
@keyframes tab-draw-in {
  0% {
    opacity: 0;
    clip-path: inset(0 0 100% 0 round 7px);
    transform: translateY(-5px);
  }
  55% {
    opacity: 1;
  }
  100% {
    opacity: 1;
    clip-path: inset(0 0 0 0 round 7px);
    transform: none;
  }
}
.cat-group {
  flex: none;
  padding: 2px;
  border: 1px solid transparent;
  border-radius: 10px;
  transition:
    background 0.18s var(--ease),
    border-color 0.18s var(--ease);
}
.cat-group.open {
  background: var(--primary-soft);
  border-color: rgba(71, 83, 199, 0.16);
}
.cat-children {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 1px 0 3px;
}
.cat-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.cat-item.top {
  height: 32px;
  padding: 0 9px;
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
}
/* 没开始的顶层类别整体压淡，和参照稿里的「画像 · 待开始」一致。 */
.cat-item.top.idle {
  color: var(--text-3);
}
.cat-item.child {
  height: 29px;
  padding: 0 9px 0 21px;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
}
.cat-item:hover {
  background: rgba(255, 255, 255, 0.72);
  color: var(--text);
}
.cat-item.top.active {
  color: var(--text);
}
.cat-item.child.active {
  background: rgba(255, 255, 255, 0.86);
  color: var(--text);
  font-weight: 600;
}
.cat-item.flash {
  background: var(--primary-faint);
}
.cat-item .label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 状态文案右对齐，四种语气共用一套字号与颜色。 */
.cat-status {
  flex: none;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.01em;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.cat-status.running {
  color: var(--primary);
}
.cat-status.done {
  color: var(--text-2);
}
.cat-status.error {
  color: var(--danger);
}
/* 未读角标挨着名字，不占状态的位置。 */
.mini-badge {
  flex: none;
  min-width: 14px;
  height: 14px;
  padding: 0 4px;
  border-radius: 7px;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  font-weight: 500;
  line-height: 14px;
  text-align: center;
}

/* ---------- flight overlay ---------- */
.flight {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 80;
  overflow: visible;
}
:deep(.fly-path) {
  fill: none;
  stroke: var(--primary);
  stroke-width: 1.5;
  stroke-linecap: round;
  opacity: 0.55;
  transition: opacity 0.2s var(--ease);
}
:deep(.fly-path.done) {
  opacity: 0;
}
:deep(.fly-comet) {
  stroke: none;
  pointer-events: none;
  transition: opacity 0.2s var(--ease);
}
:deep(.fly-comet.done) {
  opacity: 0;
}
:deep(.fly-head) {
  stroke: none;
  pointer-events: none;
  transition: opacity 0.2s var(--ease);
}
:deep(.fly-head.done) {
  opacity: 0;
}

/* ---------- ask overlay ---------- */
.ask-overlay {
  position: fixed;
  z-index: 95;
  animation: ask-pop 0.16s var(--ease);
}
.ask-overlay :deep(.ask-card) {
  position: relative;
  z-index: 1;
  /* 题目多 / 屏幕矮时卡片自己滚动，别把选项和提交按钮挤出可视区。 */
  max-height: calc(100vh - 24px);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.ask-arrow {
  position: absolute;
  z-index: 0;
  width: 12px;
  height: 12px;
  background: var(--panel-bg);
  border: 1px solid var(--primary-soft);
  transform: rotate(45deg);
  pointer-events: none;
}
.ask-overlay[data-side='top'] .ask-arrow {
  top: -7px;
  border-right: 0;
  border-bottom: 0;
}
.ask-overlay[data-side='bottom'] .ask-arrow {
  bottom: -7px;
  border-left: 0;
  border-top: 0;
}
@keyframes ask-pop {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
}

@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}

@media (max-width: 960px) {
  .market-page {
    overflow: auto;
  }
  /* 单列后高度交给内容决定；否则左列被压扁，流程图会盖到右侧面板上。 */
  .grid {
    grid-template-columns: minmax(0, 1fr);
    flex: none;
    height: auto;
  }
  .left {
    min-height: auto;
  }
  .right {
    min-height: 420px;
  }
}

@media (max-width: 720px) {
  /* 窄屏把竖排类别折成横向标签，别让它的宽度挤掉内容。 */
  .right-body {
    flex-direction: column;
  }
  .cat-rail {
    width: auto;
    min-height: auto;
    flex-direction: row;
    align-items: center;
    gap: 3px;
    padding: 6px;
    overflow-x: auto;
    overflow-y: hidden;
    border-right: 0;
    border-bottom: 1px solid var(--border);
    scrollbar-width: none;
  }
  .cat-rail::-webkit-scrollbar {
    display: none;
  }
  .cat-rail-list {
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .cat-group {
    display: flex;
    flex: none;
    align-items: center;
    padding: 1px;
  }
  .cat-children {
    flex-direction: row;
    gap: 1px;
    padding: 0;
  }
  .cat-item {
    width: auto;
    flex: none;
    height: 30px;
    padding: 0 10px;
    white-space: nowrap;
  }
  .cat-item.child {
    padding: 0 10px;
  }
  /* 横排时状态文字会挤掉类别名，只留名字和角标。 */
  .cat-status {
    display: none;
  }
}
</style>
