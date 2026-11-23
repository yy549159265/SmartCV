<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useStorage } from '@vueuse/core'
import {
  siAlibabadotcom,
  siBytedance,
  siDeepseek,
  siHuawei,
  siQq,
  siSearxng,
} from 'simple-icons'
import { dialog, message } from '@/utils/feedback'
import {
  ASR_MODE_OPTIONS,
  DEFAULT_DEEPSEEK_BASE_URL,
  asrSettings,
} from '@/composables/useAsrSettings'
import { getAgentMd, type AgentMdFile, type AgentMdPayload } from '@/api/agent'
import { renderMarkdown } from '@/utils/markdown'
import { useDocumentsStore } from '@/stores/documents'
import {
  DEFAULT_MARKET_MOTION,
  MOTION_CHANNELS,
  RANDOM_MOTION_COLORS,
  RANDOM_RANGES,
  marketMotion,
  pickRandomMotionColor,
  randomBetween,
  randomBowSign,
  type MotionChannel,
} from '@/composables/useMarketMotion'
import {
  BUILTIN_SOURCES,
  COLLECT_METHOD_OPTIONS,
  DEFAULT_MARKET_RESEARCH,
  DIM_LIMIT_MAX,
  DIM_LIMIT_MIN,
  FETCH_MODE_OPTIONS,
  PAGE_DIM_OPTIONS,
  TIME_RANGE_MAX,
  TIME_RANGE_MIN,
  TIME_RANGE_OPTIONS,
  defaultSourceSettings,
  isCustomTimeRange,
  marketResearch,
  type BuiltinSourceOption,
  type DimPagesKey,
  type SourceSelection,
} from '@/composables/useMarketResearch'
import { brandSvg } from '@/data/icons'
import jobsAggregateIcon from '@/assets/brand/jobs-aggregate.svg?raw'
import {
  DIRECTION_OPTIONS,
  normalizeSourceUrl,
  sourceHost,
  useMarketSourcesStore,
  type MarketSourceEntry,
  type SourceDirection,
} from '@/stores/marketSources'
import { supportsDirectoryPicker } from '@/utils/fs/directoryHandle'
import { formatDateTime } from '@/utils/time'
import IconGlyph from '@/components/IconGlyph.vue'

const props = defineProps<{
  initialTab?: 'provider' | 'backup' | 'market' | 'interview' | 'md'
}>()

const tab = ref<'provider' | 'backup' | 'market' | 'interview' | 'md'>(
  props.initialTab ?? 'provider',
)
watch(
  () => props.initialTab,
  (value) => {
    if (value) tab.value = value
  },
)

const documents = useDocumentsStore()
const marketSources = useMarketSourcesStore()
const supportsFolder = supportsDirectoryPicker()

const statusText = computed(() => {
  switch (documents.status) {
    case 'unsupported':
      return '当前浏览器不支持'
    case 'unbound':
      return '未设置'
    case 'needs-permission':
      return '需要授权'
    case 'denied':
      return '权限被拒绝'
    case 'ready':
      return '已连接'
    default:
      return '未设置'
  }
})

const statusClass = computed(() => ({
  'is-ready': documents.status === 'ready',
  'is-warn': documents.status === 'needs-permission' || documents.status === 'denied',
}))

function confirmSwitchFolder(): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (value: boolean) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    dialog.warning({
      title: '更换备份文件夹？',
      content: '更换后，旧文件夹里的文件不会被删除或移动；当前简历也不会自动复制到新文件夹。',
      positiveText: '更换',
      negativeText: '取消',
      onPositiveClick: () => finish(true),
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

async function onChooseFolder() {
  if (documents.isBound && !(await confirmSwitchFolder())) return
  const ok = await documents.bindFolder()
  if (ok) message.success(`已连接备份文件夹：${documents.folderName}`)
}

async function onSync() {
  const ok = await documents.sync()
  if (ok) message.success(`已同步，文件夹内共 ${documents.files.length} 份简历`)
}

async function onAuthorize() {
  const ok = await documents.ensurePermission()
  if (ok) {
    await documents.refreshFiles()
    message.success('已获得文件夹读写权限')
  } else {
    message.warning('未获得文件夹权限，请在浏览器地址栏的站点设置中允许后重试')
  }
}

function onDisconnect() {
  dialog.warning({
    title: '断开备份文件夹？',
    content: '只会忘记这个文件夹，里面的 JSON / PDF 文件不会被删除。当前简历仍保留在浏览器里。',
    positiveText: '断开连接',
    negativeText: '取消',
    onPositiveClick: async () => {
      await documents.unbindFolder()
      message.success('已断开备份文件夹')
    },
  })
}

const settings = useStorage('smartcv-provider-settings', {
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4o-mini',
})

const draft = reactive({ ...settings.value })

function onSave() {
  settings.value = { ...draft }
  message.success('已保存（保存在浏览器本地）')
}

function onTest() {
  message.info('连接测试功能开发中：接入后端后即可使用')
}

const md = ref<AgentMdPayload>({ prompts: [], skills: [] })
const selected = ref<AgentMdFile | null>(null)
const mdLoaded = ref(false)
const loading = ref(false)

function stripFrontmatter(src: string): string {
  return src.replace(/^---\r?\n[\s\S]*?\r?\n-{3,}\s*(?:\r?\n|$)/, '')
}

const mdHtml = computed(() =>
  renderMarkdown(stripFrontmatter(selected.value?.content ?? '')),
)

const promptGroups = computed(() => {
  const resume = md.value.prompts.filter((f) => f.category !== 'market' && f.category !== 'interview')
  const interview = md.value.prompts.filter((f) => f.category === 'interview')
  const market = md.value.prompts.filter((f) => f.category === 'market')
  return [
    { key: 'resume', label: '优化简历', items: resume },
    { key: 'interview', label: '模拟面试', items: interview },
    { key: 'market', label: '市场洞察', items: market },
  ].filter((group) => group.items.length > 0)
})

const selectedKind = computed(() => {
  if (!selected.value) return ''
  if (selected.value.category === 'market') return '市场洞察'
  if (selected.value.category === 'interview') return '模拟面试'
  if (selected.value.category === 'resume') return '优化简历'
  return '技能'
})

interface PreviewLane {
  key: string
  color: string
  tail: number
  duration: number
  width: number
  /** 预览弧线向上 / 向下：正数向下弯，负数向上弯。 */
  bend: number
}

const previewTick = ref(0)

/** 预览时各链路的基准值，和流程图里实际飞行箭头的比例保持一致。 */
const PREVIEW_BASE: Record<MotionChannel, { tail: number; duration: number }> = {
  bus: { tail: 200, duration: 700 },
  report: { tail: 280, duration: 900 },
  flow: { tail: 420, duration: 760 },
}

/** 预览用三条链路；随机模式下每次重算 / 重播都重新抽一组值。 */
const previewLanes = computed<PreviewLane[]>(() => {
  const motion = marketMotion.value
  const channels: MotionChannel[] = ['bus', 'report', 'flow']
  const tick = previewTick.value
  if (motion.mode === 'random') {
    return channels.map((_, index) => ({
      key: `random-${tick}-${index}`,
      color: pickRandomMotionColor(),
      tail: Math.round(randomBetween(...RANDOM_RANGES.tail)),
      duration: Math.round(randomBetween(...RANDOM_RANGES.duration)),
      width: Math.round(randomBetween(...RANDOM_RANGES.width) * 10) / 10,
      bend: randomBowSign() * Math.round(randomBetween(14, 30)),
    }))
  }
  const tailScale = motion.tail / DEFAULT_MARKET_MOTION.tail
  const durationScale = motion.duration / DEFAULT_MARKET_MOTION.duration
  return channels.map((channel, index) => ({
    key: `fixed-${tick}-${index}`,
    color: motion.colors[channel],
    tail: Math.round(PREVIEW_BASE[channel].tail * tailScale),
    duration: Math.round(PREVIEW_BASE[channel].duration * durationScale),
    width: motion.width,
    bend:
      motion.directionRandom !== false
        ? randomBowSign() * Math.round(randomBetween(14, 30))
        : 0,
  }))
})

function laneStyle(lane: PreviewLane): Record<string, string> {
  return {
    '--lane-color': lane.color,
    '--lane-tail': `${lane.tail}px`,
    '--lane-duration': `${lane.duration}ms`,
    '--lane-width': `${lane.width}px`,
    '--lane-bend': `${lane.bend}px`,
  }
}

function replayPreview() {
  previewTick.value += 1
}

function resetMotion() {
  marketMotion.value = {
    ...DEFAULT_MARKET_MOTION,
    colors: { ...DEFAULT_MARKET_MOTION.colors },
  }
  replayPreview()
  message.success('已恢复默认动效')
}

/** 内置来源图标：品牌站用 simple-icons，全网招聘用随包的聚合图标。 */
const SOURCE_ICONS: Record<string, string> = {
  aggregate: jobsAggregateIcon,
  tencent: brandSvg(siQq),
  bytedance: brandSvg(siBytedance),
  huawei: brandSvg(siHuawei),
  alibaba: brandSvg(siAlibabadotcom),
}

function sourceIcon(source: BuiltinSourceOption): string {
  return SOURCE_ICONS[source.icon] ?? ''
}

/** 内置来源的社招 / 校招官网入口，只做界面跳转。 */
function sourceLinks(source: BuiltinSourceOption): { key: string; label: string; url: string }[] {
  const links: { key: string; label: string; url: string }[] = []
  if (source.links?.experienced) {
    links.push({ key: 'experienced', label: '社招', url: source.links.experienced })
  }
  if (source.links?.campus) {
    links.push({ key: 'campus', label: '校招', url: source.links.campus })
  }
  return links
}

/** 关掉全部内置来源后，jobs 维度完全交给 SearXNG 聚合搜索。 */
function isSourceEnabled(id: string): boolean {
  return id in marketResearch.value.sources
}

function sourceSetting(id: string, key: string): string {
  return marketResearch.value.sources[id]?.[key] ?? ''
}

function toggleSource(id: string) {
  const next: SourceSelection = { ...marketResearch.value.sources }
  if (next[id]) delete next[id]
  else next[id] = defaultSourceSettings(id)
  marketResearch.value.sources = next
}

/** 下拉选择设置；设置项不可清空，选空时回退到默认值。来源未启用时不写入。 */
function setSourceSetting(id: string, key: string, value: string | null) {
  if (!isSourceEnabled(id)) return
  const settings = { ...(marketResearch.value.sources[id] ?? {}) }
  const next = value || defaultSourceSettings(id)[key]
  if (!next) return
  settings[key] = next
  marketResearch.value.sources = { ...marketResearch.value.sources, [id]: settings }
}

/* ---------- 采集页数与抓取方式 ---------- */

/** 时间范围的自定义月数；预设项被选中时清空。 */
const customMonths = ref<number | null>(null)

function pickTimeRange(value: string) {
  marketResearch.value.timeRange = value
  customMonths.value = null
}

function applyCustomTimeRange() {
  const raw = customMonths.value
  if (raw === null || !Number.isFinite(raw)) {
    customMonths.value = null
    return
  }
  const months = Math.min(TIME_RANGE_MAX, Math.max(TIME_RANGE_MIN, Math.round(raw)))
  marketResearch.value.timeRange = `${months}m`
  customMonths.value = months
}

// 已经存过自定义范围时回填输入框，避免界面显示成未选中任何项。
const storedMonths = /^(\d{1,3})m$/.exec(marketResearch.value.timeRange)
if (storedMonths) customMonths.value = Number(storedMonths[1])

/**
 * 输入框独立保存正在编辑的数字，失焦 / 回车时才收窄成合法值，
 * 避免边输入边被改成 1（比如想输 36，输到 3 就被改写）。
 */
type PageLimitField = DimPagesKey | 'urlsPerDim'

function currentLimit(field: PageLimitField): number {
  return field === 'urlsPerDim'
    ? marketResearch.value.urlsPerDim
    : marketResearch.value.pagesPerDim[field]
}

const customPages = reactive<{
  jobs: number | null
  trend: number | null
  other: number | null
  urlsPerDim: number | null
}>({
  jobs: currentLimit('jobs'),
  trend: currentLimit('trend'),
  other: currentLimit('other'),
  urlsPerDim: currentLimit('urlsPerDim'),
})

function setLimit(field: PageLimitField, value: number) {
  if (field === 'urlsPerDim') marketResearch.value.urlsPerDim = value
  else marketResearch.value.pagesPerDim[field] = value
}

function clampLimit(value: number): number {
  return Math.min(DIM_LIMIT_MAX, Math.max(DIM_LIMIT_MIN, Math.round(value)))
}

/** 输入过程中同步合法值；越界留给失焦时的 applyLimit 收窄。 */
function onLimitInput(field: PageLimitField, value: number | null) {
  customPages[field] = value
  if (value === null || !Number.isFinite(value)) return
  setLimit(field, clampLimit(value))
}

function applyLimit(field: PageLimitField) {
  const raw = customPages[field]
  if (raw === null || !Number.isFinite(raw)) {
    // 空值 / 非法输入：回到已保存的值，不留一个空输入框。
    customPages[field] = currentLimit(field)
    return
  }
  const value = clampLimit(raw)
  setLimit(field, value)
  customPages[field] = value
}

const activeAsrLabel = computed(
  () => ASR_MODE_OPTIONS.find((item) => item.value === asrSettings.value.mode)?.label ?? '',
)

const fetchModeHint = computed(
  () => FETCH_MODE_OPTIONS.find((item) => item.value === marketResearch.value.fetchMode)?.hint ?? '',
)

const collectMethodHint = computed(
  () => COLLECT_METHOD_OPTIONS.find((item) => item.value === marketResearch.value.collector)?.hint ?? '',
)

/** DeepSeek 品牌图标：市场洞察采集方式与模拟面试语音识别共用。 */
const DEEPSEEK_ICON = brandSvg(siDeepseek)

/** 采集方式图标：两种方式都有品牌图标。 */
const COLLECT_METHOD_ICONS: Record<string, string> = {
  searxng: brandSvg(siSearxng),
  deepseek: DEEPSEEK_ICON,
}

/** 抓取方式图标：直取是下载，正文解析是从页面里抽文字。 */
const FETCH_MODE_ICONS: Record<string, string> = {
  get: 'download',
  crawler: 'file-text',
}

/* ---------- 信息来源标签库 ---------- */

const sourceDraft = reactive<{
  url: string
  direction: SourceDirection
  note: string
}>({
  url: '',
  direction: 'jobs',
  note: '',
})
const editingSourceId = ref('')
const sourceFormError = ref('')
// 网址按三个方向折叠展示；默认全部收起，避免收藏多了以后把设置页撑成上百个标签。
const openSourceGroup = ref<SourceDirection | ''>('')
const sourceGroups = computed(() =>
  DIRECTION_OPTIONS.map((option) => ({
    ...option,
    entries: marketSources.entries.filter((entry) => entry.direction === option.value),
  })),
)

function toggleSourceGroup(direction: SourceDirection) {
  openSourceGroup.value = openSourceGroup.value === direction ? '' : direction
}

const sourceSyncText = computed(() => {
  if (!supportsFolder) return '当前浏览器不支持本地文件夹，来源只保存在浏览器里'
  if (!documents.isBound) return '未绑定备份文件夹，来源暂存在浏览器本地'
  if (marketSources.savedToFolder) return '已同步到备份库 · market-sources.json'
  return '已保存在浏览器；备份库暂不可写，授权后会重新同步'
})

function resetSourceForm() {
  sourceDraft.url = ''
  sourceDraft.direction = 'jobs'
  sourceDraft.note = ''
  editingSourceId.value = ''
  sourceFormError.value = ''
}

function editSource(entry: MarketSourceEntry) {
  editingSourceId.value = entry.id
  sourceDraft.url = entry.url
  sourceDraft.direction = entry.direction
  sourceDraft.note = entry.note
  sourceFormError.value = ''
  openSourceGroup.value = entry.direction
}

async function submitSource() {
  sourceFormError.value = ''
  if (!sourceDraft.url.trim()) {
    sourceFormError.value = '请先填写网址'
    return
  }
  if (!normalizeSourceUrl(sourceDraft.url)) {
    sourceFormError.value = '网址格式不正确，请填写 http(s):// 开头的完整地址'
    return
  }
  if (!sourceDraft.note.trim()) {
    sourceFormError.value =
      '请填写备注：备注会用来判断「其他」网址该归到哪个调研方面，也用来判定它是否贴近本轮目标岗位'
    return
  }
  const input = {
    url: sourceDraft.url,
    direction: sourceDraft.direction,
    note: sourceDraft.note,
  }
  const ok = editingSourceId.value
    ? await marketSources.update(editingSourceId.value, input)
    : await marketSources.add(input)
  if (!ok) {
    sourceFormError.value = '这个网址已经添加过了'
    return
  }
  // 新增 / 编辑后展开对应方向，确认它落在正确的分类里。
  openSourceGroup.value = sourceDraft.direction
  resetSourceForm()
}

function removeSource(entry: MarketSourceEntry) {
  dialog.warning({
    title: '删除来源？',
    content: `将从本地来源库和 market-sources.json 中删除 ${sourceHost(entry.url)}。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await marketSources.remove(entry.id)
      if (editingSourceId.value === entry.id) resetSourceForm()
    },
  })
}

function resetResearch() {
  marketResearch.value = {
    ...DEFAULT_MARKET_RESEARCH,
    // 嵌套对象要复制，否则改页数会改到默认常量本身。
    pagesPerDim: { ...DEFAULT_MARKET_RESEARCH.pagesPerDim },
    collectorSettings: { ...DEFAULT_MARKET_RESEARCH.collectorSettings },
    sources: { ...DEFAULT_MARKET_RESEARCH.sources },
  }
  customMonths.value = null
  customPages.jobs = currentLimit('jobs')
  customPages.trend = currentLimit('trend')
  customPages.other = currentLimit('other')
  customPages.urlsPerDim = currentLimit('urlsPerDim')
  message.success('已恢复默认采集参数')
}

onMounted(() => {
  void marketSources.load(true)
})

// 从其他分组切回市场洞察时重新对齐一次文件，外部改过 JSON 也能反映到界面。
watch(tab, (value) => {
  if (value === 'market') void marketSources.load(true)
})

// 文件夹刚完成授权时补读一次，避免界面一直停在浏览器缓存版本。
watch(
  () => documents.status,
  (value) => {
    if (value === 'ready' && tab.value === 'market') void marketSources.load(true)
  },
)

async function openMd() {
  tab.value = 'md'
  if (mdLoaded.value || loading.value) return
  loading.value = true
  try {
    md.value = await getAgentMd()
    mdLoaded.value = true
    selected.value = md.value.prompts[0] ?? md.value.skills[0] ?? null
  } catch (err) {
    message.error(`加载失败：${err instanceof Error ? err.message : String(err)}`)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="settings-page">
    <div class="settings-shell">
      <div class="settings-grid">
        <aside class="settings-nav">
          <div class="nav-caption">配置项</div>
          <button
            class="nav-item"
            :class="{ active: tab === 'provider' }"
            @click="tab = 'provider'"
          >
            <span class="nav-icon"><IconGlyph name="sliders-horizontal" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">OpenAI 设置</span>
              <span class="nav-hint">接口地址与模型</span>
            </span>
          </button>
          <button
            class="nav-item"
            :class="{ active: tab === 'backup' }"
            @click="tab = 'backup'"
          >
            <span class="nav-icon"><IconGlyph name="folder" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">本地备份</span>
              <span class="nav-hint">文件夹与导出位置</span>
            </span>
          </button>
          <button
            class="nav-item"
            :class="{ active: tab === 'market' }"
            @click="tab = 'market'"
          >
            <span class="nav-icon"><IconGlyph name="move" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">市场洞察</span>
              <span class="nav-hint">调研参数与光点动效</span>
            </span>
          </button>
          <button
            class="nav-item"
            :class="{ active: tab === 'interview' }"
            @click="tab = 'interview'"
          >
            <span class="nav-icon"><IconGlyph name="mic" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">模拟面试</span>
              <span class="nav-hint">语音识别方式</span>
            </span>
          </button>
          <button class="nav-item" :class="{ active: tab === 'md' }" @click="openMd">
            <span class="nav-icon"><IconGlyph name="book-open" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">提示词预览</span>
              <span class="nav-hint">提示词与技能文档</span>
            </span>
          </button>
        </aside>

        <section :key="tab" class="settings-panel">
          <template v-if="tab === 'provider'">
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">OpenAI 设置</h2>
                <p class="panel-desc">
                  支持任何兼容 OpenAI 格式的接口地址与模型名。保存后，优化对话与提示词增强都会使用这里的配置。
                </p>
              </div>
              <span class="panel-badge">
                <span class="badge-dot" aria-hidden="true"></span>
                OpenAI 兼容
              </span>
            </div>

            <div class="form">
              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">接口地址</span>
                  <span class="field-hint">Base URL，需兼容 OpenAI 接口格式</span>
                </div>
                <div class="field-control">
                  <n-input
                    v-model:value="draft.baseUrl"
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
              </div>

              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">API Key</span>
                  <span class="field-hint">只写入当前浏览器，不会上传到其他服务</span>
                </div>
                <div class="field-control">
                  <n-input
                    v-model:value="draft.apiKey"
                    type="password"
                    show-password-on="click"
                    placeholder="sk-..."
                  />
                </div>
              </div>

              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">模型名称</span>
                  <span class="field-hint">例如 gpt-4o-mini、gpt-4.1</span>
                </div>
                <div class="field-control">
                  <n-input v-model:value="draft.model" placeholder="gpt-4o-mini" />
                </div>
              </div>
            </div>

            <footer class="panel-foot">
              <p class="foot-note">配置保存后立即生效，并按当前浏览器分别保存。</p>
              <div class="foot-actions">
                <n-button size="small" quaternary @click="onTest">测试连接</n-button>
                <n-button size="small" type="primary" @click="onSave">保存设置</n-button>
              </div>
            </footer>
          </template>

          <template v-else-if="tab === 'backup'">
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">本地备份</h2>
                <p class="panel-desc">
                  选一个电脑上的文件夹当简历库：每份简历存成一个 JSON 文件，导出的 PDF 也写到这里。
                  文件只留在本机，不会上传。
                </p>
              </div>
              <span class="panel-badge">
                <IconGlyph name="folder" :size="13" />
                仅本地
              </span>
            </div>

            <div class="form">
              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">备份文件夹</span>
                  <span class="field-hint">Chrome / Edge 支持；选择后浏览器会询问读写权限</span>
                </div>
                <div class="field-control">
                  <div class="backup-folder-row">
                    <div class="backup-folder-value" :class="{ empty: !documents.folderName }">
                      <IconGlyph name="folder" :size="15" />
                      <span>{{ documents.folderName || '尚未选择文件夹' }}</span>
                    </div>
                    <n-button
                      size="small"
                      :disabled="!supportsFolder"
                      @click="onChooseFolder"
                    >
                      {{ documents.folderName ? '更换文件夹' : '选择文件夹' }}
                    </n-button>
                  </div>
                  <div class="backup-status-row">
                    <span class="backup-status" :class="statusClass">
                      <span class="backup-status-dot" aria-hidden="true"></span>
                      {{ statusText }}
                    </span>
                    <span class="backup-hint">文件夹内 {{ documents.files.length }} 份简历</span>
                  </div>
                  <p v-if="!supportsFolder" class="backup-warn">
                    当前浏览器不支持选择文件夹，请使用 Chrome 或 Edge。其他功能（包括下载到电脑）不受影响。
                  </p>
                </div>
              </div>

              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">同步</span>
                  <span class="field-hint">扫描文件夹、写入当前简历，并检测文件夹里的外部修改</span>
                </div>
                <div class="field-control">
                  <div class="backup-action-row">
                    <n-button
                      size="small"
                      type="primary"
                      :loading="documents.busy"
                      :disabled="!supportsFolder || !documents.isBound"
                      @click="onSync"
                    >
                      立即同步
                    </n-button>
                    <n-button
                      size="small"
                      quaternary
                      :disabled="!documents.isBound"
                      @click="onAuthorize"
                    >
                      重新授权
                    </n-button>
                    <n-button
                      size="small"
                      quaternary
                      type="error"
                      :disabled="!documents.isBound"
                      @click="onDisconnect"
                    >
                      断开连接
                    </n-button>
                  </div>
                  <p class="backup-meta">最近同步：{{ formatDateTime(documents.lastSyncAt) }}</p>
                </div>
              </div>
            </div>

            <footer class="panel-foot">
              <p class="foot-note">断开连接只会忘记这个文件夹，不会删除里面的 JSON / PDF 文件。</p>
              <span class="backup-foot-note">JSON 与「导出 JSON」格式完全一致</span>
            </footer>
          </template>

          <template v-else-if="tab === 'market'">
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">市场洞察设置</h2>
                <p class="panel-desc">市场洞察页面的界面与行为设置，按功能分组管理。</p>
              </div>
              <span class="panel-badge">
                <IconGlyph name="move" :size="13" />
                市场洞察
              </span>
            </div>

            <div class="settings-sections">
              <section class="settings-section">
                <div class="section-head">
                  <div class="section-head-copy">
                    <h3 class="section-title">采集参数</h3>
                    <n-tooltip trigger="hover" :style="{ maxWidth: '400px' }">
                      <template #trigger>
                        <p class="section-desc tip" tabindex="0">
                          时间窗口、采集规模、抓取方式与数据来源
                          <IconGlyph name="info" :size="12" />
                        </p>
                      </template>
                      控制采集规模、抓取方式与来源，从下一轮调研开始生效。
                    </n-tooltip>
                  </div>
                  <div class="section-actions">
                    <n-button size="small" quaternary @click="resetResearch">恢复默认</n-button>
                  </div>
                </div>

                <div class="form">
                  <div class="form-group-label">采集规模</div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">时间范围</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '360px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            只保留窗口内的页面
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        只保留窗口内的页面，检索词会换算成绝对年月。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="limit-control">
                        <div class="segmented" role="group" aria-label="时间范围">
                          <button
                            v-for="item in TIME_RANGE_OPTIONS"
                            :key="item.value"
                            type="button"
                            :class="{ active: marketResearch.timeRange === item.value }"
                            @click="pickTimeRange(item.value)"
                          >
                            {{ item.label }}
                          </button>
                        </div>
                        <label
                          class="limit-custom"
                          :class="{ active: isCustomTimeRange(marketResearch.timeRange) }"
                        >
                          <span class="limit-custom-label">自定义</span>
                          <n-input-number
                            v-model:value="customMonths"
                            class="limit-input"
                            size="small"
                            :min="TIME_RANGE_MIN"
                            :max="TIME_RANGE_MAX"
                            :show-button="false"
                            placeholder="1~120"
                            @blur="applyCustomTimeRange"
                            @keyup.enter="applyCustomTimeRange"
                          />
                          <span class="limit-custom-label">个月</span>
                        </label>
                      </div>
                    </div>
                  </div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">采集页数</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '420px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            每个维度各自抓取的上限
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        招聘矩阵、技术趋势与其他方向各自抓取的页数上限，不在维度之间分摊。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="dim-limits">
                        <label
                          v-for="field in PAGE_DIM_OPTIONS"
                          :key="field.key"
                          class="dim-limit"
                          :title="field.hint"
                        >
                          <span class="dim-limit-label">{{ field.label }}</span>
                          <n-input-number
                            :value="customPages[field.key]"
                            class="dim-limit-input"
                            size="small"
                            :min="DIM_LIMIT_MIN"
                            :max="DIM_LIMIT_MAX"
                            :show-button="false"
                            @update:value="(value: number | null) => onLimitInput(field.key, value)"
                            @blur="applyLimit(field.key)"
                            @keyup.enter="applyLimit(field.key)"
                          />
                          <span class="dim-limit-unit">页</span>
                        </label>
                      </div>
                    </div>
                  </div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">采集方式</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '420px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            决定怎么把检索词变成页面
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        {{ collectMethodHint }}。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="builtin-sources">
                        <n-popover
                          v-for="item in COLLECT_METHOD_OPTIONS"
                          :key="item.value"
                          trigger="hover"
                          placement="bottom-start"
                          :delay="120"
                          :show-arrow="false"
                          keep-alive-on-hover
                          raw
                        >
                          <template #trigger>
                            <button
                              type="button"
                              class="builtin-source"
                              :class="{ active: marketResearch.collector === item.value }"
                              :aria-label="item.label"
                              :aria-pressed="marketResearch.collector === item.value"
                              @click="marketResearch.collector = item.value"
                            >
                              <span
                                class="builtin-source-icon"
                                v-html="COLLECT_METHOD_ICONS[item.value]"
                              />
                              <span class="builtin-source-dot" aria-hidden="true" />
                            </button>
                          </template>
                          <div class="builtin-source-card collector-card">
                            <div class="builtin-source-card-head">
                              <span class="builtin-source-card-name">{{ item.label }}</span>
                              <span
                                class="builtin-source-card-state"
                                :class="{ on: marketResearch.collector === item.value }"
                              >
                                {{ marketResearch.collector === item.value ? '使用中' : '未使用' }}
                              </span>
                            </div>
                            <p class="collector-card-hint">{{ item.hint }}</p>
                            <template v-if="item.value === 'deepseek'">
                              <label class="collector-card-field">
                                <span class="builtin-source-card-label">Base URL</span>
                                <n-input
                                  v-model:value="marketResearch.collectorSettings.baseUrl"
                                  size="small"
                                  placeholder="https://api.deepseek.com"
                                />
                              </label>
                              <label class="collector-card-field">
                                <span class="builtin-source-card-label">API Key</span>
                                <n-input
                                  v-model:value="marketResearch.collectorSettings.apiKey"
                                  size="small"
                                  type="password"
                                  show-password-on="click"
                                  placeholder="sk-..."
                                />
                              </label>
                              <span
                                v-if="!marketResearch.collectorSettings.apiKey"
                                class="collector-card-warn"
                              >
                                未填写 Key 时，使用该方式的轮次采不到页面
                              </span>
                            </template>
                            <button
                              type="button"
                              class="builtin-source-card-toggle"
                              :disabled="marketResearch.collector === item.value"
                              @click="marketResearch.collector = item.value"
                            >
                              {{ marketResearch.collector === item.value ? '当前采集方式' : '切换到该方式' }}
                            </button>
                          </div>
                        </n-popover>
                        <span class="builtin-sources-hint">点击切换 · 悬浮配置</span>
                      </div>
                    </div>
                  </div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">抓取方式</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '420px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            决定每个网址怎么取正文
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        {{ fetchModeHint }}。只影响取正文方式，不改变采集哪些网址。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="builtin-sources">
                        <n-popover
                          v-for="item in FETCH_MODE_OPTIONS"
                          :key="item.value"
                          trigger="hover"
                          placement="bottom-start"
                          :delay="120"
                          :show-arrow="false"
                          raw
                        >
                          <template #trigger>
                            <button
                              type="button"
                              class="builtin-source"
                              :class="{ active: marketResearch.fetchMode === item.value }"
                              :aria-label="item.label"
                              :aria-pressed="marketResearch.fetchMode === item.value"
                              @click="marketResearch.fetchMode = item.value"
                            >
                              <span class="builtin-source-icon">
                                <IconGlyph :name="FETCH_MODE_ICONS[item.value]" :size="20" />
                              </span>
                              <span class="builtin-source-dot" aria-hidden="true" />
                            </button>
                          </template>
                          <div class="builtin-source-card collector-card">
                            <div class="builtin-source-card-head">
                              <span class="builtin-source-card-name">{{ item.label }}</span>
                              <span
                                class="builtin-source-card-state"
                                :class="{ on: marketResearch.fetchMode === item.value }"
                              >
                                {{ marketResearch.fetchMode === item.value ? '使用中' : '未使用' }}
                              </span>
                            </div>
                            <p class="collector-card-hint">{{ item.hint }}</p>
                            <button
                              type="button"
                              class="builtin-source-card-toggle"
                              :disabled="marketResearch.fetchMode === item.value"
                              @click="marketResearch.fetchMode = item.value"
                            >
                              {{ marketResearch.fetchMode === item.value ? '当前抓取方式' : '切换到该方式' }}
                            </button>
                          </div>
                        </n-popover>
                        <span class="builtin-sources-hint">点击切换 · 悬浮查看</span>
                      </div>
                    </div>
                  </div>

                  <div class="form-group-label">数据来源</div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">内置来源</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '320px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            勾选后只取内置来源
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        启用后招聘维度只取选中来源，不再回落到 SearXNG；全部停用时才走聚合搜索。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="builtin-sources">
                        <n-popover
                          v-for="source in BUILTIN_SOURCES"
                          :key="source.id"
                          trigger="hover"
                          placement="bottom-start"
                          :delay="120"
                          :show-arrow="false"
                          raw
                        >
                          <template #trigger>
                            <button
                              type="button"
                              class="builtin-source"
                              :class="{ active: isSourceEnabled(source.id) }"
                              :aria-label="source.label"
                              :aria-pressed="isSourceEnabled(source.id)"
                              @click="toggleSource(source.id)"
                            >
                              <span
                                v-if="sourceIcon(source)"
                                class="builtin-source-icon"
                                :class="source.icon"
                                v-html="sourceIcon(source)"
                              />
                              <IconGlyph v-else name="briefcase" :size="20" />
                              <span class="builtin-source-dot" aria-hidden="true" />
                            </button>
                          </template>
                          <div class="builtin-source-card">
                            <div class="builtin-source-card-head">
                              <span class="builtin-source-card-name">{{ source.label }}</span>
                              <span
                                class="builtin-source-card-state"
                                :class="{ on: isSourceEnabled(source.id) }"
                              >
                                {{ isSourceEnabled(source.id) ? '已启用' : '未启用' }}
                              </span>
                            </div>
                            <label
                              v-for="setting in source.settings"
                              :key="setting.key"
                              class="builtin-source-card-setting"
                            >
                              <span class="builtin-source-card-label">{{ setting.label }}</span>
                              <n-select
                                class="builtin-source-select"
                                size="small"
                                :value="sourceSetting(source.id, setting.key) || setting.default || null"
                                :options="setting.options"
                                :disabled="!isSourceEnabled(source.id)"
                                :clearable="false"
                                @update:value="
                                  (value: string | null) =>
                                    setSourceSetting(source.id, setting.key, value)
                                "
                              />
                            </label>
                            <div
                              v-if="sourceLinks(source).length"
                              class="builtin-source-card-links"
                            >
                              <a
                                v-for="link in sourceLinks(source)"
                                :key="link.key"
                                :href="link.url"
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {{ link.label }} ↗
                              </a>
                            </div>
                            <button
                              type="button"
                              class="builtin-source-card-toggle"
                              @click="toggleSource(source.id)"
                            >
                              {{ isSourceEnabled(source.id) ? '停用来源' : '启用来源' }}
                            </button>
                          </div>
                        </n-popover>
                        <span class="builtin-sources-hint">点击启用 · 悬浮配置</span>
                      </div>
                    </div>
                  </div>

                  <div class="form-group-label">补充网址</div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">网址页数</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '420px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            每个方向最多用的补充网址
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        每个方向最多使用的补充网址，按备注筛选后截断。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="dim-limits">
                        <label class="dim-limit">
                          <span class="dim-limit-label">每个方向最多</span>
                          <n-input-number
                            :value="customPages.urlsPerDim"
                            class="dim-limit-input"
                            size="small"
                            :min="DIM_LIMIT_MIN"
                            :max="DIM_LIMIT_MAX"
                            :show-button="false"
                            @update:value="(value: number | null) => onLimitInput('urlsPerDim', value)"
                            @blur="applyLimit('urlsPerDim')"
                            @keyup.enter="applyLimit('urlsPerDim')"
                          />
                          <span class="dim-limit-unit">条</span>
                        </label>
                      </div>
                    </div>
                  </div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">来源标签</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '380px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            按方向归档，备注必填
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        按方向归档，备注必填；采集前再按备注筛选相关性。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="source-groups">
                        <div
                          v-for="group in sourceGroups"
                          :key="group.value"
                          class="source-group"
                          :class="{ open: openSourceGroup === group.value }"
                        >
                          <button
                            type="button"
                            class="source-group-head"
                            :aria-expanded="openSourceGroup === group.value"
                            @click="toggleSourceGroup(group.value)"
                          >
                            <span class="group-label">{{ group.label }}</span>
                            <span class="group-count">{{ group.entries.length }}</span>
                            <IconGlyph name="chevron-down" :size="13" class="group-caret" />
                          </button>
                          <div v-if="openSourceGroup === group.value" class="source-tags">
                            <span
                              v-for="entry in group.entries"
                              :key="entry.id"
                              class="source-tag"
                              :class="{ editing: editingSourceId === entry.id }"
                            >
                              <span class="tag-title">{{ sourceHost(entry.url) }}</span>
                              <span v-if="entry.note" class="tag-note" :title="entry.note">
                                {{ entry.note }}
                              </span>
                              <span v-else class="tag-note empty" title="备注用于筛选网址，请补填">
                                缺少备注
                              </span>
                              <button
                                type="button"
                                class="tag-action"
                                aria-label="编辑来源"
                                @click="editSource(entry)"
                              >
                                <IconGlyph name="pen-line" :size="12" />
                              </button>
                              <button
                                type="button"
                                class="tag-action danger"
                                aria-label="删除来源"
                                @click="removeSource(entry)"
                              >
                                <IconGlyph name="x" :size="12" />
                              </button>
                            </span>
                            <span v-if="!group.entries.length" class="source-tag empty">
                              <IconGlyph name="plus" :size="12" />
                              这个方向还没有网址
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">{{ editingSourceId ? '编辑来源' : '添加来源' }}</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '400px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            按上方「抓取方式」取正文
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        粘贴完整网址并选择方向；按上方抓取方式取正文，需登录的页面取不到内容。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <div class="source-form">
                        <n-input
                          v-model:value="sourceDraft.url"
                          placeholder="https://careers.example.com/jobs"
                          @keyup.enter="submitSource"
                        />
                        <div class="source-form-row">
                          <div class="segmented" role="group" aria-label="调研方向">
                            <button
                              v-for="item in DIRECTION_OPTIONS"
                              :key="item.value"
                              type="button"
                              :class="{ active: sourceDraft.direction === item.value }"
                              @click="sourceDraft.direction = item.value"
                            >
                              {{ item.label }}
                            </button>
                          </div>
                          <n-input
                            v-model:value="sourceDraft.note"
                            class="source-note"
                            placeholder="备注（必填）：岗位 / 方向 / 级别"
                            @keyup.enter="submitSource"
                          />
                          <n-button
                            size="small"
                            type="primary"
                            :loading="marketSources.saving"
                            @click="submitSource"
                          >
                            {{ editingSourceId ? '保存' : '添加' }}
                          </n-button>
                          <n-button v-if="editingSourceId" size="small" quaternary @click="resetSourceForm">
                            取消
                          </n-button>
                        </div>
                        <p v-if="sourceFormError" class="source-error">{{ sourceFormError }}</p>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section class="settings-section">
                <div class="section-head">
                  <div class="section-head-copy">
                    <h3 class="section-title">光点箭头</h3>
                    <n-tooltip trigger="hover" :style="{ maxWidth: '400px' }">
                      <template #trigger>
                        <p class="section-desc tip" tabindex="0">
                          调整颜色、方向、长短与速度
                          <IconGlyph name="info" :size="12" />
                        </p>
                      </template>
                      控制调研流程图里光点箭头的颜色、方向、长短和飞行速度。固定模式统一颜色 / 长短 / 速度，方向默认逐条随机；随机模式下所有参数都由每个箭头单独抽取。
                    </n-tooltip>
                  </div>
                  <div class="section-actions">
                    <n-button size="small" quaternary @click="replayPreview">重新预览</n-button>
                    <n-button size="small" quaternary @click="resetMotion">恢复默认</n-button>
                  </div>
                </div>

                <div class="form">
                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">动效模式</span>
                      <span class="field-hint">切换后立即生效，并保存在当前浏览器</span>
                    </div>
                    <div class="field-control">
                      <div class="motion-mode" role="group" aria-label="动效模式">
                        <button
                          type="button"
                          :class="{ active: marketMotion.mode === 'fixed' }"
                          @click="marketMotion.mode = 'fixed'"
                        >
                          固定
                        </button>
                        <button
                          type="button"
                          :class="{ active: marketMotion.mode === 'random' }"
                          @click="marketMotion.mode = 'random'"
                        >
                          随机
                        </button>
                      </div>
                    </div>
                  </div>

                  <div class="field-row">
                    <div class="field-info">
                      <span class="field-label">方向随机</span>
                      <n-tooltip trigger="hover" :style="{ maxWidth: '380px' }">
                        <template #trigger>
                          <span class="field-hint tip" tabindex="0">
                            弧线方向与幅度逐条随机
                            <IconGlyph name="info" :size="12" />
                          </span>
                        </template>
                        每个箭头的弧线独立向上或向下弯，弯曲幅度也会随机抖动；同向箭头允许连续出现，避免看起来像「一上一下」的固定交替。
                      </n-tooltip>
                    </div>
                    <div class="field-control">
                      <n-switch v-model:value="marketMotion.directionRandom" />
                    </div>
                  </div>

                  <template v-if="marketMotion.mode === 'fixed'">
                    <div class="field-row">
                      <div class="field-info">
                        <span class="field-label">箭头颜色</span>
                        <span class="field-hint">分别对应三类光点链路</span>
                      </div>
                      <div class="field-control">
                        <div class="motion-colors">
                          <label
                            v-for="channel in MOTION_CHANNELS"
                            :key="channel.key"
                            class="motion-color"
                          >
                            <input v-model="marketMotion.colors[channel.key]" type="color" />
                            <span>{{ channel.label }}</span>
                          </label>
                        </div>
                      </div>
                    </div>

                    <div class="field-row">
                      <div class="field-info">
                        <span class="field-label">拖尾长度</span>
                        <span class="field-hint">基准长度，各链路按原比例缩放</span>
                      </div>
                      <div class="field-control">
                        <div class="motion-slider">
                          <n-slider v-model:value="marketMotion.tail" :min="80" :max="600" :step="10" />
                          <span class="motion-slider-value">{{ marketMotion.tail }} px</span>
                        </div>
                      </div>
                    </div>

                    <div class="field-row">
                      <div class="field-info">
                        <span class="field-label">飞行时长</span>
                        <span class="field-hint">基准时长，数值越小飞得越快</span>
                      </div>
                      <div class="field-control">
                        <div class="motion-slider">
                          <n-slider
                            v-model:value="marketMotion.duration"
                            :min="200"
                            :max="1600"
                            :step="20"
                          />
                          <span class="motion-slider-value">{{ marketMotion.duration }} ms</span>
                        </div>
                      </div>
                    </div>

                    <div class="field-row">
                      <div class="field-info">
                        <span class="field-label">线宽</span>
                        <span class="field-hint">光点箭头的粗细</span>
                      </div>
                      <div class="field-control">
                        <div class="motion-slider">
                          <n-slider
                            v-model:value="marketMotion.width"
                            :min="3"
                            :max="14"
                            :step="0.5"
                          />
                          <span class="motion-slider-value">{{ marketMotion.width }} px</span>
                        </div>
                      </div>
                    </div>
                  </template>

                  <template v-else>
                    <div class="field-row">
                      <div class="field-info">
                        <span class="field-label">随机范围</span>
                        <span class="field-hint">每个箭头独立抽取，互不影响</span>
                      </div>
                      <div class="field-control">
                        <div class="motion-random">
                          <div class="motion-palette" aria-hidden="true">
                            <span
                              v-for="color in RANDOM_MOTION_COLORS"
                              :key="color"
                              class="motion-swatch"
                              :style="{ background: color }"
                            ></span>
                          </div>
                          <p class="motion-note">
                            颜色从 {{ RANDOM_MOTION_COLORS.length }} 色中随机；弧线方向与幅度随机（弧度
                            {{ RANDOM_RANGES.bow[0] }}–{{ RANDOM_RANGES.bow[1] }} px）；拖尾
                            {{ RANDOM_RANGES.tail[0] }}–{{ RANDOM_RANGES.tail[1] }} px；飞行时长
                            {{ RANDOM_RANGES.duration[0] }}–{{ RANDOM_RANGES.duration[1] }} ms；线宽
                            {{ RANDOM_RANGES.width[0] }}–{{ RANDOM_RANGES.width[1] }} px。
                          </p>
                        </div>
                      </div>
                    </div>
                  </template>
                </div>

                <div class="motion-preview">
                  <div class="motion-preview-head">
                    <span>效果预览</span>
                    <span>{{ marketMotion.mode === 'random' ? '每轮重新随机' : '固定参数' }}</span>
                  </div>
                  <div class="motion-lanes">
                    <div v-for="lane in previewLanes" :key="lane.key" class="motion-lane">
                      <span class="motion-target"></span>
                      <span class="motion-flight" :style="laneStyle(lane)"></span>
                    </div>
                  </div>
                </div>
              </section>
            </div>

            <footer class="panel-foot">
              <p class="foot-note">设置只保存在当前浏览器，不会上传。</p>
            </footer>
          </template>

          <template v-else-if="tab === 'interview'">
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">模拟面试设置</h2>
                <p class="panel-desc">作答与讲解输入框的语音识别方式。</p>
              </div>
              <span class="panel-badge">
                <IconGlyph name="mic" :size="13" />
                语音输入
              </span>
            </div>

            <div class="form">
              <div class="field-row">
                <div class="field-info">
                  <span class="field-label asr-label">
                    语音识别
                    <n-tooltip trigger="hover" :style="{ maxWidth: '420px' }">
                      <template #trigger>
                        <span class="asr-tip" tabindex="0" aria-label="语音输入使用建议">
                          <IconGlyph name="info" :size="13" />
                        </span>
                      </template>
                      可以用系统或输入法自带的语音输入，比如 Windows 语音输入、macOS
                      听写、手机输入法的语音转文字；另外也可以试试豆包、VocoType
                      等第三方语音输入工具。
                    </n-tooltip>
                  </span>
                  <span class="field-hint">点击切换，悬浮查看说明</span>
                </div>
                <div class="field-control">
                  <div class="builtin-sources">
                    <n-popover
                      v-for="item in ASR_MODE_OPTIONS"
                      :key="item.value"
                      trigger="hover"
                      placement="bottom-start"
                      :delay="120"
                      :show-arrow="false"
                      keep-alive-on-hover
                      raw
                    >
                      <template #trigger>
                        <button
                          type="button"
                          class="builtin-source"
                          :class="{ active: asrSettings.mode === item.value }"
                          :aria-label="item.label"
                          :aria-pressed="asrSettings.mode === item.value"
                          @click="asrSettings.mode = item.value"
                        >
                          <span
                            v-if="item.value === 'deepseek'"
                            class="builtin-source-icon"
                            v-html="DEEPSEEK_ICON"
                          />
                          <span v-else class="builtin-source-icon">
                            <IconGlyph name="audio-waveform" :size="20" />
                          </span>
                          <span class="builtin-source-dot" aria-hidden="true" />
                        </button>
                      </template>
                      <div class="builtin-source-card collector-card">
                        <div class="builtin-source-card-head">
                          <span class="builtin-source-card-name">{{ item.label }}</span>
                          <span
                            class="builtin-source-card-state"
                            :class="{ on: asrSettings.mode === item.value }"
                          >
                            {{ asrSettings.mode === item.value ? '使用中' : '未使用' }}
                          </span>
                        </div>
                        <p class="collector-card-hint">{{ item.hint }}</p>
                        <template v-if="item.value === 'deepseek'">
                          <label class="collector-card-field">
                            <span class="builtin-source-card-label">Base URL</span>
                            <n-input
                              v-model:value="asrSettings.deepseek.baseUrl"
                              size="small"
                              :placeholder="DEFAULT_DEEPSEEK_BASE_URL"
                            />
                          </label>
                          <label class="collector-card-field">
                            <span class="builtin-source-card-label">API Key</span>
                            <n-input
                              v-model:value="asrSettings.deepseek.apiKey"
                              size="small"
                              type="password"
                              show-password-on="click"
                              placeholder="sk-..."
                            />
                          </label>
                          <span
                            v-if="!asrSettings.deepseek.apiKey"
                            class="collector-card-warn"
                          >
                            未填写 Key 时无法使用该方式识别
                          </span>
                        </template>
                        <button
                          type="button"
                          class="builtin-source-card-toggle"
                          :disabled="asrSettings.mode === item.value"
                          @click="asrSettings.mode = item.value"
                        >
                          {{ asrSettings.mode === item.value ? '当前识别方式' : '切换到该方式' }}
                        </button>
                      </div>
                    </n-popover>
                    <span class="builtin-sources-hint">{{ activeAsrLabel }}</span>
                  </div>
                </div>
              </div>
            </div>

            <footer class="panel-foot">
              <p class="foot-note">
                设置只保存在当前浏览器；DeepSeek 模式会把录音临时上传到所填接口。
              </p>
            </footer>
          </template>

          <template v-else>
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">提示词预览</h2>
                <p class="panel-desc">
                  只读展示后端 Agent 加载的提示词与技能文档，内容按 Markdown 排版渲染。
                </p>
              </div>
              <span class="panel-badge">
                <IconGlyph name="shield-check" :size="13" />
                只读
              </span>
            </div>

            <div class="md-layout">
              <aside class="md-list">
                <template v-if="loading">
                  <span v-for="i in 5" :key="i" class="sk sk-item"></span>
                </template>
                <template v-else>
                  <template v-for="group in promptGroups" :key="group.key">
                    <div class="md-group">
                      <span>{{ group.label }}</span>
                      <span class="md-count">{{ group.items.length }}</span>
                    </div>
                    <button
                      v-for="(f, i) in group.items"
                      :key="group.key + i"
                      class="md-item"
                      :class="{ active: selected === f }"
                      @click="selected = f"
                    >
                      <IconGlyph name="file-text" :size="14" class="md-item-icon" />
                      <span class="md-item-name">{{ f.name }}</span>
                    </button>
                  </template>

                  <div class="md-group">
                    <span>技能</span>
                    <span class="md-count">{{ md.skills.length }}</span>
                  </div>
                  <button
                    v-for="(f, i) in md.skills"
                    :key="'s' + i"
                    class="md-item"
                    :class="{ active: selected === f }"
                    @click="selected = f"
                  >
                    <IconGlyph name="file-text" :size="14" class="md-item-icon" />
                    <span class="md-item-name">{{ f.name }}</span>
                  </button>
                </template>
              </aside>

              <div class="md-viewer">
                <div class="md-viewer-head">
                  <span class="md-path">{{ selected?.path || '未选择文件' }}</span>
                  <span v-if="selected" class="md-type">{{ selectedKind }} · Markdown</span>
                </div>

                <div v-if="loading" class="md-doc">
                  <div class="doc-skeleton">
                    <span class="sk sk-title"></span>
                    <span v-for="i in 6" :key="i" class="sk sk-line" :class="{ short: i % 3 === 0 }"></span>
                  </div>
                </div>
                <div v-else-if="selected" class="md-doc">
                  <div class="md-doc-inner" v-html="mdHtml"></div>
                </div>
                <div v-else class="md-empty">
                  <span class="md-empty-icon"><IconGlyph name="file-text" :size="20" /></span>
                  <p class="md-empty-text">选择左侧文件查看内容</p>
                </div>
              </div>
            </div>
          </template>
        </section>
      </div>
    </div>
  </main>
</template>

<style scoped>
.settings-page {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--app-bg);
}
.settings-shell {
  max-width: 1560px;
  margin: 0 auto;
  padding: 24px 28px 56px;
}

.settings-grid {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  animation: settings-rise 0.32s var(--ease) 0.04s both;
}
.settings-nav {
  flex: none;
  width: 230px;
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.03);
}
.nav-caption {
  padding: 8px 10px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.nav-item:hover {
  background: var(--surface-soft);
}
.nav-item.active {
  background: var(--primary-soft);
}
.nav-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 2px;
  border-radius: 2px;
  background: transparent;
  transition: background 0.16s var(--ease);
}
.nav-item.active::before {
  background: var(--primary);
}
.nav-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.nav-item:hover .nav-icon {
  color: var(--text-secondary);
}
.nav-item.active .nav-icon {
  background: var(--panel-bg);
  color: var(--primary);
}
.nav-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.nav-label {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.35;
  color: var(--text-secondary);
}
.nav-item.active .nav-label {
  color: var(--primary-hover);
  font-weight: 600;
}
.nav-hint {
  font-size: 12px;
  line-height: 1.4;
  color: var(--text-tertiary);
}
.nav-item.active .nav-hint {
  color: var(--primary);
  opacity: 0.66;
}

.settings-panel {
  flex: 1;
  min-width: 0;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.03);
  overflow: hidden;
  animation: panel-in 0.24s var(--ease) both;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.panel-head-copy {
  flex: 1 1 240px;
  min-width: 0;
}
.panel-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.panel-desc {
  margin: 5px 0 0;
  max-width: 620px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-tertiary);
}
.panel-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--primary-faint);
  border: 1px solid var(--primary-soft);
  font-size: 12px;
  font-weight: 500;
  color: var(--primary-hover);
  white-space: nowrap;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

.form {
  padding: 0 22px;
}
.field-row {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
  padding: 16px 0;
  border-bottom: 1px solid var(--border);
}
.field-row:last-child {
  border-bottom: none;
}
.field-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding-top: 7px;
}
.field-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.field-hint {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.field-hint.tip,
.section-desc.tip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  align-self: flex-start;
  width: fit-content;
  cursor: help;
  text-decoration: underline dotted color-mix(in srgb, var(--text-tertiary) 45%, transparent);
  text-underline-offset: 3px;
  transition: color 0.16s var(--ease);
}
.field-hint.tip:hover,
.field-hint.tip:focus-visible,
.section-desc.tip:hover,
.section-desc.tip:focus-visible {
  color: var(--text-secondary);
  outline: none;
}
.field-control {
  min-width: 0;
  max-width: 880px;
}
.field-control :deep(.n-input) {
  background: var(--surface-soft);
  border-radius: 9px;
  transition:
    background-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.field-control :deep(.n-input:hover) {
  background: var(--panel-bg);
}
.field-control :deep(.n-input--focus) {
  background: var(--panel-bg);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.1);
}

.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 22px;
  border-top: 1px solid var(--border);
  background: var(--surface-soft);
}
.foot-note {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

/* ---------- 市场洞察设置 ---------- */
.settings-sections {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 18px 22px 22px;
}
.settings-section {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel-bg);
  overflow: hidden;
}
.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-soft);
}
.section-head-copy {
  flex: 1 1 260px;
  min-width: 0;
}
.section-title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
}
.section-desc {
  margin: 4px 0 0;
  max-width: 620px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-tertiary);
}
.section-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.settings-section .form {
  padding: 0 18px;
}
.settings-section .motion-preview {
  margin: 0 18px 18px;
}
/* 合并模块内部的分组标签：只做视觉分段，不另起卡片。 */
.form-group-label {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 0 4px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-tertiary);
  text-transform: none;
}
.form-group-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
.form-group-label + .field-row {
  padding-top: 10px;
}
/* 预设 + 自定义输入同一行；自定义命中时高亮。 */
.limit-control {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

/* 采集方式 / 抓取方式复用内置来源的图标墙，卡片里多一段说明和输入项。 */
.collector-card {
  width: 248px;
}
.collector-card-hint {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-tertiary);
}
.collector-card-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.collector-card-warn {
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--warning);
}

/* 「语音识别」标签旁的建议图标：悬浮查看系统 / 第三方语音输入方式。 */
.asr-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
}
.asr-tip {
  display: inline-flex;
  align-items: center;
  color: var(--text-tertiary);
  cursor: help;
  transition: color 0.16s var(--ease);
}
.asr-tip:hover,
.asr-tip:focus-visible {
  color: var(--text-secondary);
  outline: none;
}

/* 页数额度排成一行小标签，避免每个维度各占一整行。 */
.dim-limits {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.dim-limit {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
  cursor: text;
  transition:
    border-color 0.16s var(--ease),
    background-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.dim-limit:hover {
  border-color: color-mix(in srgb, var(--primary) 32%, var(--border));
  background: var(--panel-bg);
}
.dim-limit:focus-within {
  border-color: color-mix(in srgb, var(--primary) 55%, transparent);
  background: var(--panel-bg);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.1);
}
.dim-limit-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.dim-limit-unit {
  font-size: 12.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.dim-limit-input {
  width: 46px;
}
/* 外层小标签已经有边框，输入框只留数字，避免两层框叠在一起。 */
.dim-limit-input :deep(.n-input),
.dim-limit-input :deep(.n-input:hover),
.dim-limit-input :deep(.n-input.n-input--focus) {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}
.dim-limit-input :deep(.n-input__border),
.dim-limit-input :deep(.n-input__state-border) {
  display: none;
}
.dim-limit-input :deep(.n-input__input-el) {
  padding: 0;
  text-align: right;
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.limit-custom {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 7px 0 9px;
  border: 1px dashed var(--border);
  border-radius: 9px;
  background: var(--surface-soft);
  transition:
    border-color 0.16s var(--ease),
    background-color 0.16s var(--ease);
}
.limit-custom:hover {
  border-color: color-mix(in srgb, var(--primary) 40%, var(--border));
}
.limit-custom.active {
  border-style: solid;
  border-color: color-mix(in srgb, var(--primary) 55%, transparent);
  background: color-mix(in srgb, var(--primary) 8%, var(--panel-bg));
}
.limit-custom-label {
  font-size: 12.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.limit-custom.active .limit-custom-label {
  color: var(--primary);
}
.limit-input {
  width: 52px;
}
/* 自定义小框已经有虚线边框，输入框不再画自己的框。 */
.limit-input :deep(.n-input),
.limit-input :deep(.n-input:hover),
.limit-input :deep(.n-input.n-input--focus) {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}
.limit-input :deep(.n-input__border),
.limit-input :deep(.n-input__state-border) {
  display: none;
}
.limit-input :deep(.n-input__input-el) {
  padding: 0;
  text-align: center;
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
}

/* ---------- 市场洞察动效 ---------- */
.segmented,
.motion-mode {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
}
.segmented button,
.motion-mode button {
  padding: 5px 14px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 13.5px;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.segmented button:hover,
.motion-mode button:hover {
  color: var(--text);
}
.segmented button.active,
.motion-mode button.active {
  background: var(--panel-bg);
  color: var(--primary-hover);
  font-weight: 600;
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.06),
    0 8px 18px -14px rgba(28, 33, 48, 0.4);
}

/* ---------- 信息来源标签库 ---------- */
.source-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
/* ---------- 内置来源：图标墙，悬浮展开配置卡片 ---------- */
.builtin-sources {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.builtin-sources-hint {
  margin-left: 2px;
  font-size: 12.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.builtin-source {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel-bg);
  cursor: pointer;
  transition:
    transform 0.16s var(--ease),
    border-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease),
    background 0.16s var(--ease);
}
.builtin-source:hover {
  transform: translateY(-1px);
  border-color: var(--border-strong);
  box-shadow: 0 6px 14px -10px rgba(28, 33, 48, 0.45);
}
.builtin-source.active {
  border-color: rgba(71, 83, 199, 0.45);
  box-shadow: inset 0 0 0 1px rgba(71, 83, 199, 0.12);
}
.builtin-source.active:hover {
  border-color: var(--primary);
}
.builtin-source-icon {
  display: inline-flex;
  width: 20px;
  height: 20px;
  transition:
    filter 0.16s var(--ease),
    opacity 0.16s var(--ease);
}
.builtin-source-icon :deep(svg) {
  width: 20px;
  height: 20px;
}
/* 聚合图标留白较多，放大一点才和其它品牌图标的视觉重量一致。 */
.builtin-source-icon.aggregate {
  width: 24px;
  height: 24px;
}
.builtin-source-icon.aggregate :deep(svg) {
  width: 24px;
  height: 24px;
}
.builtin-source:not(.active) .builtin-source-icon {
  filter: grayscale(1);
  opacity: 0.42;
}
.builtin-source-dot {
  position: absolute;
  top: 7px;
  right: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: transparent;
  transition: background 0.16s var(--ease);
}
.builtin-source.active .builtin-source-dot {
  background: var(--primary);
}
.builtin-source-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 216px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel-bg);
  box-shadow: var(--shadow-raised);
}
.builtin-source-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.builtin-source-card-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.builtin-source-card-state {
  margin-left: auto;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 12px;
}
.builtin-source-card-state.on {
  background: var(--primary-soft);
  color: var(--primary);
}
.builtin-source-card-setting {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.builtin-source-card-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.builtin-source-select {
  width: 104px;
  flex: none;
}
.builtin-source-card-links {
  display: flex;
  gap: 12px;
  font-size: 12.5px;
}
.builtin-source-card-links a {
  color: var(--text-secondary);
  text-decoration: none;
  transition: color 0.16s var(--ease);
}
.builtin-source-card-links a:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}
.builtin-source-card-toggle {
  height: 28px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-soft);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease),
    border-color 0.16s var(--ease);
}
.builtin-source-card-toggle:not(:disabled):hover {
  border-color: rgba(71, 83, 199, 0.4);
  background: var(--primary-soft);
  color: var(--primary-hover);
}
/* 采集方式 / 抓取方式单项必选，当前项的按钮只作为状态标签。 */
.builtin-source-card-toggle:disabled {
  background: transparent;
  border-color: transparent;
  color: var(--text-tertiary);
  cursor: default;
}
.source-groups {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.source-group {
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-soft);
  overflow: hidden;
}
.source-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 11px;
  border: none;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.source-group-head:hover {
  background: var(--panel-bg);
}
.group-label {
  font-weight: 600;
}
.group-count {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--panel-bg);
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: center;
}
.group-caret {
  margin-left: auto;
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease);
}
.source-group.open .group-caret {
  transform: rotate(180deg);
}
.source-group .source-tags {
  max-height: 216px;
  padding: 2px 10px 10px;
  overflow-y: auto;
}
.source-group .source-tag {
  background: var(--panel-bg);
}
.source-tag {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 5px 7px 5px 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease),
    opacity 0.16s var(--ease);
}
.source-tag.muted {
  opacity: 0.5;
}
.source-tag.editing {
  border-color: var(--primary-soft);
  background: var(--primary-faint);
}
.source-tag.empty {
  padding-right: 11px;
  border-style: dashed;
  color: var(--text-tertiary);
}
.tag-title {
  min-width: 0;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--text);
}
.tag-note {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-tertiary);
}
.tag-note.empty {
  font-style: italic;
  color: #c0392b;
}
.source-tag.empty .tag-title {
  font-weight: 500;
  color: var(--text-tertiary);
}
.tag-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  padding: 2px 5px;
  border: none;
  border-radius: 999px;
  background: transparent;
  font-size: 12px;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.tag-action:hover {
  background: var(--panel-bg);
  color: var(--primary-hover);
}
.tag-action.danger:hover {
  color: #c0392b;
}
.source-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.source-form-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.source-note {
  flex: 1 1 180px;
  min-width: 160px;
}
.source-error {
  margin: 0;
  font-size: 12.5px;
  color: #c0392b;
}
.source-sync {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.source-sync.warn {
  color: #b7791f;
}

.motion-colors {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.motion-color {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 11px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-soft);
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.motion-color:hover {
  border-color: var(--primary-soft);
  background: var(--panel-bg);
}
.motion-color input[type='color'] {
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: none;
  cursor: pointer;
}
.motion-color input[type='color']::-webkit-color-swatch-wrapper {
  padding: 0;
}
.motion-color input[type='color']::-webkit-color-swatch {
  border: none;
  border-radius: 5px;
}
.motion-color input[type='color']::-moz-color-swatch {
  border: none;
  border-radius: 5px;
}

.motion-slider {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 520px;
}
.motion-slider :deep(.n-slider) {
  flex: 1;
  min-width: 0;
}
.motion-slider-value {
  flex: none;
  min-width: 62px;
  text-align: right;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.motion-random {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.motion-palette {
  display: flex;
  gap: 7px;
}
.motion-swatch {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  box-shadow: inset 0 0 0 1px rgba(28, 33, 48, 0.08);
}
.motion-note {
  margin: 0;
  padding: 10px 13px;
  border: 1px dashed var(--primary-soft);
  border-radius: 9px;
  background: var(--primary-faint);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.motion-preview {
  margin: 4px 22px 20px;
  padding: 14px 16px 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-soft);
}
.motion-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-tertiary);
}
.motion-lanes {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.motion-lane {
  position: relative;
  height: 24px;
}
.motion-target {
  position: absolute;
  right: 2px;
  top: 50%;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-strong, #c7ccda);
  transform: translateY(-50%);
}
.motion-flight {
  position: absolute;
  top: 50%;
  left: 0;
  width: var(--lane-tail);
  height: var(--lane-width);
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, var(--lane-color));
  transform: translateY(-50%);
  animation: motion-lane-fly var(--lane-duration) cubic-bezier(0.22, 0.72, 0.3, 1) infinite;
  filter: drop-shadow(0 0 3px color-mix(in srgb, var(--lane-color) 40%, transparent));
}
.motion-flight::after {
  content: '';
  position: absolute;
  right: -5px;
  top: 50%;
  width: 0;
  height: 0;
  border-left: 6px solid var(--lane-color);
  border-top: calc(var(--lane-width) * 0.55) solid transparent;
  border-bottom: calc(var(--lane-width) * 0.55) solid transparent;
  transform: translateY(-50%);
}
@keyframes motion-lane-fly {
  0% {
    left: 0;
    top: calc(50% + var(--lane-bend));
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  88% {
    opacity: 1;
  }
  100% {
    left: calc(100% - var(--lane-tail));
    top: 50%;
    opacity: 0;
  }
}

.backup-folder-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.backup-folder-value {
  flex: 1 1 260px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 560px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-soft);
  font-size: 14px;
  color: var(--text);
}
.backup-folder-value span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.backup-folder-value.empty {
  color: var(--text-tertiary);
}
.backup-folder-value :deep(.icon-glyph) {
  flex: none;
  color: var(--text-tertiary);
}
.backup-status-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.backup-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
}
.backup-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
}
.backup-status.is-ready {
  color: var(--success);
}
.backup-status.is-ready .backup-status-dot {
  background: var(--success);
}
.backup-status.is-warn {
  color: var(--warning);
}
.backup-status.is-warn .backup-status-dot {
  background: var(--warning);
}
.backup-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.backup-warn {
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--warning);
}
.backup-action-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.backup-meta {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.backup-foot-note {
  flex: none;
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.md-layout {
  display: flex;
  height: calc(100vh - 300px);
  min-height: 380px;
  max-height: 760px;
}
.md-list {
  flex: none;
  width: 236px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px;
  overflow: auto;
  background: var(--surface-soft);
  border-right: 1px solid var(--border);
}
.md-group {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 9px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.md-group:first-of-type {
  padding-top: 4px;
}
.md-count {
  font-weight: 500;
  color: var(--text-tertiary);
}
.md-item {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 7px 9px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.md-item:hover {
  background: var(--panel-bg);
}
.md-item.active {
  background: var(--panel-bg);
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.05),
    0 6px 16px -12px rgba(28, 33, 48, 0.28);
}
.md-item-icon {
  flex: none;
  color: var(--text-tertiary);
  transition: color 0.16s var(--ease);
}
.md-item.active .md-item-icon {
  color: var(--primary);
}
.md-item-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text-secondary);
}
.md-item.active .md-item-name {
  color: var(--primary-hover);
  font-weight: 600;
}

.md-viewer {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
}
.md-viewer-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border);
}
.md-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--surface-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--text-secondary);
}
.md-type {
  margin-left: auto;
  flex: none;
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.md-doc {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 28px 40px 56px;
}
.md-doc-inner {
  max-width: 820px;
  margin: 0 auto;
}

.md-doc-inner :deep(h1),
.md-doc-inner :deep(h2),
.md-doc-inner :deep(h3),
.md-doc-inner :deep(h4) {
  color: var(--text);
  line-height: 1.35;
}
.md-doc-inner :deep(h1) {
  margin: 0 0 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.md-doc-inner :deep(h2) {
  margin: 28px 0 10px;
  font-size: 17px;
  font-weight: 600;
}
.md-doc-inner :deep(h3) {
  margin: 22px 0 8px;
  font-size: 15px;
  font-weight: 600;
}
.md-doc-inner :deep(h4) {
  margin: 18px 0 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}
.md-doc-inner :deep(p) {
  margin: 0 0 12px;
  font-size: 14px;
  line-height: 1.85;
  color: var(--text-secondary);
}
.md-doc-inner :deep(ul),
.md-doc-inner :deep(ol) {
  margin: 6px 0 14px;
  padding-left: 1.45em;
}
.md-doc-inner :deep(li) {
  margin: 4px 0;
  line-height: 1.75;
  color: var(--text-secondary);
}
.md-doc-inner :deep(li::marker) {
  color: var(--text-tertiary);
}
.md-doc-inner :deep(strong) {
  font-weight: 600;
  color: var(--text);
}
.md-doc-inner :deep(a) {
  color: var(--primary);
  text-decoration: none;
  border-bottom: 1px solid rgba(71, 83, 199, 0.25);
  transition: border-color 0.16s var(--ease);
}
.md-doc-inner :deep(a:hover) {
  border-bottom-color: var(--primary);
}
.md-doc-inner :deep(code) {
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--surface-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.88em;
  color: var(--primary-hover);
}
.md-doc-inner :deep(pre) {
  margin: 10px 0 16px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
  overflow: auto;
}
.md-doc-inner :deep(pre.hljs) {
  background: var(--surface-soft);
}
.md-doc-inner :deep(pre code) {
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
}
.md-doc-inner :deep(blockquote) {
  margin: 12px 0 16px;
  padding: 10px 14px;
  border-left: 3px solid var(--primary);
  border-radius: 0 8px 8px 0;
  background: var(--primary-faint);
  color: var(--text-secondary);
}
.md-doc-inner :deep(blockquote p:last-child) {
  margin-bottom: 0;
}
.md-doc-inner :deep(table) {
  width: 100%;
  margin: 10px 0 18px;
  border-collapse: collapse;
  font-size: 13px;
}
.md-doc-inner :deep(th),
.md-doc-inner :deep(td) {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.md-doc-inner :deep(th) {
  background: var(--surface-soft);
  font-weight: 600;
  color: var(--text);
}
.md-doc-inner :deep(td) {
  color: var(--text-secondary);
}
.md-doc-inner :deep(hr) {
  margin: 24px 0;
  border: none;
  border-top: 1px solid var(--border);
}
.md-doc-inner :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}

.md-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-tertiary);
}
.md-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
}
.md-empty-text {
  margin: 0;
  font-size: 13.5px;
}

.sk {
  display: block;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--surface-sunken) 25%,
    var(--surface-soft) 37%,
    var(--surface-sunken) 63%
  );
  background-size: 400% 100%;
  animation: sk-shimmer 1.4s ease infinite;
}
.sk-item {
  height: 28px;
  margin-bottom: 6px;
}
.doc-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 780px;
  margin: 0 auto;
}
.sk-title {
  width: 42%;
  height: 24px;
  margin-bottom: 8px;
}
.sk-line {
  width: 100%;
  height: 12px;
}
.sk-line.short {
  width: 64%;
}

@keyframes settings-rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes panel-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes sk-shimmer {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

@media (max-width: 920px) {
  .settings-shell {
    padding: 20px 16px 44px;
  }
  .settings-grid {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .settings-panel {
    width: 100%;
  }
  .settings-nav {
    position: static;
    width: 100%;
    flex-direction: row;
    gap: 4px;
    overflow-x: auto;
  }
  .nav-caption {
    display: none;
  }
  .nav-item {
    flex: 1 0 176px;
    width: auto;
  }
  .field-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }
  .field-info {
    padding-top: 0;
  }
  .md-layout {
    height: calc(100vh - 340px);
    min-height: 360px;
  }
}
@media (max-width: 760px) {
  .md-layout {
    flex-direction: column;
    height: auto;
    max-height: none;
  }
  .md-viewer {
    flex: none;
    height: 62vh;
    min-height: 360px;
  }
  .md-list {
    flex-direction: row;
    align-items: center;
    width: 100%;
    overflow-x: auto;
    padding: 10px 12px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .md-group {
    display: none;
  }
  .md-item {
    flex: none;
    width: auto;
    max-width: 220px;
    padding: 6px 11px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--panel-bg);
  }
  .md-item.active {
    border-color: var(--primary-soft);
    background: var(--primary-soft);
    box-shadow: none;
  }
  .md-doc {
    padding: 20px 20px 40px;
  }
}
</style>
