import { useStorage } from '@vueuse/core'

/**
 * 市场洞察的采集参数：时间范围、三类维度的采集页数与补充网址条数、
 * 采集方式、抓取方式与内置来源开关。
 *
 * 这些参数作为全局默认值放在「高级设置 · 市场洞察」里，每轮调研开始时读取一次；
 * 修改后从下一轮开始生效。用户补充的带标签网址在 stores/marketSources.ts，
 * 单独走本地备份库。
 */
export const TIME_RANGE_OPTIONS = [
  { value: '3m', label: '近3个月' },
  { value: '6m', label: '近6个月' },
  { value: '12m', label: '近12个月' },
]

/** 自定义时间范围：存成 `<月数>m`，如 18m；后端负责换算成绝对年月。 */
export const TIME_RANGE_MIN = 1
export const TIME_RANGE_MAX = 120
const CUSTOM_TIME_RANGE_RE = /^(\d{1,3})m$/

/** 预设或自定义时间范围的展示文案。 */
export function timeRangeLabel(value: string): string {
  const preset = TIME_RANGE_OPTIONS.find((option) => option.value === value)
  if (preset) return preset.label
  const match = CUSTOM_TIME_RANGE_RE.exec(value)
  return match ? `近 ${Number(match[1])} 个月` : value
}

/** 是否不是预设值（用于高亮自定义输入）。 */
export function isCustomTimeRange(value: string): boolean {
  return !TIME_RANGE_OPTIONS.some((option) => option.value === value)
}

/** 旧值可能是已下线选项或非法自定义值：收窄成当前可用的预设或 `<月数>m`。 */
function normalizeTimeRange(value: unknown): string {
  const raw = String(value ?? '').trim()
  if (TIME_RANGE_OPTIONS.some((option) => option.value === raw)) return raw
  const match = CUSTOM_TIME_RANGE_RE.exec(raw)
  if (match) {
    const months = Math.min(TIME_RANGE_MAX, Math.max(TIME_RANGE_MIN, Number(match[1])))
    return `${months}m`
  }
  return DEFAULT_MARKET_RESEARCH.timeRange
}

/** 设置项的一个可选值：value 传给后端，label 只用于界面展示。 */
export interface BuiltinSourceSettingOption {
  value: string
  label: string
}

/** 内置来源的一项设置：key 和 value 都是英文，原样传给后端适配器的 settings。 */
export interface BuiltinSourceSetting {
  /** 传给后端的设置键，如 recruitType。 */
  key: string
  /** 界面展示的字段名，如「招聘类型」。 */
  label: string
  options: BuiltinSourceSettingOption[]
  /** 默认值（英文）：启用来源时自动选中，未配置时也用它兜底；设置项不可清空。 */
  default?: string
}

export interface BuiltinSourceOption {
  /** 来源 key，必须与后端适配器的 label 一致。 */
  id: string
  label: string
  /** 来源图标：IconGlyph 名或品牌图标 id。 */
  icon: 'briefcase' | 'aggregate' | 'tencent' | 'bytedance' | 'huawei' | 'alibaba'
  settings: BuiltinSourceSetting[]
  /** 社招 / 校招官网入口；只用于界面跳转，不传给后端。 */
  links?: Partial<Record<'experienced' | 'campus', string>>
}

/** 内置来源：全部是结构化招聘来源；id 必须与后端适配器的 label 一致。 */
export const BUILTIN_SOURCES: BuiltinSourceOption[] = [
  {
    // 通过 SearXNG 聚合多个招聘网站的公开岗位页，不区分社招 / 校招。
    id: '全网招聘',
    label: '全网招聘',
    icon: 'aggregate',
    settings: [],
  },
  {
    id: '腾讯',
    label: '腾讯',
    icon: 'tencent',
    settings: [
      {
        key: 'recruitType',
        label: '招聘类型',
        options: [
          { value: 'experienced', label: '社招' },
          { value: 'campus', label: '校招' },
        ],
        default: 'experienced',
      },
    ],
    links: {
      experienced: 'https://careers.tencent.com/jobopportunity.html',
      campus: 'https://join.qq.com/post.html',
    },
  },
  {
    id: '字节跳动',
    label: '字节跳动',
    icon: 'bytedance',
    settings: [
      {
        key: 'recruitType',
        label: '招聘类型',
        options: [
          { value: 'experienced', label: '社招' },
          { value: 'campus', label: '校招' },
        ],
        default: 'experienced',
      },
    ],
    links: {
      experienced: 'https://jobs.bytedance.com/',
      campus: 'https://jobs.bytedance.com/campus',
    },
  },
  {
    id: '华为',
    label: '华为',
    icon: 'huawei',
    settings: [
      {
        key: 'recruitType',
        label: '招聘类型',
        options: [
          { value: 'experienced', label: '社招' },
          { value: 'campus', label: '校招' },
        ],
        default: 'experienced',
      },
    ],
    links: {
      experienced: 'https://career.huawei.com/cn/social-recruitment',
      campus: 'https://career.huawei.com/cn/campus-recruitment',
    },
  },
  {
    id: '阿里巴巴',
    label: '阿里巴巴',
    icon: 'alibaba',
    settings: [
      {
        key: 'recruitType',
        label: '招聘类型',
        options: [
          { value: 'experienced', label: '社招' },
          { value: 'campus', label: '校招' },
        ],
        default: 'experienced',
      },
    ],
    links: {
      experienced: 'https://talent.alibaba.com/',
      campus: 'https://campus-talent.alibaba.com/campus/position',
    },
  },
]

/** 内置来源 id 列表；需要字符串数组时用它。 */
export const SOURCE_OPTIONS = BUILTIN_SOURCES.map((source) => source.id)

/** 单个来源的动态设置：键由来源决定，如 recruitType。 */
export type SourceSettings = Record<string, string>
/** 用户勾选的来源及其设置：{ 来源: { 设置键: 值 } }，与后端 sources 一致。 */
export type SourceSelection = Record<string, SourceSettings>

/** 页数按三类维度配置：固定维度 jobs / trend，其余动态方向统一走 other。 */
export type DimPagesKey = 'jobs' | 'trend' | 'other'
export type DimPages = Record<DimPagesKey, number>

export const PAGE_DIM_OPTIONS: { key: DimPagesKey; label: string; hint: string }[] = [
  { key: 'jobs', label: '招聘矩阵', hint: '招聘维度的页数；启用内置来源时由各来源共用。' },
  { key: 'trend', label: '技术趋势', hint: '技术趋势维度每轮抓取的页数。' },
  { key: 'other', label: '其他方向', hint: '用户选择的每个动态方向各自抓取的页数。' },
]
export const DIM_LIMIT_MIN = 1
export const DIM_LIMIT_MAX = 60

/** 抓取方式：id 与后端 `tools/fetch` 注册表一一对应。 */
export const FETCH_MODE_OPTIONS = [
  { value: 'get', label: 'GET 直取', hint: '普通 GET 请求读取静态 HTML，最快，覆盖公开文章页' },
  { value: 'crawler', label: '正文解析', hint: '带浏览器指纹抓取后抽取 article/main 正文并转 Markdown，比直取干净，较慢' },
]

/**
 * 采集方式：id 与后端 `tools/collectors` 注册表一一对应。
 * searxng 先搜出网址再按抓取方式取正文；deepseek 检索时直接带回正文。
 */
export const COLLECT_METHOD_OPTIONS = [
  {
    value: 'searxng',
    label: 'SearXNG',
    hint: '本地 SearXNG 聚合搜索出网址，再按抓取方式取正文；不调用外部付费接口',
  },
  {
    value: 'deepseek',
    label: 'DeepSeek',
    hint: '调用 DeepSeek 搜索接口，检索时直接返回摘要与正文，不再逐页抓取；需要 Base URL 和 API Key',
  },
]

/** 采集方式的参数：只有 DeepSeek 用得上，SearXNG 不需要填。 */
export interface CollectMethodSettings {
  /** 接口地址，默认 https://api.deepseek.com。 */
  baseUrl: string
  /** API Key，只保存在当前浏览器。 */
  apiKey: string
}

export interface MarketResearchSettings {
  timeRange: string
  /** 三类维度各自抓取的页数。 */
  pagesPerDim: DimPages
  /** 每个调研方向最多使用的补充网址条数。 */
  urlsPerDim: number
  fetchMode: string
  /** 采集方式：searxng / deepseek，见 COLLECT_METHOD_OPTIONS。 */
  collector: string
  /** 采集方式的参数，随采集方式一起传给后端。 */
  collectorSettings: CollectMethodSettings
  sources: SourceSelection
}

export const DEFAULT_MARKET_RESEARCH: MarketResearchSettings = {
  timeRange: '3m',
  pagesPerDim: { jobs: 12, trend: 12, other: 12 },
  urlsPerDim: 12,
  fetchMode: 'get',
  collector: 'searxng',
  collectorSettings: { baseUrl: 'https://api.deepseek.com', apiKey: '' },
  // 不勾内置源时走采集方式；勾了内置源就只用内置源，不回落。
  sources: {},
}

/** 采集方式 → 后端 `collector` 字段：{方式 id: {设置键: 值}}，SearXNG 没有设置。 */
export function collectorPayload(
  settings: MarketResearchSettings,
): Record<string, Record<string, string>> {
  if (settings.collector !== 'deepseek') return { [settings.collector]: {} }
  return {
    deepseek: {
      baseUrl: settings.collectorSettings.baseUrl.trim(),
      apiKey: settings.collectorSettings.apiKey.trim(),
    },
  }
}

/** 是否启用了任意内置来源；启用后 jobs 相关采集改走内置来源。 */
export function hasBuiltinSource(settings: MarketResearchSettings): boolean {
  return Object.keys(settings.sources).length > 0
}

export const marketResearch = useStorage<MarketResearchSettings>(
  'smartcv-market-research',
  DEFAULT_MARKET_RESEARCH,
  undefined,
  { mergeDefaults: true },
)

function clampDimLimit(value: unknown, fallback: number): number {
  const num = Math.round(Number(value))
  if (!Number.isFinite(num)) return fallback
  return Math.min(DIM_LIMIT_MAX, Math.max(DIM_LIMIT_MIN, num))
}

/**
 * 旧版本把页数存成单个数字，并单独存 jobsPagesPerDim；统一迁成三维度对象。
 * 旧单值同时作为 trend / other 的默认值，招聘维度优先用旧的招聘页数。
 */
function normalizePagesPerDim(value: unknown, legacyJobs?: unknown): DimPages {
  const source =
    value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  const fallback =
    typeof value === 'number' ? value : DEFAULT_MARKET_RESEARCH.pagesPerDim.jobs
  return {
    jobs: clampDimLimit(legacyJobs ?? source.jobs ?? fallback, fallback),
    trend: clampDimLimit(source.trend ?? fallback, fallback),
    other: clampDimLimit(source.other ?? fallback, fallback),
  }
}

/** 来源改过展示名：旧 key 迁移到新 id，历史设置不丢。 */
const SOURCE_ALIASES: Record<string, string> = {
  腾讯招聘: '腾讯',
  BOSS直聘: '全网招聘',
  聚合招聘: '全网招聘',
}

/** 设置键/值统一用英文契约；迁移旧版存过的中文键值。 */
const SETTING_KEY_ALIASES: Record<string, string> = { 招聘类型: 'recruitType' }
const SETTING_VALUE_ALIASES: Record<string, Record<string, string>> = {
  recruitType: { 社招: 'experienced', 校招: 'campus' },
}

/** 该来源各设置项的默认值；设置不可清空，未勾选设置时也靠它保证有值。 */
export function defaultSourceSettings(id: string): SourceSettings {
  const source = BUILTIN_SOURCES.find((item) => item.id === id)
  const result: SourceSettings = {}
  for (const setting of source?.settings ?? []) {
    if (setting.default) result[setting.key] = setting.default
  }
  return result
}

/** 只保留该来源声明过的设置项和枚举值，顺带把旧中文键值换成英文。 */
function normalizeSourceSettings(id: string, settings: Record<string, unknown>): SourceSettings {
  const source = BUILTIN_SOURCES.find((item) => item.id === id)
  if (!source) return {}
  const result: SourceSettings = {}
  for (const [rawKey, rawValue] of Object.entries(settings)) {
    const key = SETTING_KEY_ALIASES[rawKey.trim()] ?? rawKey.trim()
    const setting = source.settings.find((item) => item.key === key)
    if (!setting) continue
    const raw = String(rawValue).trim()
    const value = SETTING_VALUE_ALIASES[key]?.[raw] ?? raw
    if (setting.options.some((option) => option.value === value)) result[key] = value
  }
  return result
}

/**
 * 旧的 sources 是字符串数组，新结构是 {来源: {设置}}。
 * 这里统一迁移，同时丢掉已下线的来源和非法设置值。
 */
function normalizeSources(value: unknown): SourceSelection {
  const known = new Set(SOURCE_OPTIONS)
  const result: SourceSelection = {}
  const canonical = (name: string) => SOURCE_ALIASES[name] ?? name
  if (Array.isArray(value)) {
    for (const item of value) {
      const name = canonical(String(item))
      if (known.has(name)) result[name] = defaultSourceSettings(name)
    }
    return result
  }
  if (!value || typeof value !== 'object') return result
  for (const [rawName, settings] of Object.entries(value as Record<string, unknown>)) {
    const name = canonical(rawName)
    if (!known.has(name)) continue
    if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
      result[name] = { ...defaultSourceSettings(name), ...(result[name] ?? {}) }
      continue
    }
    result[name] = {
      ...defaultSourceSettings(name),
      ...(result[name] ?? {}),
      ...normalizeSourceSettings(name, settings as Record<string, unknown>),
    }
  }
  return result
}

// 旧版本可能存过已下线的渠道、旧的总额度字段或非法取值：收窄成当前可用的取值。
marketResearch.value.sources = normalizeSources(marketResearch.value.sources)
marketResearch.value.timeRange = normalizeTimeRange(marketResearch.value.timeRange)
const legacyJobsPages = (marketResearch.value as unknown as Record<string, unknown>)
  .jobsPagesPerDim
marketResearch.value.pagesPerDim = normalizePagesPerDim(
  marketResearch.value.pagesPerDim,
  legacyJobsPages,
)
delete (marketResearch.value as unknown as Record<string, unknown>).jobsPagesPerDim
marketResearch.value.urlsPerDim = clampDimLimit(
  marketResearch.value.urlsPerDim,
  DEFAULT_MARKET_RESEARCH.urlsPerDim,
)
if (!FETCH_MODE_OPTIONS.some((option) => option.value === marketResearch.value.fetchMode)) {
  marketResearch.value.fetchMode = DEFAULT_MARKET_RESEARCH.fetchMode
}
if (!COLLECT_METHOD_OPTIONS.some((option) => option.value === marketResearch.value.collector)) {
  marketResearch.value.collector = DEFAULT_MARKET_RESEARCH.collector
}
// 旧版本没有 collectorSettings；缺失时补默认地址，别让 deepseek 首轮就报缺地址。
const storedCollector = marketResearch.value.collectorSettings
marketResearch.value.collectorSettings = {
  baseUrl:
    String(storedCollector?.baseUrl ?? '').trim() ||
    DEFAULT_MARKET_RESEARCH.collectorSettings.baseUrl,
  apiKey: String(storedCollector?.apiKey ?? '').trim(),
}
