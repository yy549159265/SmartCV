<script setup lang="ts">
/**
 * 页面 2 · 诊断简历（AI 辅助修改）
 *
 * 布局：
 *  - 左侧：当前简历的只读渲染（连续流，与预览同款组件）；
 *  - 右侧：JD 输入（可选，有 JD 就粘贴，没有就不填）+ AI 对话栏。
 *
 * 对话走 SSE 流式（见 src/api/chat.ts）：诊断"思考"正文 + steps 执行过程 +
 * 摘要"修改说明"气泡；供应商配置在「高级设置」页（localStorage 保存）。
 */
import { nextTick, ref, computed, watch } from 'vue'
import type { InputInst } from 'naive-ui'
import PreviewSection from '@/components/PreviewSection.vue'
import ResumeDiffDialog from '@/components/ResumeDiffDialog.vue'
import AskQuestionCard from '@/components/AskQuestionCard.vue'
import ReferenceExamplePicker from '@/components/ReferenceExamplePicker.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { useResumeStore } from '@/stores/resume'
import { useOptimizeStore, type ChatItem, type ChatStep } from '@/stores/optimize'
import { useStatsStore } from '@/stores/stats'
import type { ChatAnswer, DiagnosisItem, RewriteMode } from '@/api/chat'
import { checkResumeGrammar } from '@/api/grammar'
import { coordToTarget, diffResume } from '@/utils/resumeDiff'

/** 各 agent 生命周期的友好文案：running（进行中）/ done（完成） */
const AGENT_STATUS: Record<string, { running: string; done: string }> = {
  diagnose: { running: '诊断简历中', done: '诊断完成' },
  optimize: { running: '修改简历中', done: '修改完成' },
  summarize: { running: '总结中', done: '总结完成' },
}

/** 诊断档位文案：诊断 agent 对这条结论给出的「修改建议」 */
const DIAG_DISPOSITION_LABEL: Record<string, string> = {
  must: '必须修改',
  suggest: '建议修改',
  keep: '可以保留',
  insufficient: '信息不足',
}

/** 诊断项的审查状态文案：默认「待分析」，优化 agent 审查后更新 */
const DIAG_STATUS_LABEL: Record<string, string> = {
  pending: '待分析',
  change: '待修改',
  skip: '不更改',
  done: '已修改',
  failed: '未执行',
}

/** 诊断结论面板里的状态统计顺序：待修改 → 已修改 → 不更改 → 未执行 → 待分析 */
const DIAG_STATUS_ORDER = ['change', 'done', 'skip', 'failed', 'pending'] as const

/** 按状态统计诊断项，只返回数量非 0 的状态（面板标题右侧的小徽章） */
function diagCounts(items: DiagnosisItem[]) {
  const counts: Record<string, number> = {}
  for (const item of items) {
    const status = item.status ?? 'pending'
    counts[status] = (counts[status] ?? 0) + 1
  }
  return DIAG_STATUS_ORDER.filter((status) => counts[status]).map((status) => ({
    status,
    label: DIAG_STATUS_LABEL[status],
    count: counts[status] as number,
  }))
}

/** 诊断结论占位的文案：正在等用户回答时，不要说「正在生成」 */
function diagPendingText(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const waiting = m.questions.some((q) => q.status === 'pending' || q.status === 'submitting')
  return waiting ? '等待你的回答' : '正在生成诊断结论'
}

/** 诊断卡前置状态：优先用 store 并入的 lead；旧会话（HMR 保留的状态）从紧邻的状态行补 */
function leadText(m: Extract<ChatItem, { kind: 'agent' }>, i: number): string {
  if (m.lead) return m.lead
  const prev = optimizeStore.messages[i - 1]
  return m.agent === 'diagnose' && prev?.kind === 'status' ? prev.text : ''
}

/** 紧跟诊断 agent 的状态行已经在卡片内展示，不再单独占一行 */
function isMergedStatus(i: number): boolean {
  const next = optimizeStore.messages[i + 1]
  return next?.kind === 'agent' && next.agent === 'diagnose'
}

/** 节点详情当前是否展开：有未回答的反问时强制展开，避免把交互藏起来 */
function isNodeBodyOpen(m: Extract<ChatItem, { kind: 'agent' }>): boolean {
  return m.nodeOpen || m.questions.some((q) => q.status === 'pending' || q.status === 'submitting')
}

/** 折叠态是否要展示缩略行：诊断节点的摘要由「诊断结论」入口/占位条承担，不重复 */
function showNodePreview(m: Extract<ChatItem, { kind: 'agent' }>): boolean {
  if (isNodeBodyOpen(m)) return false
  if (m.agent === 'diagnose' && (m.diagnosis.length > 0 || m.status === 'running')) return false
  return true
}

/** 折叠态的缩略内容：一行铺满卡片宽度，超出由 CSS 省略号截断 */
function nodePreview(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const text = (m.text ?? '').replace(/[#>*_`]/g, '').replace(/\s+/g, ' ').trim()
  if (m.agent === 'diagnose' && m.diagnosis.length) {
    return diagCounts(m.diagnosis)
      .map((c) => `${c.label} ${c.count}`)
      .join(' · ')
  }
  if (m.agent === 'optimize') {
    const parts: string[] = []
    if (m.status === 'done') parts.push(`确认修改 ${doneCount()} 处`)
    if (text) parts.push(text)
    return parts.join(' · ') || '正在逐条审查诊断…'
  }
  return text || statusText(m)
}

/** 当前节点是不是这一轮流程的最后一个：往后到下一个用户消息之间没有别的 agent 节点 */
function isLastFlowNode(i: number): boolean {
  for (let j = i + 1; j < optimizeStore.messages.length; j++) {
    const next = optimizeStore.messages[j]
    if (next.kind === 'user') break
    if (next.kind === 'agent') return false
  }
  return true
}

/** 已成功修改的诊断条数（优化 agent 完成时展示） */
function doneCount(): number {
  for (let i = optimizeStore.messages.length - 1; i >= 0; i--) {
    const m = optimizeStore.messages[i]
    if (m.kind === 'agent' && m.agent === 'diagnose' && m.diagnosis.length) {
      return m.diagnosis.filter((d) => d.status === 'done').length
    }
  }
  return 0
}

/** 诊断结论弹窗：保存当前查看的诊断块（引用，状态更新会实时反映到弹窗） */
const diagShow = ref(false)
const diagDetail = ref<Extract<ChatItem, { kind: 'agent' }> | null>(null)
/** 诊断列表滚动容器（对比弹窗「查看诊断」跳转定位用） */
const diagListEl = ref<HTMLElement | null>(null)

function openDiagDetail(m: Extract<ChatItem, { kind: 'agent' }>) {
  diagDetail.value = m
  diagShow.value = true
}

/** 找最近一个带诊断列表的 diagnose 块（与 store 内部 diagnosisOwner 同语义） */
function diagOwner(): Extract<ChatItem, { kind: 'agent' }> | null {
  for (let i = optimizeStore.messages.length - 1; i >= 0; i--) {
    const m = optimizeStore.messages[i]
    if (m.kind === 'agent' && m.agent === 'diagnose' && m.diagnosis.length) return m
  }
  return null
}

/** 诊断项按章节分组的树结构：章节标题 + 章内诊断项（保留全局序号用于跳转定位） */
interface DiagGroup {
  section: string
  sectionIndex: number
  items: { di: number; d: DiagnosisItem }[]
}

const groupedDiag = computed<DiagGroup[]>(() => {
  const detail = diagDetail.value
  if (!detail) return []
  const groups = new Map<string, DiagGroup>()
  const order: string[] = []
  detail.diagnosis.forEach((d, di) => {
    const section = d.section ?? '简历'
    const sectionIndex = d.sectionIndex ?? -1
    const key = `${sectionIndex}\u0000${section}`
    let g = groups.get(key)
    if (!g) {
      g = { section, sectionIndex, items: [] }
      groups.set(key, g)
      order.push(key)
    }
    g.items.push({ di, d })
  })
  // 按简历章节顺序（sectionIndex）排序
  order.sort((a, b) => {
    const ga = groups.get(a)!
    const gb = groups.get(b)!
    return ga.sectionIndex !== gb.sectionIndex ? ga.sectionIndex - gb.sectionIndex : a.localeCompare(b)
  })
  return order.map((k) => groups.get(k)!)
})

/** 折叠的章节 key（`sectionIndex\0section`），默认全展开 */
const collapsedGroups = ref<Set<string>>(new Set())

function diagGroupKey(group: DiagGroup): string {
  return `${group.sectionIndex}\u0000${group.section}`
}

function toggleGroup(key: string) {
  const next = new Set(collapsedGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedGroups.value = next
}

/** 当前正在闪烁定位的诊断卡片序号（对比弹窗跳过来时标红闪一下，方便确认看的是哪一条） */
const diagFlashIndex = ref<number | null>(null)

function flashDiagCard(index: number) {
  // 先清掉再设置，保证同一张卡片连点也能重新触发闪烁
  diagFlashIndex.value = null
  void nextTick(() => {
    diagFlashIndex.value = index
    window.setTimeout(() => {
      if (diagFlashIndex.value === index) diagFlashIndex.value = null
    }, 2200)
  })
}

/** 对比弹窗里点某处「查看诊断」：打开诊断结论弹窗（叠加在对比弹窗之上）并闪烁定位对应卡片 */
function onJumpToDiagnosis(index: number) {
  const owner = diagOwner()
  if (!owner) return
  openDiagDetail(owner)
  flashDiagCard(index)
  // 弹窗用 display-directive="if" 挂载，可能晚于一次 nextTick；逐帧重试直到卡片出现
  const scrollTo = (attempt: number) => {
    const el = diagListEl.value?.querySelector(`[data-diag-index="${index}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    if (attempt < 12) requestAnimationFrame(() => scrollTo(attempt + 1))
  }
  void nextTick(() => scrollTo(0))
}

/** 对比弹窗关联的诊断项：只有聊天修改有诊断，全文纠错没有 */
const latestDiagnosis = computed<DiagnosisItem[]>(() => {
  if (optimizeStore.pendingDiff?.source !== 'chat') return []
  return diagOwner()?.diagnosis ?? []
})

/** 诊断序号 → 对比弹窗里的改动 key（反向映射，诊断页「查看对比」跳转用） */
const diffKeyByDiagIndex = computed<ReadonlyMap<number, string>>(() => {
  const map = new Map<number, string>()
  const pending = optimizeStore.pendingDiff
  if (!pending) return map
  const keys = new Set(diffResume(pending.before, pending.after).changes.map((c) => c.key))
  latestDiagnosis.value.forEach((d, idx) => {
    if (d.s == null || d.r == null || d.c == null || d.i == null) return
    const target = coordToTarget(pending.before, d.s, d.r, d.c, d.i)
    if (!target) return
    const unitKey = `unit:${target.contentId}:${target.unitIndex}`
    if (keys.has(unitKey)) {
      map.set(idx, unitKey)
      return
    }
    const contentKey = `content:${target.contentId}`
    if (keys.has(contentKey)) map.set(idx, contentKey)
  })
  return map
})

/** 诊断页「查看对比」的闪烁目标：{ key, nonce }，nonce 保证同一处连点也重新触发 */
const diffFlash = ref<{ key: string; nonce: number } | null>(null)

/** 诊断结论弹窗里点「查看对比」：关闭诊断弹窗、回到对比弹窗并闪烁对应改动 */
function onJumpToDiff(index: number) {
  const key = diffKeyByDiagIndex.value.get(index)
  if (!key) return
  diagShow.value = false
  optimizeStore.diffOpen = true
  diffFlash.value = { key, nonce: Date.now() }
}

/** 取出 agent 块当前应该显示的状态文案 */
function statusText(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const map = AGENT_STATUS[m.agent]
  if (!map) return m.label
  if (m.agent === 'diagnose' && m.status === 'done') {
    // 诊断完成后直接带出问题条数；哪些要改由上方「诊断结论」的状态统计展示
    return m.diagnosis.length
      ? `${map.done} · 发现 ${m.diagnosis.length} 处问题`
      : `${map.done} · 未发现问题`
  }
  if (m.agent === 'optimize' && m.status === 'done') {
    // 条数来自逐条诊断的执行状态，和诊断结论弹窗里的「已修改」一致
    return `${map.done} · 确认修改 ${doneCount()} 处`
  }
  return m.status === 'done' ? map.done : map.running
}

/** 执行过程的展示行：把 tool_call + tool_result 合并成一条（agent 生命周期走状态头，不在此列） */
interface DisplayStep {
  kind: 'tool'
  tool: string
  args: string
  result?: string
}

/** 把扁平的 steps[] 整理成易读的行：同一工具的 tool_call + tool_result 合并 */
function groupSteps(steps: ChatStep[]): DisplayStep[] {
  const rows: DisplayStep[] = []
  let i = 0
  while (i < steps.length) {
    const st = steps[i]
    if (st.kind === 'tool_call') {
      const next = steps[i + 1]
      if (next?.kind === 'tool_result' && next.tool === st.tool) {
        rows.push({ kind: 'tool', tool: st.tool, args: st.args, result: next.result })
        i += 2
      } else {
        rows.push({ kind: 'tool', tool: st.tool, args: st.args })
        i++
      }
    } else if (st.kind === 'tool_result') {
      // 落单的 tool_result（没有配对的调用）
      rows.push({ kind: 'tool', tool: st.tool, args: '', result: st.result })
      i++
    } else {
      i++
    }
  }
  return rows
}

/** 工具调用展示行：web_search 在「Web 搜索」区单独展示，这里跳过避免重复 */
function toolRows(steps: ChatStep[]): DisplayStep[] {
  return groupSteps(steps).filter((row) => row.tool !== 'web_search')
}
import { usePagination } from '@/composables/usePagination'
import { previewZoom, ZOOM_LEVELS } from '@/composables/usePreviewZoom'
import { contentWidth, pageHeight, pageWidth } from '@/composables/usePageSize'
import { PAGE_PADDING } from '@/utils/constants'
import { pageRunSpecs, type PageUnit, type RunSpec } from '@/utils/pagination'
import { fetchResumePdf } from '@/api/pdf'
import { resumeFilename } from '@/composables/useResumeName'
import { polishTexts } from '@/api/polish'
import type { Section } from '@/types'
import { downloadBlob, downloadJson } from '@/utils/download'
import { useDocumentsStore } from '@/stores/documents'
import { renderMarkdown } from '@/utils/markdown'
import { dialog, message } from '@/utils/feedback'
import { getAgentSessionId, resetAgentSessionId } from '@/api/session'

/**
 * 示例库是独立页面：选择器为空时给一个「去上传示例」的跳转入口；
 * convert-to-example 把当前简历 JSON 一起带过去，直接填进示例库的上传表单。
 */
const emit = defineEmits<{
  'open-library': []
  'convert-to-example': [json: string]
}>()

const resumeStore = useResumeStore()
const optimizeStore = useOptimizeStore()
const statsStore = useStatsStore()
const documents = useDocumentsStore()

/* ---------- 隐藏测量层：和预览同款，算出与预览一致的分页方案 ---------- */
const measureFlowEl = ref<HTMLElement | null>(null)
usePagination(measureFlowEl)

/** 按分页方案把内容分到各页（每页 = 一组"连续同章节片段"RunSpec）—— 导出的每页块据此渲染，页数才和预览一致 */
const pages = computed(() =>
  resumeStore.pagePlan.pages.map((page) =>
    pageRunSpecs(
      page.unitIds
        .map((id) => resumeStore.unitById(id))
        .filter((u): u is PageUnit => u !== undefined),
    )
      .map((spec) => ({ spec, section: resumeStore.sectionById(spec.sectionId) }))
      .filter((x): x is { spec: RunSpec; section: Section } => x.section !== undefined),
  ),
)

/**
 * 分页纸张样式：和「实时预览」的纸张保持完全一致 ——
 * 同样的纸宽 / 最小高 / 页边距 / 缩放，这样两边显示的字号、换行、分页完全一样，
 * 不会出现"诊断简历页看起来更大/不分页"的问题。
 */
const pageStyle = computed(() => ({
  width: `${pageWidth.value}px`,
  minHeight: `${pageHeight.value}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: previewZoom.value,
}))

/** 隐藏测量层宽度：与纸面内容区等宽（随纸面宽度一起变） */
const measureStyle = computed(() => ({ width: `${contentWidth.value}px` }))

/** 导出流宽度：与纸面同宽（PDF 的 @page size 也读同一个值，导出页与预览页一致） */
const exportStyle = computed(() => ({ width: `${pageWidth.value}px` }))

/* ---------- 导出 ---------- */

/** JSON 处理菜单是否展开（导出 JSON / 转换成优秀示例） */
const jsonMenuShow = ref(false)

/** 导出 JSON 到备份文件夹：写回当前文件；没有文件夹 / 没权限时降级为浏览器下载 */
async function onExportJsonToFolder() {
  jsonMenuShow.value = false
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  const result = await documents.exportJson()
  if (result === 'saved') {
    await statsStore.inc('json')
    message.success(
      documents.currentFile
        ? `已保存到备份文件夹：${documents.currentFile}`
        : '已保存到备份文件夹',
    )
    return
  }
  // 用户主动取消（覆盖确认 / 命名）时什么都不做
  if (result === 'cancelled') return
  // 没绑定文件夹或没有权限：给一份浏览器下载兜底
  downloadJson(resumeStore.resume, `${resumeFilename()}.json`)
  await statsStore.inc('json')
}

/** 下载 JSON 到电脑（不需要备份文件夹） */
function onDownloadJson() {
  jsonMenuShow.value = false
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  downloadJson(resumeStore.resume, `${resumeFilename()}.json`)
  void statsStore.inc('json')
}

/** 转换成优秀示例：带上当前简历 JSON 跳到示例库，上传表单自动填入粘贴框 */
function onConvertToExample() {
  jsonMenuShow.value = false
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  emit('convert-to-example', JSON.stringify(resumeStore.resume, null, 2))
}

/** 是否正在导出 PDF（按钮转圈，防止重复点击） */
const exporting = ref(false)

/** 导出用的隐藏简历流：按分页方案渲染成"每页一块"，不带缩放，保证 100% 输出 */
const exportFlowEl = ref<HTMLElement | null>(null)

/**
 * 导出 PDF：把整份简历的"连续流"序列化成 HTML 发给后端，
 * 后端用无头 Chromium 打 PDF（文字版、与预览排版一致），返回 .pdf 文件直接下载。
 */
async function onExportPdf() {
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  // 在点击手势里先恢复文件夹权限：生成 PDF 要等网络，之后再申请权限可能已失去用户激活
  if (documents.isBound) await documents.ensurePermission()
  exporting.value = true
  try {
    // 等导出容器渲染完再序列化
    await nextTick()
    await new Promise((r) => setTimeout(r, 350))

    if (!exportFlowEl.value) throw new Error('没有可导出的内容')

    // 防呆：分页方案没算出来时导出容器是空的，会生成空白 PDF —— 直接报错，别把空文件发出去
    if (exportFlowEl.value.querySelector('.export-page') == null) {
      throw new Error('简历排版还没准备好，请稍后重试')
    }

    const blob = await fetchResumePdf(exportFlowEl.value)
    const filename = resumeFilename()
    // 绑定了备份文件夹就写进文件夹，否则（或写入失败）走浏览器下载
    const saved = await documents.savePdf(blob, filename)
    if (!saved) downloadBlob(blob, `${filename}.pdf`)
    await statsStore.inc('pdf')
    message.success(
      saved ? 'PDF 已保存到备份文件夹' : 'PDF 已导出（后端生成，与预览一致）',
    )
  } catch (err) {
    console.error(err)
    message.error(`导出失败：${err instanceof Error ? err.message : String(err)}`)
  } finally {
    exporting.value = false
  }
}

/** JD 输入区是否展开（可选功能：没有 JD 就不展开） */
const jdExpanded = ref(false)

/** 输入框内容 */
const draft = ref('')
/** 输入框实例（增强后把光标放回末尾，方便继续编辑或发送） */
const chatInputRef = ref<InputInst | null>(null)
/** 对话列表容器（用于自动滚到底部） */
const chatListEl = ref<HTMLElement | null>(null)
/** 输入区设置菜单（提示词增强 / 全文纠错 / 优化强度） */
const settingsShow = ref(false)
/** 全文纠错请求进行中：禁止同时发送聊天，避免两个结果抢同一份 pendingDiff */
const grammarRunning = ref(false)

async function onSend() {
  if (!draft.value.trim()) return
  if (grammarRunning.value) {
    message.warning('全文纠错进行中，请稍候')
    return
  }
  const text = draft.value
  draft.value = ''
  await optimizeStore.send(text)
  // 新消息上屏后滚到底部
  await nextTick()
  chatListEl.value?.scrollTo({ top: chatListEl.value.scrollHeight, behavior: 'smooth' })
}

/** 诊断 agent 反问：提交答案（空数组 = 跳过） */
function onSubmitQuestion(questionId: string, answers: ChatAnswer[]) {
  void optimizeStore.submitQuestionAnswers(questionId, answers)
}

// 反问卡片出现时自动滚到底部，别让用户错过等待回答的问题
watch(
  () =>
    optimizeStore.messages.some(
      (m) =>
        m.kind === 'agent' &&
        m.questions.some((q) => q.status === 'pending' || q.status === 'submitting'),
    ),
  async (pending) => {
    if (!pending) return
    await nextTick()
    chatListEl.value?.scrollTo({ top: chatListEl.value.scrollHeight, behavior: 'smooth' })
  },
)

/* ---------- 提示词增强 ---------- */

/** 是否正在请求增强（按钮转圈，避免重复点击） */
const enhancing = ref(false)
/** 增强前 / 增强后对比弹窗 */
const enhanceShow = ref(false)
const enhanceBefore = ref('')
const enhanceAfter = ref('')
/** 增强后的文本可直接编辑，弹窗打开后聚焦到这里 */
const enhanceEditorEl = ref<HTMLTextAreaElement | null>(null)

/**
 * 把输入框里的口语化要求发给后端改写成更明确、可执行的提示词。
 * 复用 /api/polish（mode='enhance'），已填的 JD 作为参考材料一起传。
 * 不直接覆盖输入框：先弹窗对比，用户点「确定」才写回。
 */
async function onEnhancePrompt() {
  const text = draft.value.trim()
  if (enhancing.value || optimizeStore.sending || grammarRunning.value) return
  if (!text) {
    message.warning('先输入修改要求再增强')
    return
  }
  settingsShow.value = false

  enhancing.value = true
  try {
    const [enhanced] = await polishTexts([text], '', 'enhance', optimizeStore.jd)
    const result = (enhanced ?? '').trim()
    if (!result) throw new Error('增强结果为空，请稍后重试')
    enhanceBefore.value = text
    enhanceAfter.value = result
    enhanceShow.value = true
    // 弹窗打开后直接聚焦增强结果，光标放到末尾，方便用户接着改
    await nextTick()
    const editor = enhanceEditorEl.value
    if (editor) {
      editor.focus()
      editor.setSelectionRange(editor.value.length, editor.value.length)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '提示词增强失败')
  } finally {
    enhancing.value = false
  }
}

/** 确认采用（可能被用户改过的）增强结果：写回输入框，光标移到末尾 */
function onApplyEnhance() {
  const result = enhanceAfter.value.trim()
  if (!result) {
    message.warning('增强结果不能为空')
    return
  }
  draft.value = result
  enhanceShow.value = false
  nextTick(() => chatInputRef.value?.focus())
}

/* ---------- 全文纠错 ---------- */

/** 已有待确认修改时，问用户是否放弃它再继续；取消则什么都不做 */
function confirmDiscardPendingDiff(): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (value: boolean) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    dialog.warning({
      title: '还有一份修改没有确认',
      content: '重新检查会放弃上一次的修改结果（简历本身不会变）。要继续吗？',
      positiveText: '放弃并继续',
      negativeText: '先处理这份修改',
      onPositiveClick: () => {
        optimizeStore.discardPendingDiff()
        finish(true)
      },
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

/** 切换优化强度后收起菜单，下一次发送生效 */
function onSetRewriteMode(mode: RewriteMode) {
  optimizeStore.setRewriteMode(mode)
  settingsShow.value = false
}

/**
 * 全文纠错：把整份简历发给后端，模型返回坐标 + 完整改后文字，后端校验后
 * 返回改好的简历。这里不直接写回，而是塞进 pendingDiff，复用「修改对比」弹窗
 * 让用户逐处确认；点「确定应用」才走 importResume（一步 Ctrl+Z 可撤销）。
 *
 * 已有一份待确认的修改时不再直接拦下，而是先问要不要放弃它再重新检查：
 * 之前的实现直接 return，用户又没有别的出口，按钮会一直卡在禁用状态。
 */
async function onGrammarCheck() {
  settingsShow.value = false
  if (grammarRunning.value || optimizeStore.sending) return
  if (!resumeStore.resume.length) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  if (optimizeStore.pendingDiff) {
    if (!(await confirmDiscardPendingDiff())) return
  }

  // 改前快照：和聊天修改一样深拷贝，避免请求期间简历变化导致 diff 失真
  const before = JSON.parse(JSON.stringify(resumeStore.resume)) as Section[]
  grammarRunning.value = true
  try {
    const result = await checkResumeGrammar(before)

    // 请求期间简历被改过（撤销 / 其它入口）时放弃本次结果，防止用旧快照覆盖新内容
    if (JSON.stringify(resumeStore.resume) !== JSON.stringify(before)) {
      message.warning('检查期间简历发生了变化，请重新检查')
      return
    }

    if (!result.stats.fixed) {
      message.info(
        result.stats.skipped
          ? `未发现可应用的错误，${result.stats.skipped} 处建议未通过校验`
          : '未发现语法或拼写问题',
      )
      return
    }

    optimizeStore.setPendingDiff(before, result.resume, 'grammar')
    if (result.stats.skipped) {
      message.info(
        `已修正 ${result.stats.fixed} 处；另有 ${result.stats.skipped} 处建议未通过校验`,
      )
    } else {
      message.success(`已修正 ${result.stats.fixed} 处，请确认后应用`)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '全文纠错失败')
  } finally {
    grammarRunning.value = false
  }
}

/** 当前会话 id（展示用；「新建会话」重置后同步更新） */
const sessionId = ref(getAgentSessionId())
const shortSessionId = computed(() => sessionId.value.slice(0, 8))

/** 清空对话 + 新建一个会话 id：诊断 / 优化 / 摘要等 agent 共用，后端按它隔离会话 */
function onNewConversation() {
  optimizeStore.clearMessages()
  sessionId.value = resetAgentSessionId()
  message.success('已清空会话，并新建会话 id')
}

/* ---------- AI 修改对比 ---------- */

/** 对比弹窗标题：全文纠错和聊天修改共用同一个弹窗 */
const diffTitle = computed(() =>
  optimizeStore.pendingDiff?.source === 'grammar' ? '全文纠错对比' : 'AI 修改对比',
)

/**
 * 应用对比弹窗里的修改：这时候才真正把（逐处筛选过的）结果写回 store。
 * importResume 会重生成 id 并整体替换，同时被 main.ts 的 $onAction 记一次撤销快照，
 * 所以提示里告诉用户可以 Ctrl+Z 撤回。
 * 全部还原时 store 不会写回，提示也换成"简历未改动"。
 */
function onApplyDiff() {
  const source = optimizeStore.pendingDiff?.source
  const applied = optimizeStore.applyPendingDiff()
  if (applied) {
    message.success(
      source === 'grammar'
        ? '已应用纠错修改，可用 Ctrl+Z 撤销'
        : '已应用 AI 修改，可用 Ctrl+Z 撤销',
    )
  } else {
    message.info('所有改动都已还原，简历保持不变')
  }
}

/** 放弃本次修改：简历不动，清掉待确认状态，之后可以重新纠错 / 对话 */
function onDiscardDiff() {
  optimizeStore.discardPendingDiff()
  message.info('已放弃本次修改，简历保持不变')
}
</script>

<template>
  <!-- 隐藏测量层：始终挂载，连续渲染全部章节用于算分页（与预览同宽，页数才能一致） -->
  <div ref="measureFlowEl" class="measure-flow" :style="measureStyle">
    <PreviewSection
      v-for="g in resumeStore.resume"
      :key="g.id"
      :section="g"
      :data-section-id="g.id"
      :data-forced="g.pageBreakBefore ? 'true' : undefined"
    />
  </div>

  <!-- 隐藏导出流：导出 PDF 时按预览的分页方案渲染成"每页一块"，
       每块用 break-after 强制独占一页，导出的页数 = 预览页数 -->
  <div v-if="exporting" class="export-pages">
    <div ref="exportFlowEl" class="export-flow" :style="exportStyle">
      <div
        v-for="(page, i) in pages"
        :key="i"
        class="export-page"
        :style="{
          height: `${pageHeight}px`,
          padding: `${PAGE_PADDING}px`,
          breakAfter: i === pages.length - 1 ? 'auto' : 'page',
        }"
      >
        <template v-for="(x, fi) in page" :key="`${x.spec.sectionId}:${x.spec.rowFrom}:${x.spec.rowTo}`">
          <PreviewSection
            :section="x.section!"
            :row-from="x.spec.rowFrom"
            :row-to="x.spec.rowTo"
            :show-title="x.spec.hasTitle"
            :top-pad="x.spec.topPad"
            :bottom-pad="x.spec.bottomPad"
            :space-before="x.spec.spaceBefore"
          />
        </template>
      </div>
    </div>
  </div>

  <main class="optimize-page">
    <!-- 左：当前简历只读渲染 -->
    <section class="resume-panel">
      <div class="panel-header">
        <span class="panel-title">当前简历</span>
        <span class="panel-hint">共 {{ resumeStore.resume.length }} 个章节 · {{ pages.length }} 页 · 只读</span>
        <span class="panel-spacer" />
        <!-- 缩放与实时预览共用：两边看到的字号永远一致 -->
        <n-button-group size="tiny">
          <n-button
            v-for="z in ZOOM_LEVELS"
            :key="z"
            :type="previewZoom === z ? 'primary' : 'default'"
            ghost
            @click="previewZoom = z"
          >
            {{ Math.round(z * 100) }}%
          </n-button>
        </n-button-group>
        <!-- JSON 处理：导出 JSON 文件 / 转换成优秀示例；PDF（文字版，浏览器打印 → 另存为 PDF） -->
        <n-popover v-model:show="jsonMenuShow" trigger="click" placement="bottom-end" :width="256">
          <template #trigger>
            <n-button size="small" quaternary class="json-menu-btn" :aria-expanded="jsonMenuShow">
              JSON 处理
              <IconGlyph name="chevron-down" :size="12" />
            </n-button>
          </template>
          <div class="composer-menu" role="menu" aria-label="JSON 处理">
            <button
              v-if="documents.isBound"
              type="button"
              role="menuitem"
              class="composer-menu-item"
              @click="onExportJsonToFolder"
            >
              <span class="menu-icon" aria-hidden="true">
                <IconGlyph name="folder-down" :size="16" />
              </span>
              <span class="menu-text">
                <span class="menu-title">保存到备份文件夹</span>
                <span class="menu-desc">写回当前简历的 JSON 文件</span>
              </span>
            </button>
            <button type="button" role="menuitem" class="composer-menu-item" @click="onDownloadJson">
              <span class="menu-icon" aria-hidden="true">
                <IconGlyph name="download" :size="16" />
              </span>
              <span class="menu-text">
                <span class="menu-title">下载到电脑</span>
                <span class="menu-desc">
                  {{ documents.isBound ? '另存一份 JSON 到下载目录' : '下载当前简历数据文件' }}
                </span>
              </span>
            </button>
            <div class="composer-menu-divider" />
            <button type="button" role="menuitem" class="composer-menu-item" @click="onConvertToExample">
              <span class="menu-icon" aria-hidden="true">
                <IconGlyph name="file-up" :size="16" />
              </span>
              <span class="menu-text">
                <span class="menu-title">转换成优秀示例</span>
                <span class="menu-desc">跳到示例库上传，当前简历 JSON 自动填入</span>
              </span>
            </button>
          </div>
        </n-popover>
        <n-button size="small" type="primary" ghost :loading="exporting" @click="onExportPdf">
          {{ exporting ? '导出中…' : '导出 PDF' }}
        </n-button>
      </div>
      <div class="resume-scroll">
        <!-- 与「实时预览」同款：按分页方案渲染成一张张 A4 纸（带页码），格式一致 -->
        <div class="page-stack">
          <div v-for="(page, i) in pages" :key="i" class="page-slot">
            <div class="a4-page" :style="pageStyle">
              <template v-for="(x, fi) in page" :key="`${x.spec.sectionId}:${x.spec.rowFrom}:${x.spec.rowTo}`">
                <PreviewSection
                  :section="x.section!"
                  :row-from="x.spec.rowFrom"
                  :row-to="x.spec.rowTo"
                  :show-title="x.spec.hasTitle"
                  :top-pad="x.spec.topPad"
                  :bottom-pad="x.spec.bottomPad"
                  :space-before="x.spec.spaceBefore"
                />
              </template>
              <span class="page-number">{{ i + 1 }} / {{ pages.length }}</span>
            </div>
          </div>
          <div v-if="resumeStore.resume.length === 0" class="resume-empty">
            暂无简历内容，请先去「编辑简历」页添加
          </div>
        </div>
      </div>
    </section>

    <!-- 右：JD（可选） + AI 对话 -->
    <section class="chat-panel">
      <!-- JD 输入区：可选折叠 -->
      <div class="jd-section">
        <button class="jd-toggle" :class="{ open: jdExpanded }" @click="jdExpanded = !jdExpanded">
          <span class="jd-caret" aria-hidden="true"></span>
          <span class="jd-toggle-text">JD 职位描述（可选，有就粘贴）</span>
        </button>
        <div v-if="jdExpanded" class="jd-body">
          <n-input
            :value="optimizeStore.jd"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 10 }"
            placeholder="把招聘 JD 粘贴到这里，AI 会参考它来提修改建议。没有 JD 可以不填。"
            @update:value="(v: string) => optimizeStore.setJd(v)"
          />
        </div>
      </div>

      <!-- 优秀示例选择器：诊断时参考他人简历的写作方式与结构，最多 3 份 -->
      <ReferenceExamplePicker
        :selected="optimizeStore.referenceIds"
        @update:selected="optimizeStore.setReferenceIds"
        @open-library="emit('open-library')"
      />

      <!-- 对话栏 -->
      <div class="chat-header">
        <span class="chat-heading">
          <span class="chat-heading-icon" aria-hidden="true">✦</span>
          <span class="panel-title">简历修改对话</span>
        </span>
        <span class="panel-spacer" />
        <!-- 右侧操作整组对齐；窄面板放不下时整组换行并靠右，不会被裁掉 -->
        <div class="chat-actions">
          <!-- 大胆模式常显一个轻量标签；点它重新打开设置菜单 -->
          <button
            v-if="optimizeStore.rewriteMode === 'bold'"
            class="rewrite-mode-chip"
            title="当前为大胆优化，点此切换"
            @click="settingsShow = true"
          >
            大胆优化
          </button>
          <!-- 对比弹窗关掉后简历仍是旧的，这里留个入口，想好了再点开应用 -->
          <n-button
            v-if="optimizeStore.pendingDiff"
            size="tiny"
            type="primary"
            ghost
            @click="optimizeStore.openDiff()"
          >
            查看修改对比
          </n-button>
          <span
            class="session-id"
            :title="`会话 id：${sessionId}（诊断 / 优化 / 摘要等 agent 共用）`"
          >
            会话 {{ shortSessionId }}
          </span>
          <n-button
            size="tiny"
            quaternary
            :disabled="optimizeStore.sending"
            @click="onNewConversation"
          >
            新建会话
          </n-button>
        </div>
      </div>

      <div ref="chatListEl" class="chat-list">
        <!-- 空状态 -->
        <div v-if="optimizeStore.messages.length === 0" class="chat-empty">
          <span class="chat-empty-icon" aria-hidden="true">✦</span>
          <p class="chat-empty-title">描述你想怎么改这份简历，例如：</p>
          <div class="chat-empty-examples">
            <span>「把工作经历写得更量化一点」</span>
            <span>「帮我把自我评价改得简洁有力」</span>
          </div>
        </div>

        <!-- 时间线：用户消息 / 过程 agent 块 / 摘要回答气泡 -->
        <div
          v-for="(m, i) in optimizeStore.messages"
          :key="i"
          class="chat-msg"
          :class="{ 'from-user': m.kind === 'user' }"
        >
          <!-- 用户消息：右侧气泡 -->
          <div v-if="m.kind === 'user'" class="msg-block from-user">
            <div class="bubble">{{ m.text }}</div>
          </div>

          <!-- 错误：左侧提示气泡 -->
          <div v-else-if="m.kind === 'error'" class="msg-block from-ai">
            <div class="bubble error">{{ m.text }}</div>
          </div>

          <!-- 阶段状态：convert 等非 agent 阶段（正在解析 → 已完成） -->
          <div
            v-else-if="m.kind === 'status'"
            v-show="!isMergedStatus(i)"
            class="msg-block from-process"
          >
            <div class="status-line" :class="{ done: m.done }">
              <span class="status-mark">
                <span v-if="m.done" class="check"><IconGlyph name="check" :size="12" /></span>
                <span v-else class="pulse"></span>
              </span>
              <span class="status-line-text">{{ m.text }}</span>
            </div>
          </div>

          <!-- agent 块：流程节点（诊断 → 优化 → 总结）。节点之间用带箭头的竖线相连；
               点节点头折叠/展开：折叠显示一行缩略内容，展开显示该节点的工作详情 -->
          <div v-else class="msg-block from-process">
            <div class="flow-node" :class="[m.status, { 'is-last': isLastFlowNode(i) }]">
              <!-- 左侧轨道：节点标记 + 指向下一个节点的竖线与箭头 -->
              <div class="flow-rail" aria-hidden="true">
                <span class="flow-marker">
                  <span v-if="m.status === 'done'" class="check"><IconGlyph name="check" :size="11" /></span>
                  <span v-else class="pulse"></span>
                </span>
                <span class="flow-line"></span>
                <span class="flow-arrow"></span>
              </div>

              <div class="flow-card">
                <!-- 节点头：标题 + 状态摘要，整行可点 -->
                <button
                  type="button"
                  class="flow-head"
                  :aria-expanded="isNodeBodyOpen(m)"
                  @click="m.nodeOpen = !m.nodeOpen"
                >
                  <span class="flow-title">{{ m.label || m.agent }}</span>
                  <span class="flow-status" :class="m.status">{{ statusText(m) }}</span>
                  <span class="flow-caret" :class="{ open: isNodeBodyOpen(m) }">
                    <IconGlyph name="chevron-down" :size="14" />
                  </span>
                </button>

                <!-- 诊断结论占位：思考/工具阶段先占住结论的位置并持续扫光，
                     避免用户以为没在诊断；结论一到就换成下方可点的「诊断结论」入口 -->
                <div
                  v-if="m.agent === 'diagnose' && m.status === 'running' && !m.diagnosis.length"
                  class="diag-pending"
                >
                  <span class="diag-pending-icon" aria-hidden="true"><IconGlyph name="scan-line" :size="12" /></span>
                  <span class="diag-pending-text">{{ diagPendingText(m) }}</span>
                  <span class="diag-pending-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                </div>

                <!-- 诊断结论入口：结论是产出，不随节点详情折叠 -->
                <button
                  v-if="m.diagnosis.length"
                  type="button"
                  class="diag-entry"
                  @click="openDiagDetail(m)"
                >
                  <span class="diag-entry-icon" aria-hidden="true"><IconGlyph name="scan-line" :size="12" /></span>
                  <span class="diag-entry-main">
                    <span class="diag-entry-title">诊断结论</span>
                    <span class="diag-report-count">{{ m.diagnosis.length }} 处</span>
                  </span>
                  <span class="diag-entry-chips">
                    <span
                      v-for="c in diagCounts(m.diagnosis)"
                      :key="c.status"
                      class="diag-chip"
                      :class="c.status"
                    >
                      {{ c.label }} {{ c.count }}
                    </span>
                  </span>
                  <span class="diag-entry-action">查看详情 <IconGlyph name="arrow-right" :size="12" /></span>
                </button>

                <!-- 折叠态：一句话说清这个节点做了什么 -->
                <div v-if="showNodePreview(m)" class="flow-preview">
                  <span>{{ nodePreview(m) }}</span>
                </div>

                <!-- 展开态：该节点的工作详情 -->
                <div v-if="isNodeBodyOpen(m)" class="agent-body">
                  <!-- convert 阶段结束状态：并入诊断节点，作为详情的第一行 -->
                  <div v-if="leadText(m, i)" class="agent-lead">{{ leadText(m, i) }}</div>
                <!-- 🧭 位置诊断：诊断 agent 实际收到的带位置编号的简历文本 -->
                <div v-if="m.markdown" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.markdownOpen = !m.markdownOpen">
                    <span class="chevron" :class="{ open: m.markdownOpen }" aria-hidden="true"></span>
                    <span>位置诊断</span>
                    <span class="field-tip">
                      <span class="field-hint">{{ m.markdown.split('\n').length }} 行</span>
                      <span class="tip-bubble">发给诊断 agent 的简历文本；每行开头的 [s:章节 r:窗口 c:内容 i:子项] 用来定位</span>
                    </span>
                  </button>
                  <pre v-if="m.markdownOpen" class="agent-markdown">{{ m.markdown }}</pre>
                </div>

                <!-- 📚 优秀示例：本次诊断实际参考的示例 + 提炼出的写作规范 -->
                <div v-if="m.references.length" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.examplesOpen = !m.examplesOpen">
                    <span class="chevron" :class="{ open: m.examplesOpen }" aria-hidden="true"></span>
                    <span>优秀示例</span>
                    <span class="field-tip">
                      <span class="field-hint">
                        {{ m.references.length }} 份{{ m.styleNotes.length ? ` · ${m.styleNotes.length} 条规范` : '' }}
                      </span>
                      <span class="tip-bubble">
                        诊断时参考的他人简历：只借写作方式与结构，事实仍来自你的简历；提炼出的写作规范会交给修改 agent 执行
                      </span>
                    </span>
                  </button>
                  <div v-if="m.examplesOpen" class="ref-notes">
                    <div v-for="(r, ri) in m.references" :key="r.id" class="ref-note-item">
                      <div class="ref-note-head">
                        <span class="ref-note-index">示例 {{ ri + 1 }}</span>
                        <span class="ref-note-direction">{{ r.direction }}</span>
                      </div>
                      <p class="ref-note-desc">{{ r.description }}</p>
                    </div>
                    <div v-if="m.styleNotes.length" class="style-notes">
                      <div class="style-notes-title">提炼的写作规范</div>
                      <ol class="style-notes-list">
                        <li v-for="(note, ni) in m.styleNotes" :key="ni">{{ note }}</li>
                      </ol>
                    </div>
                  </div>
                </div>

                <!-- 💭 思考过程：模型 reasoning_content 字段，折叠；模型没返回思考则给提示 -->
                <div class="agent-block">
                  <button class="agent-sub-toggle" @click="m.thinkingOpen = !m.thinkingOpen">
                    <span class="chevron" :class="{ open: m.thinkingOpen }" aria-hidden="true"></span>
                    <span>思考过程</span>
                    <span class="field-tip">
                      <span class="field-hint">reasoning_content</span>
                      <span class="tip-bubble">思考参考模型的 reasoning_content 字段；模型没返回这个字段，就是没有思考过程</span>
                    </span>
                  </button>
                  <div v-if="m.thinkingOpen && m.thinking" class="agent-think">{{ m.thinking }}</div>
                </div>

                <!-- 🔧 工具调用：折叠（web_search 单独在下一块展示） -->
                <div v-if="toolRows(m.steps).length" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.toolsOpen = !m.toolsOpen">
                    <span class="chevron" :class="{ open: m.toolsOpen }" aria-hidden="true"></span>
                    <span>工具调用</span>
                    <span class="field-tip">
                      <span class="field-hint">{{ toolRows(m.steps).length }} 次</span>
                      <span class="tip-bubble">该 agent 实际调用的工具，如 review_diagnosis 审查诊断、patch_content 执行修改</span>
                    </span>
                  </button>
                  <div v-if="m.toolsOpen" class="steps">
                    <div v-for="(row, si) in toolRows(m.steps)" :key="si" class="step" :class="row.kind">
                      <div class="tool-line"><span class="tool-name">调用工具 {{ row.tool }}</span><span class="tool-args">{{ row.args }}</span></div>
                      <div v-if="row.result" class="tool-result">↳ {{ row.result }}</div>
                    </div>
                  </div>
                </div>

                <!-- 🌐 Web 搜索：只诊断 agent 会联网；排在工具之后、回答之前 -->
                <div v-if="m.searches.length" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.searchesOpen = !m.searchesOpen">
                    <span class="chevron" :class="{ open: m.searchesOpen }" aria-hidden="true"></span>
                    <span>Web 搜索</span>
                    <span class="field-tip">
                      <span class="field-hint">{{ m.searches.length }} 次</span>
                      <span class="tip-bubble">诊断时查的外部公开资料，只用于核对术语、公司背景和岗位标准，不会写进简历事实</span>
                    </span>
                  </button>
                  <div v-if="m.searchesOpen" class="searches">
                    <div v-for="(s, si) in m.searches" :key="si" class="search">
                      <div class="search-query">
                        <span class="search-text">{{ s.query }}</span>
                        <span v-if="!s.results.length" class="search-empty">
                          {{ s.error ? '搜索失败' : '无结果' }}
                        </span>
                      </div>
                      <div v-if="s.error" class="search-error">{{ s.error }}</div>
                      <a
                        v-for="(r, ri) in s.results"
                        :key="ri"
                        class="search-result"
                        :href="r.url"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <span class="search-title">{{ r.title }}</span>
                        <span class="search-url">{{ r.url }}</span>
                        <span v-if="r.content" class="search-content">{{ r.content }}</span>
                      </a>
                    </div>
                  </div>
                </div>

                <!-- ❓ 追问记录：排在工具之后；待回答时展示表单，答完/失效后折叠成一行 -->
                <div v-if="m.questions.length" class="agent-block">
                  <template v-for="q in m.questions" :key="q.questionId">
                    <AskQuestionCard
                      v-if="q.status === 'pending' || q.status === 'submitting'"
                      :item="q"
                      @submit="onSubmitQuestion"
                    />
                    <template v-else>
                      <button class="agent-sub-toggle" @click="m.questionsOpen = !m.questionsOpen">
                        <span class="chevron" :class="{ open: m.questionsOpen }" aria-hidden="true"></span>
                        <span>追问记录</span>
                        <span class="field-tip">
                          <span class="field-hint">
                            {{ q.questions.length }} 个问题 ·
                            {{ q.status === 'answered' ? '已回答' : '已失效' }}
                          </span>
                          <span class="tip-bubble">诊断 agent 在诊断前向你确认的信息；点开可回看问题和答案</span>
                        </span>
                      </button>
                      <div v-if="m.questionsOpen" class="question-archive">
                        <AskQuestionCard :item="q" @submit="onSubmitQuestion" />
                      </div>
                    </template>
                  </template>
                </div>

                <!-- 💬 回答：模型 content 字段，折叠；内容按 Markdown 渲染 -->
                <div v-if="m.text" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.answerOpen = !m.answerOpen">
                    <span class="chevron" :class="{ open: m.answerOpen }" aria-hidden="true"></span>
                    <span>回答</span>
                  </button>
                  <div v-if="m.answerOpen" class="agent-answer" v-html="renderMarkdown(m.text)"></div>
                </div>
              </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 工具进行中：在输入区上方就地提示，不走全局 toast（否则会飘到页面顶部） -->
      <div v-if="enhancing" class="enhance-loading">
        <n-spin :size="12" />
        <span>正在增强提示词…</span>
      </div>
      <div v-if="grammarRunning" class="enhance-loading">
        <n-spin :size="12" />
        <span>正在检查全文语法与拼写…</span>
      </div>

      <!-- 输入区 -->
      <div class="chat-input">
        <n-input
          ref="chatInputRef"
          v-model:value="draft"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入修改要求，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="onSend"
        />
        <!-- 设置菜单：简历工具 / 输入工具 / 优化强度 -->
        <n-popover
          v-model:show="settingsShow"
          trigger="click"
          placement="top-start"
          :width="304"
        >
          <template #trigger>
            <n-button
              class="settings-btn"
              quaternary
              size="small"
              aria-label="简历工具与设置"
              :aria-expanded="settingsShow"
            >
              <IconGlyph name="sliders-horizontal" :size="17" />
            </n-button>
          </template>

          <div class="composer-menu" role="menu" aria-label="简历工具与设置">
            <div class="composer-menu-group">
              <div class="composer-menu-label">简历工具</div>
              <button
                type="button"
                role="menuitem"
                class="composer-menu-item"
                :disabled="optimizeStore.sending || grammarRunning"
                @click="onGrammarCheck"
              >
                <span class="menu-icon" aria-hidden="true">
                  <IconGlyph name="scan-line" :size="16" />
                </span>
                <span class="menu-text">
                  <span class="menu-title">
                    全文纠错
                    <n-spin v-if="grammarRunning" :size="11" />
                  </span>
                  <span class="menu-desc">
                    {{
                      optimizeStore.pendingDiff
                        ? '还有一份修改待确认，重新检查会先请你确认放弃'
                        : '检查错别字、标点与语病，逐处对比后应用'
                    }}
                  </span>
                </span>
              </button>
            </div>

            <div class="composer-menu-divider" />

            <div class="composer-menu-group">
              <div class="composer-menu-label">输入工具</div>
              <button
                type="button"
                role="menuitem"
                class="composer-menu-item"
                :disabled="optimizeStore.sending || enhancing || grammarRunning"
                @click="onEnhancePrompt"
              >
                <span class="menu-icon" aria-hidden="true">
                  <IconGlyph name="sparkles" :size="16" />
                </span>
                <span class="menu-text">
                  <span class="menu-title">提示词增强</span>
                  <span class="menu-desc">把口语化要求改写成更明确的提示词</span>
                </span>
              </button>
            </div>

            <div class="composer-menu-divider" />

            <div class="composer-menu-group">
              <div class="composer-menu-label">优化强度</div>
              <div class="mode-options" role="radiogroup" aria-label="优化强度">
                <button
                  type="button"
                  role="menuitemradio"
                  class="mode-option"
                  :class="{ active: optimizeStore.rewriteMode === 'standard' }"
                  :aria-checked="optimizeStore.rewriteMode === 'standard'"
                  @click="onSetRewriteMode('standard')"
                >
                  <span class="mode-radio" aria-hidden="true" />
                  <span class="mode-copy">
                    <span class="mode-name">标准</span>
                    <span class="mode-desc">保留原句式，只做必要改写</span>
                  </span>
                  <IconGlyph
                    v-if="optimizeStore.rewriteMode === 'standard'"
                    class="mode-check"
                    name="check"
                    :size="14"
                  />
                </button>
                <button
                  type="button"
                  role="menuitemradio"
                  class="mode-option"
                  :class="{ active: optimizeStore.rewriteMode === 'bold' }"
                  :aria-checked="optimizeStore.rewriteMode === 'bold'"
                  @click="onSetRewriteMode('bold')"
                >
                  <span class="mode-radio" aria-hidden="true" />
                  <span class="mode-copy">
                    <span class="mode-name">大胆</span>
                    <span class="mode-desc">可大幅重写表达，不新增事实、不改结构</span>
                  </span>
                  <IconGlyph
                    v-if="optimizeStore.rewriteMode === 'bold'"
                    class="mode-check"
                    name="check"
                    :size="14"
                  />
                </button>
              </div>
            </div>
          </div>
        </n-popover>
        <n-button
          type="primary"
          size="small"
          :disabled="optimizeStore.sending || grammarRunning"
          @click="onSend"
        >
          发送
        </n-button>
      </div>
    </section>
  </main>

  <!-- 诊断结论弹窗：从时间线最前面的入口打开；状态随优化过程实时更新。
       z-index 显式抬高，保证它叠加在「对比弹窗」之上（两个都是 n-modal，默认层级不够可靠） -->
  <n-modal
    v-model:show="diagShow"
    display-directive="if"
    preset="card"
    :z-index="5000"
    style="width: 980px; max-width: 94vw"
  >
    <template #header>
      <div class="diag-modal-head">
        <span class="diag-report-icon" aria-hidden="true"><IconGlyph name="scan-line" :size="12" /></span>
        <span class="diag-modal-title">诊断结论</span>
        <!-- 状态说明：讲清「修改建议」和「最终执行」两列分别按什么标准判断 -->
        <n-popover
          trigger="click"
          placement="bottom-start"
          :width="400"
          :z-index="6000"
          :show-arrow="false"
          :style="{
            boxShadow: '0 12px 32px -12px rgba(28, 33, 48, 0.28), 0 0 0 1px var(--border-strong)',
          }"
        >
          <template #trigger>
            <button type="button" class="diag-help-btn" aria-label="状态说明" title="两列状态是怎么判断的">
              <IconGlyph name="info" :size="14" />
            </button>
          </template>
          <div class="diag-help">
            <div class="diag-help-section">
              <div class="diag-help-head">
                <span class="diag-help-title">修改建议</span>
                <span class="diag-help-sub">诊断阶段</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag d-must">必须修改</span>
                <span class="diag-help-desc">事实错误、关键信息缺失、与 JD 硬性要求不符</span>
                <span class="diag-help-flag must">一定修改</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag d-suggest">建议修改</span>
                <span class="diag-help-desc">没有硬伤，但能更专业、更量化、更贴合 JD</span>
                <span class="diag-help-flag">概率更改</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag d-keep">可以保留</span>
                <span class="diag-help-desc">原文已清晰准确，不必改</span>
                <span class="diag-help-flag">禁止修改</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag d-insufficient">信息不足</span>
                <span class="diag-help-desc">缺少关键信息，问不到就不改</span>
                <span class="diag-help-flag">禁止修改</span>
              </div>
            </div>
            <div class="diag-help-section">
              <div class="diag-help-head">
                <span class="diag-help-title">最终执行</span>
                <span class="diag-help-sub">优化阶段</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag st-pending">待分析</span>
                <span class="diag-help-desc">还没审查</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag st-change">待修改</span>
                <span class="diag-help-desc">判定要改，等待执行</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag st-skip">不更改</span>
                <span class="diag-help-desc">判定不改，收益不足或有风险</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag st-done">已修改</span>
                <span class="diag-help-desc">已替换成新文字</span>
              </div>
              <div class="diag-help-row">
                <span class="diag-help-tag st-failed">未执行</span>
                <span class="diag-help-desc">坐标或原文对不上</span>
              </div>
            </div>
          </div>
        </n-popover>
        <span class="diag-report-count">{{ diagDetail?.diagnosis.length ?? 0 }} 处</span>
        <span class="diag-report-chips">
          <span
            v-for="c in diagDetail ? diagCounts(diagDetail.diagnosis) : []"
            :key="c.status"
            class="diag-chip"
            :class="c.status"
          >
            {{ c.label }} {{ c.count }}
          </span>
        </span>
      </div>
    </template>

    <div v-if="diagDetail" ref="diagListEl" class="diag-modal-list">
      <div
        v-for="group in groupedDiag"
        :key="diagGroupKey(group)"
        class="diag-group"
      >
        <!-- 章节标题：树的一级节点，点击折叠/展开章内诊断项 -->
        <div
          class="diag-group-head"
          :class="{ collapsed: collapsedGroups.has(diagGroupKey(group)) }"
          role="button"
          tabindex="0"
          @click="toggleGroup(diagGroupKey(group))"
          @keydown.enter="toggleGroup(diagGroupKey(group))"
        >
          <IconGlyph name="chevron-down" :size="14" class="diag-group-caret" />
          <span class="diag-group-title">{{ group.section }}</span>
          <span class="diag-group-count">{{ group.items.length }} 处</span>
        </div>
        <!-- 章内诊断项：树的叶子节点 -->
        <div v-if="!collapsedGroups.has(diagGroupKey(group))" class="diag-group-items">
          <div
            v-for="(it, gi) in group.items"
            :key="it.di"
            class="diag-item"
            :class="[`s-${it.d.status ?? 'pending'}`, { 'diag-flash': diagFlashIndex === it.di }]"
            :data-diag-index="it.di"
          >
            <div class="diag-head">
              <span class="diag-index">{{ gi + 1 }}</span>
              <span v-if="it.d.location" class="diag-location">{{ it.d.location }}</span>
              <span v-if="it.d.quote" class="diag-quote">「{{ it.d.quote }}」</span>
              <span v-else class="diag-tag">无原文片段</span>
              <!-- 右侧：只有这处真的改了，才有跳回对比弹窗的入口 -->
              <span class="diag-head-right">
                <button
                  v-if="diffKeyByDiagIndex.has(it.di)"
                  type="button"
                  class="diag-jump-diff"
                  title="回到对比弹窗，定位这处改动"
                  @click="onJumpToDiff(it.di)"
                >
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M16 3h5v5M21 3l-7 7M8 21H3v-5M3 21l7-7"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  查看对比
                </button>
              </span>
            </div>
            <!-- 两个状态分开写清楚：诊断给的建议 vs 优化阶段最终是改还是没改 -->
            <div class="diag-states">
              <span class="diag-state">
                <span class="diag-state-label">修改建议</span>
                <span
                  class="diag-state-value"
                  :class="`d-${it.d.disposition ?? 'suggest'}`"
                >
                  {{ DIAG_DISPOSITION_LABEL[it.d.disposition ?? 'suggest'] }}
                </span>
              </span>
              <span class="diag-state">
                <span class="diag-state-label">最终执行</span>
                <span
                  class="diag-state-value"
                  :class="`st-${it.d.status ?? 'pending'}`"
                >
                  {{ DIAG_STATUS_LABEL[it.d.status ?? 'pending'] }}
                </span>
              </span>
            </div>
            <!-- 标签列固定宽度，标题和每条正文左边缘对齐，长文也整齐 -->
            <div class="diag-grid">
              <span class="diag-label">问题</span>
              <span class="diag-value">{{ it.d.reason }}</span>
              <span class="diag-label">方向</span>
              <span class="diag-value">{{ it.d.suggestion }}</span>
              <span class="diag-label">依据</span>
              <span class="diag-value">{{ it.d.evidence }}</span>
              <template v-if="it.d.reference">
                <span class="diag-label">示例</span>
                <span class="diag-value">{{ it.d.reference }}</span>
              </template>
              <template v-if="it.d.note">
                <span class="diag-label">{{ it.d.status === 'failed' ? '失败原因' : '判定理由' }}</span>
                <span class="diag-value">{{ it.d.note }}</span>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="diag-modal-footer">
        <span class="diag-modal-hint">已按简历章节分组 · 状态会随优化过程实时更新</span>
        <n-button size="small" type="primary" @click="diagShow = false">关闭</n-button>
      </div>
    </template>
  </n-modal>

  <!-- AI 修改对比弹窗：后端返回改好的简历后自动弹出；
       每处可单独 ← 还原 / → 恢复，点「确定应用」才把结果写回简历 -->
  <ResumeDiffDialog
    :show="optimizeStore.diffOpen && !!optimizeStore.pendingDiff"
    :title="diffTitle"
    :before="optimizeStore.pendingDiff?.before ?? []"
    :after="optimizeStore.pendingDiff?.after ?? []"
    :reverted="optimizeStore.pendingDiff?.reverted ?? []"
    :diagnosis="latestDiagnosis"
    :flash="diffFlash"
    @update:show="(v: boolean) => { if (!v) optimizeStore.dismissDiff() }"
    @toggle="(key: string) => optimizeStore.toggleDiffChange(key)"
    @revert-all="optimizeStore.revertAllDiff()"
    @accept-all="optimizeStore.acceptAllDiff()"
    @jump-diagnosis="onJumpToDiagnosis"
    @apply="onApplyDiff"
    @discard="onDiscardDiff"
  />

  <!-- 提示词增强对比：确认后才写回输入框，取消则保持原样 -->
  <n-modal
    v-model:show="enhanceShow"
    display-directive="if"
    preset="card"
    style="width: 900px; max-width: 94vw"
  >
    <template #header>
      <div class="enhance-modal-head">
        <span class="enhance-modal-icon" aria-hidden="true">✦</span>
        <span class="enhance-modal-title">提示词增强</span>
      </div>
    </template>
    <div class="enhance-compare">
      <div class="enhance-col before">
        <div class="enhance-col-head">增强前</div>
        <div class="enhance-text">{{ enhanceBefore }}</div>
      </div>
      <div class="enhance-arrow" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path
            d="M5 12h14m-5-5 5 5-5 5"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>
      <div class="enhance-col after">
        <div class="enhance-col-head">
          <span class="enhance-col-icon" aria-hidden="true">✦</span>
          <span>增强后</span>
          <span class="enhance-editable">可编辑</span>
        </div>
        <textarea
          ref="enhanceEditorEl"
          v-model="enhanceAfter"
          class="enhance-text enhance-editor"
          aria-label="增强后的提示词，可直接编辑"
          spellcheck="false"
        ></textarea>
      </div>
    </div>
    <template #footer>
      <div class="enhance-actions">
        <n-button size="small" @click="enhanceShow = false">取消</n-button>
        <n-button size="small" type="primary" @click="onApplyEnhance">确定</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.optimize-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--app-bg);
}

/* ---- 左：简历渲染 ---- */
.resume-panel {
  flex: 1 1 55%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

/* 隐藏测量层：移出可视区并隐藏，用于计算分页（与预览组件的做法一致） */
.measure-flow {
  position: absolute;
  top: 0;
  left: -9999px;
  visibility: hidden;
}
/* 隐藏导出流：移出可视区，导出 PDF 时把整份简历克隆进 iframe（无边框、无页码水印） */
.export-pages {
  position: fixed;
  top: 0;
  left: -9999px;
}
.export-flow {
  box-sizing: border-box;
  background: #fff;
}
/* 每一页是一个纸块：纸宽、四周留白由 inline style 提供，
   固定高度 + overflow hidden + break-inside avoid + break-after 独占一页，
   确保 Chromium 打 PDF 时把"一页的块"当成一整页，绝不硬拆成两页；
   块比物理页多出来的零点几像素（取整测量误差）被裁掉，而不是多出一页。
   高度由 inline style 固定为 pageHeight，配合 @page size 与纸面一致 */
.export-page {
  box-sizing: border-box;
  width: 100%;
  background: #fff;
  overflow: hidden;
  break-inside: avoid;
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}
.panel-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}
.panel-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.panel-spacer {
  flex: 1;
}
.resume-scroll {
  flex: 1;
  overflow: auto;
  padding: var(--doc-workspace-pad);
  /* 工作区：均匀中性浅灰，与纯白纸张形成清晰对比（与「实时预览」同款） */
  background: var(--doc-workspace);
}
/* 与「实时预览」同款分页：一张张 A4 纸 + 页间距 + 页码 */
.page-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--doc-page-gap);
}
.a4-page {
  position: relative;
  background: var(--doc-paper);
  box-shadow: var(--doc-paper-shadow);
  /* 宽度 / 最小高 / 内边距 / 缩放由 pageStyle 动态设置（与实时预览的 A4 纸张一致） */
}
.page-number {
  position: absolute;
  bottom: 12px;
  right: 16px;
  font-size: 11px;
  color: var(--text-tertiary);
  pointer-events: none;
}
.resume-empty {
  padding: 60px 0;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12.5px;
}

/* ---- 右：JD + 对话 ---- */
.chat-panel {
  flex: 1 1 45%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.jd-section {
  border-bottom: 1px solid var(--border);
  background: var(--panel-bg);
}
.jd-toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 9px 16px;
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: background 0.16s var(--ease), color 0.16s var(--ease);
}
.jd-toggle:hover {
  background: var(--surface-soft);
  color: var(--text);
}
/* 折叠箭头：用边框画的小折角，展开时旋转 90°，不占额外宽度 */
.jd-caret {
  flex: none;
  position: relative;
  width: 11px;
  height: 11px;
  color: var(--text-tertiary);
  transition: color 0.16s var(--ease);
}
.jd-caret::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 50%;
  width: 5px;
  height: 5px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  border-radius: 1px;
  transform: translateY(-50%) rotate(-45deg);
  transition: transform 0.2s var(--ease);
}
.jd-toggle.open .jd-caret::before {
  transform: translateY(-50%) rotate(45deg);
}
.jd-toggle.open .jd-caret,
.jd-toggle:hover .jd-caret {
  color: var(--primary);
}
.jd-toggle-text {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.jd-body {
  padding: 0 16px 12px;
  animation: block-reveal 0.22s var(--ease) both;
}

.chat-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  row-gap: 6px;
  padding: 9px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--panel-bg);
}
/* 右侧操作整组：宽度够时靠右，窄到换行时也整组贴右，不会散成左对齐 */
.chat-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  row-gap: 6px;
  margin-left: auto;
}
.chat-heading {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: none;
  min-width: 0;
}
.chat-heading-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 19px;
  height: 19px;
  border-radius: 6px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 10px;
  line-height: 1;
}
.session-id {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-soft);
  font-size: 10.5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--text-tertiary);
  white-space: nowrap;
  cursor: help;
  transition: background 0.16s var(--ease), color 0.16s var(--ease);
}
.session-id:hover {
  background: var(--surface-sunken);
  color: var(--text-secondary);
}
/* 对话栏变窄时先让会话 id（辅助信息）让位，避免右侧按钮被裁掉 */
@media (max-width: 980px) {
  .session-id {
    display: none;
  }
}
@media (max-width: 780px) {
  .chat-header {
    gap: 6px;
  }
  .chat-heading-icon {
    display: none;
  }
}

.chat-list {
  flex: 1;
  overflow: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
/* 空状态：一枚柔和的 AI 标记 + 两条示例，把「怎么开口」变得具体 */
.chat-empty {
  margin: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  max-width: 340px;
  padding: 24px 8px;
  text-align: center;
  animation: msg-in 0.35s var(--ease) both;
}
.chat-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 16px;
  line-height: 1;
}
.chat-empty-title {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.chat-empty-examples {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chat-empty-examples span {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 11.5px;
  line-height: 1.6;
}
.chat-msg {
  display: flex;
  animation: msg-in 0.3s var(--ease) both;
}
.chat-msg.from-user {
  justify-content: flex-end;
}
.chat-msg.from-ai {
  justify-content: flex-start;
}
.msg-block {
  max-width: 82%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.from-user .msg-block {
  align-items: flex-end;
}
/* 过程消息（阶段状态 / agent 卡）统一占满对话栏，保证各 agent 卡长度一致 */
.msg-block.from-process {
  width: 100%;
  max-width: 100%;
}
/* 并入诊断卡的前置状态行（convert 完成提示） */
.agent-lead {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-tertiary);
  line-height: 1.6;
}
/* 过程 agent（诊断/优化）：可折叠卡片，默认收起 */
.from-process {
  justify-content: flex-start;
}
/* 流程节点：左侧一条轨道（节点标记 + 指向下一个节点的竖线箭头），
   右侧是纯白可折叠卡片 —— 诊断 → 优化 → 总结的执行顺序一眼可见。
   标记用靛蓝，竖线用中性发丝线，语义色不参与主状态。 */
.flow-node {
  display: flex;
  align-items: stretch;
  gap: 8px;
  width: 100%;
  min-width: 0;
}
.flow-rail {
  position: relative;
  flex: none;
  width: 18px;
}
.flow-marker {
  position: absolute;
  top: 7px;
  left: 0;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: var(--panel-bg);
  color: var(--text-tertiary);
  transition: border-color 0.16s var(--ease), background 0.16s var(--ease);
}
.flow-node.running .flow-marker {
  border-color: var(--primary);
  color: var(--primary);
  animation: node-breathe 1.6s ease-in-out infinite;
}
.flow-node.done .flow-marker {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
  animation: check-in 0.32s var(--ease);
}
/* 竖线从标记下沿一直画到卡片底部之外，落进节点之间的间隙 */
.flow-line {
  position: absolute;
  left: 50%;
  top: 25px;
  bottom: -14px;
  width: 1px;
  margin-left: -0.5px;
  background: var(--border-strong);
}
/* 指向下一个节点的小箭头：边框画的实心三角，与竖线同色 */
.flow-arrow {
  position: absolute;
  left: 50%;
  bottom: -15px;
  width: 0;
  height: 0;
  margin-left: -3px;
  border-left: 3px solid transparent;
  border-right: 3px solid transparent;
  border-top: 5px solid var(--border-strong);
}
/* 最后一个节点没有下一个可指，收掉竖线与箭头 */
.flow-node.is-last .flow-line,
.flow-node.is-last .flow-arrow {
  display: none;
}
@keyframes node-breathe {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(71, 83, 199, 0);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(71, 83, 199, 0.14);
  }
}
/* 节点卡片：与诊断结论弹窗、整页面板同一层级 —— 纯白面板 + 发丝线描边 */
.flow-card {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color 0.16s var(--ease);
}
.flow-card:hover {
  border-color: var(--border-strong);
}
/* 节点头：标题 + 状态摘要 + 折叠箭头，整行可点 */
.flow-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 11px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.16s var(--ease);
}
.flow-head:hover {
  background: var(--surface-soft);
}
.flow-title {
  flex: none;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.flow-status {
  flex: 1;
  min-width: 0;
  font-size: 11.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flow-status::before {
  content: '';
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 5px;
  border-radius: 50%;
  background: currentColor;
  vertical-align: 1px;
}
.flow-status.running {
  color: var(--primary);
}
.flow-caret {
  flex: none;
  display: inline-flex;
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease), color 0.16s var(--ease);
}
.flow-caret.open {
  transform: rotate(180deg);
  color: var(--primary);
}
/* 折叠态的缩略内容：只留一行，超出直接省略号。
   截断放在内层 —— 外层是 flex 子项，内边距不该参与文字截断的计算。 */
.flow-preview {
  min-width: 0;
  /* 上下留白取同一个值：节点头悬停底色下边 → 文字，与文字 → 卡片下边框等距 */
  padding: 8px 11px;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-secondary);
}
.flow-preview > span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 结论入口 / 诊断占位条放进卡片后，四周留出与卡片内文一致的内缩；
   上下用同一个 8px，节点头到结论、结论到卡片下边框的留白才对称 */
.flow-card > .diag-pending,
.flow-card > .diag-entry {
  width: auto;
  margin: 8px 9px;
}
.status-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex: none;
}
.status-mark .check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  line-height: 1;
}
.status-line.done .check {
  color: var(--primary);
  animation: check-in 0.32s var(--ease);
}
.status-mark .pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  animation: dot-pulse 1.2s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.3);
  }
}
@keyframes check-in {
  0% {
    opacity: 0;
    transform: scale(0.4);
  }
  60% {
    opacity: 1;
    transform: scale(1.12);
  }
  100% {
    transform: scale(1);
  }
}
/* 折叠箭头：边框画的折角，展开时旋转 90°，避免两个字形切换时的跳动 */
.chevron {
  position: relative;
  flex: none;
  width: 11px;
  height: 11px;
  color: var(--text-tertiary);
  transition: color 0.16s var(--ease);
}
.chevron::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 50%;
  width: 4.5px;
  height: 4.5px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  border-radius: 1px;
  transform: translateY(-50%) rotate(-45deg);
  transition: transform 0.2s var(--ease);
}
.chevron.open::before {
  transform: translateY(-50%) rotate(45deg);
}
.agent-sub-toggle:hover .chevron,
.chevron.open {
  color: var(--primary);
}
/* 阶段状态行：convert 等非 agent 阶段（中性 pending → 主题色已完成） */
.status-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  background: var(--surface-soft);
  color: var(--text-secondary);
}
.status-line.done {
  background: var(--surface-sunken);
  color: var(--text-secondary);
}
.status-line-text {
  white-space: nowrap;
}
/* 卡片内分区：思考过程 / 工具调用 / 回答 */
.agent-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
/* 分隔线居中：线上方是 flex gap 8，线下方同样留 8 */
.agent-block + .agent-block {
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
/* 思考/工具的折叠开关行（标题可点）：负外边距让文字仍与卡片内文左对齐 */
.agent-sub-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  margin-left: -6px;
  padding: 2px 6px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: background 0.16s var(--ease), color 0.16s var(--ease);
}
.agent-sub-toggle:hover {
  color: var(--text-secondary);
  background: var(--surface-soft);
}
/* 字段小提示：悬浮弹出解释气泡 */
.field-tip {
  position: relative;
  display: inline-flex;
}
.field-hint {
  font-size: 9px;
  font-weight: 500;
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-bg);
  color: var(--text-tertiary);
  cursor: help;
}
/* 悬浮气泡：悬停在字段标签上才显示 */
.tip-bubble {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  min-width: 180px;
  max-width: 260px;
  width: max-content;
  padding: 6px 9px;
  background: var(--text);
  color: #fff;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
  white-space: normal;
  text-align: left;
  border-radius: 6px;
  box-shadow: var(--shadow-raised);
  z-index: 30;
  opacity: 0;
  visibility: hidden;
  transform: translate(-50%, 4px);
  transition:
    opacity 0.16s var(--ease),
    transform 0.16s var(--ease),
    visibility 0.16s var(--ease);
  pointer-events: none;
}
.field-tip:hover .tip-bubble {
  opacity: 1;
  visibility: visible;
  transform: translate(-50%, 0);
}
/* 展开详情：节点头下沿、分区之间、卡片下边框统一 8px ——
   第一块（如「思考过程」）上方 8px、下方到分隔线也是 8px，上下才对称 */
.agent-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 11px;
}
/* 紧跟诊断结论 / 诊断占位条时，上方留白已由它们的下边距提供，不再叠加 */
.diag-entry + .agent-body,
.diag-pending + .agent-body {
  padding-top: 0;
}
/* 折叠内容出现时轻轻下落，减少"凭空冒出来"的生硬感 */
.agent-think,
.agent-markdown,
.steps,
.searches,
.question-archive,
.agent-answer,
.diag-pending,
.ref-notes {
  animation: block-reveal 0.22s var(--ease) both;
}
/* 优秀示例：本次参考的示例（方向 + 描述）+ 从示例提炼出的写作规范 */
.ref-notes {
  display: flex;
  flex-direction: column;
  gap: 7px;
  border-top: 1px solid var(--border);
  padding-top: 6px;
}
.ref-note-item {
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-soft);
}
.ref-note-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 7px;
}
.ref-note-index {
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
}
.ref-note-direction {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text);
}
.ref-note-desc {
  margin: 3px 0 0;
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
.style-notes {
  padding: 8px 10px;
  border: 1px solid var(--primary-soft);
  border-radius: 7px;
  background: var(--primary-faint);
}
.style-notes-title {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--primary-hover);
}
.style-notes-list {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-secondary);
}
.style-notes-list li + li {
  margin-top: 2px;
}
/* 诊断思考正文：正常字体，与步骤区分 */
.agent-think {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-top: 1px solid var(--border);
  padding-top: 6px;
}
/* 位置诊断：带 [s:章节 r:窗口 c:内容 i:子项] 的简历文本，等宽展示、内部滚动 */
.agent-markdown {
  margin: 0;
  padding: 8px 10px;
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-soft);
  color: var(--text-secondary);
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
/* 诊断结论占位：思考阶段占住「诊断结论」的位置，扫光 + 跳动圆点表示还在诊断 */
.diag-pending {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 10px 12px;
  overflow: hidden;
  border: 1px dashed var(--primary-soft);
  border-radius: var(--radius-md);
  background: var(--primary-faint);
  color: var(--primary-hover);
  font-size: 13px;
}
.diag-pending::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    100deg,
    transparent 25%,
    rgba(71, 83, 199, 0.1) 50%,
    transparent 75%
  );
  transform: translateX(-100%);
  animation: diag-pending-scan 1.8s ease-in-out infinite;
  pointer-events: none;
}
/* 文字压在扫描光带上面 */
.diag-pending-icon,
.diag-pending-text,
.diag-pending-dots {
  position: relative;
  z-index: 1;
}
.diag-pending-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  line-height: 1;
  animation: diag-pending-breathe 1.8s ease-in-out infinite;
}
.diag-pending-text {
  font-weight: 600;
}
.diag-pending-dots {
  display: inline-flex;
  gap: 3px;
}
.diag-pending-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--primary);
  opacity: 0.25;
  animation: diag-pending-dot 1.2s ease-in-out infinite;
}
.diag-pending-dots i:nth-child(2) {
  animation-delay: 0.2s;
}
.diag-pending-dots i:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes diag-pending-scan {
  to {
    transform: translateX(100%);
  }
}
@keyframes diag-pending-breathe {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(71, 83, 199, 0);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(71, 83, 199, 0.14);
  }
}
@keyframes diag-pending-dot {
  0%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

/* 诊断结论入口：整宽按钮，呼吸闪烁提示可点，点开是大弹窗 */
.diag-entry {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--primary-soft);
  border-radius: var(--radius-md);
  background: var(--primary-faint);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  animation: diag-breathe 2.6s ease-in-out infinite;
  transition: border-color 0.16s var(--ease), transform 0.16s var(--ease);
}
.diag-entry:hover {
  border-color: var(--primary);
  background: var(--primary-faint);
  transform: translateY(-1px);
}
.diag-entry-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  line-height: 1;
}
.diag-entry-main {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.diag-entry-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.diag-entry-chips {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}
.diag-entry-action {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary);
  white-space: nowrap;
  transition: transform 0.16s var(--ease);
}
.diag-entry:hover .diag-entry-action {
  transform: translateX(2px);
}
@keyframes diag-breathe {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(71, 83, 199, 0);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(71, 83, 199, 0.14);
  }
}
@media (prefers-reduced-motion: reduce) {
  .diag-entry {
    animation: none;
  }
}
.diag-report-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 21px;
  height: 21px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  line-height: 1;
}
.diag-report-count {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-hover);
  font-size: 10.5px;
  font-weight: 700;
}
.diag-report-chips {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-left: auto;
}
/* 状态计数：只用一个 5px 色点 + 中性的数字文字，不做彩色底块 */
.diag-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-tertiary);
  font-size: 10.5px;
  font-weight: 500;
  white-space: nowrap;
}
.diag-chip::before {
  content: '';
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.9;
}
.diag-chip.change {
  color: var(--warning);
}
.diag-chip.done {
  color: var(--success);
}
.diag-chip.failed {
  color: var(--danger);
}
/* 诊断结论弹窗：大尺寸、列表内部滚动，每个条目独立小卡 */
.diag-modal-head {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.diag-modal-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
/* 标题旁的「状态说明」入口：圆形幽灵按钮，悬停才染主题色 */
.diag-help-btn {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.diag-help-btn:hover {
  background: var(--primary-soft);
  color: var(--primary);
}
/* 状态说明：两段标准，标签配色和卡片里的状态徽标完全一致 */
.diag-help {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 2px 2px 0;
}
.diag-help-section {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.diag-help-section + .diag-help-section {
  padding-top: 13px;
  border-top: 1px solid var(--border);
}
.diag-help-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.diag-help-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}
.diag-help-sub {
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.diag-help-row {
  display: grid;
  grid-template-columns: 60px 1fr auto;
  align-items: start;
  gap: 8px;
}
/* 右列一句话回答「这条是否必须改」 */
.diag-help-flag {
  font-size: 10.5px;
  line-height: 18px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.diag-help-flag.must {
  color: var(--danger);
  font-weight: 600;
}
/* 状态说明里的标签：与卡片上的状态值同一套「色点 + 小字」，方便直接对上 */
.diag-help-tag {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 18px;
  color: var(--text-tertiary);
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
}
.diag-help-tag::before {
  content: '';
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.diag-help-tag.d-must {
  color: var(--danger);
}
.diag-help-tag.d-suggest {
  color: var(--warning);
}
.diag-help-tag.d-keep {
  color: var(--success);
}
.diag-help-tag.d-insufficient {
  color: var(--text-tertiary);
}
.diag-help-tag.st-change {
  color: var(--warning);
}
.diag-help-tag.st-done {
  color: var(--success);
}
.diag-help-tag.st-failed {
  color: var(--danger);
}
.diag-help-desc {
  font-size: 11.5px;
  line-height: 18px;
  color: var(--text-secondary);
}
.diag-modal-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 68vh;
  overflow-y: auto;
  padding-right: 4px;
}
/* 树状分组：章节是一级节点，章内诊断项是叶子 */
.diag-group {
  display: flex;
  flex-direction: column;
}
.diag-group-head {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 2px 2px 7px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  cursor: pointer;
  border-radius: 6px;
  user-select: none;
  transition: color 0.16s var(--ease);
}
.diag-group-head:hover {
  color: var(--primary-hover);
}
/* 折叠箭头：chevron-down，展开向下、折叠旋转 90° 指向右 */
.diag-group-caret {
  flex: none;
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease);
}
.diag-group-head.collapsed .diag-group-caret {
  transform: rotate(-90deg);
}
.diag-group-title {
  min-width: 0;
  overflow-wrap: anywhere;
}
.diag-group-count {
  flex: none;
  color: var(--text-tertiary);
  font-size: 10.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
/* 叶子容器：左侧竖线 + 缩进，形成树的分支 */
.diag-group-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-left: 14px;
  border-left: 2px solid var(--border);
  margin-left: 5px;
}
.diag-modal-footer {
  display: flex;
  align-items: center;
  gap: 12px;
}
.diag-modal-hint {
  flex: 1;
  font-size: 11px;
  color: var(--text-tertiary);
}
.diag-item {
  position: relative;
  padding: 11px 13px 11px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  font-size: 12px;
  line-height: 1.6;
  animation: diag-item-in 0.28s var(--ease) both;
  transition: border-color 0.16s var(--ease);
}
.diag-item:hover {
  border-color: var(--border-strong);
}
/* 列表出现时按顺序轻微错峰，长列表也不会"整块砸下来" */
.diag-item:nth-child(2) {
  animation-delay: 0.03s;
}
.diag-item:nth-child(3) {
  animation-delay: 0.06s;
}
.diag-item:nth-child(4) {
  animation-delay: 0.09s;
}
.diag-item:nth-child(5) {
  animation-delay: 0.12s;
}
.diag-item:nth-child(6) {
  animation-delay: 0.15s;
}
.diag-item:nth-child(n + 7) {
  animation-delay: 0.18s;
}
/* 左侧状态色条：扫一眼就知道哪几处要改 / 已改 / 未执行 */
.diag-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: var(--border-strong);
}
.diag-item.s-change::before {
  background: var(--warning);
}
.diag-item.s-done::before {
  background: var(--success);
}
.diag-item.s-failed::before {
  background: var(--danger);
}
.diag-head {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 3px;
}
.diag-index {
  flex: none;
  min-width: 15px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
  line-height: 17px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.diag-quote {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.diag-tag {
  flex: none;
  padding: 0 6px;
  border-radius: 8px;
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  font-size: 10px;
  line-height: 17px;
}
/* 章内位置徽章（如「第 2 条」「第 3 个标签」）：落在章节标题下的具体位置 */
.diag-location {
  flex: none;
  padding: 0 6px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary-hover);
  font-size: 10px;
  line-height: 17px;
  white-space: nowrap;
}
/* 右侧区域：跳回对比弹窗的入口靠右对齐 */
.diag-head-right {
  flex: none;
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}
/* 两个状态：诊断给的「修改建议」+ 优化阶段的「最终执行结果」，分开标注避免混淆 */
.diag-states {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 16px;
  margin: 1px 0 6px;
}
.diag-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.diag-state-label {
  color: var(--text-tertiary);
  font-size: 10.5px;
  white-space: nowrap;
}
/* 「修改建议」「最终执行」的值：5px 色点 + 彩色小字。
   整页只有靛蓝一处品牌色，语义色只做状态提示、不做底块，避免变成后台看板。 */
.diag-state-value {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
  line-height: 17px;
  white-space: nowrap;
}
.diag-state-value::before {
  content: '';
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
/* 修改建议：必须修改(红) / 建议修改(琥珀) / 可以保留(绿) / 信息不足(灰) */
.diag-state-value.d-must {
  color: var(--danger);
}
.diag-state-value.d-suggest {
  color: var(--warning);
}
.diag-state-value.d-keep {
  color: var(--success);
}
.diag-state-value.d-insufficient {
  color: var(--text-tertiary);
}
/* 最终执行：待修改(琥珀) / 已修改(绿) / 未执行(红) / 不更改·待分析(灰) */
.diag-state-value.st-change {
  color: var(--warning);
}
.diag-state-value.st-done {
  color: var(--success);
}
.diag-state-value.st-failed {
  color: var(--danger);
}
/* 跳回对比弹窗的小按钮：只有该诊断对应到一处实际改动时才显示 */
.diag-jump-diff {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 7px;
  height: 17px;
  border: none;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary-hover);
  font-size: 10px;
  line-height: 17px;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.15s var(--ease), color 0.15s var(--ease);
}
.diag-jump-diff svg {
  width: 11px;
  height: 11px;
}
.diag-jump-diff:hover {
  background: var(--primary);
  color: #fff;
}
/* 从对比弹窗点「查看这条诊断」跳过来时，目标卡片靛蓝描边闪烁几下，便于定位。
   跳转是定位提示、不是错误，所以用品牌色而不是告警红。 */
.diag-flash {
  animation: diag-flash 0.9s var(--ease) 2;
  border-color: var(--primary) !important;
}
@keyframes diag-flash {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(71, 83, 199, 0);
  }
  50% {
    box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.38);
  }
}
/* 正文两列：标签右对齐、值左对齐，所有条目的正文左边缘对齐 */
.diag-grid {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 5px 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
.diag-label {
  color: var(--text-tertiary);
  font-size: 10.5px;
  line-height: 1.7;
  text-align: right;
  white-space: nowrap;
}
.diag-value {
  min-width: 0;
  color: var(--text-secondary);
  font-size: 12.5px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
/* 已结束的反问回看区 */
.question-archive {
  margin-top: 4px;
}
/* 反问卡嵌在流程节点卡片里时去掉外阴影，避免两层浮层 */
.flow-card :deep(.ask-card) {
  box-shadow: none;
}
/* 回答：Markdown 渲染结果，样式收敛一点更紧凑 */
.agent-answer {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
  border-top: 1px solid var(--border);
  padding-top: 6px;
}
.agent-answer :deep(p) {
  margin: 0 0 6px;
}
.agent-answer :deep(ul),
.agent-answer :deep(ol) {
  margin: 0 0 6px;
  padding-left: 18px;
}
.agent-answer :deep(li) {
  margin: 2px 0;
}
.agent-answer :deep(li + li) {
  margin-top: 2px;
}
.agent-answer :deep(h1),
.agent-answer :deep(h2),
.agent-answer :deep(h3),
.agent-answer :deep(h4) {
  margin: 6px 0 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.agent-answer :deep(code) {
  background: var(--surface-sunken);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11px;
}
.agent-answer :deep(pre) {
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  overflow-x: auto;
  margin: 0 0 6px;
}
.agent-answer :deep(a) {
  color: var(--primary);
  text-decoration: none;
}
.agent-answer :deep(a:hover) {
  text-decoration: underline;
}
.agent-answer :deep(blockquote) {
  margin: 0 0 6px;
  padding-left: 10px;
  border-left: 3px solid var(--border-strong);
  color: var(--text-secondary);
}
/* Web 搜索：一次搜索 = query 一行 + 结果列表（标题/URL/摘要） */
.searches {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-tertiary);
}
.search {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.search-query {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  column-gap: 5px;
  color: var(--text-secondary);
  font-weight: 600;
}
/* 查询前面点一个小圆点，区分「查询」和下面的结果 */
.search-query::before {
  content: '';
  flex: none;
  width: 5px;
  height: 5px;
  margin-right: 2px;
  border-radius: 50%;
  background: var(--primary);
  opacity: 0.6;
  align-self: center;
}
.search-text {
  overflow-wrap: anywhere;
}
.search-empty {
  padding: 0 5px;
  border-radius: 6px;
  background: var(--surface-soft);
  font-weight: 400;
  color: var(--text-tertiary);
}
.search-error {
  padding-left: 16px;
  color: var(--warning);
  overflow-wrap: anywhere;
}
.search-result {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 2px 6px 2px 10px;
  color: inherit;
  text-decoration: none;
  border-left: 2px solid transparent;
  border-radius: 0 6px 6px 0;
  transition: background 0.16s var(--ease), border-color 0.16s var(--ease);
}
.search-result:hover {
  border-left-color: var(--primary);
  background: var(--panel-bg);
}
.search-title {
  color: var(--text-secondary);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.search-result:hover .search-title {
  color: var(--primary);
}
.search-url {
  font-size: 10px;
  color: var(--text-tertiary);
  opacity: 0.8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.search-content {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--text-tertiary);
}
.steps {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-tertiary);
}
.step {
  overflow-wrap: anywhere;
}
/* 工具行：调用 + 坐标一行，返回结果缩进一行 */
.tool-line {
  display: flex;
  flex-wrap: wrap;
  column-gap: 6px;
}
.tool-name {
  color: var(--text-secondary);
  font-weight: 600;
}
.tool-result {
  padding-left: 12px;
  color: var(--text-tertiary);
  opacity: 0.8;
}
.bubble {
  max-width: 100%;
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.from-user .bubble {
  background: var(--primary);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 8px 18px -12px rgba(71, 83, 199, 0.55);
}
.from-ai .bubble {
  background: var(--surface-soft);
  color: var(--text);
  border-bottom-left-radius: 4px;
}
.bubble.typing {
  color: var(--text-tertiary);
  font-style: italic;
}
.bubble.error {
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid rgba(169, 79, 74, 0.25);
}

.chat-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 16px 14px;
  border-top: 1px solid var(--border);
  background: var(--panel-bg);
}
/* 输入框平时是浅灰内衬，聚焦时变纯白并亮起一圈靛蓝柔光 */
.chat-input :deep(.n-input) {
  flex: 1;
  border-radius: 11px;
  background-color: var(--surface-soft);
  transition: background-color 0.2s var(--ease), box-shadow 0.2s var(--ease);
}
.chat-input :deep(.n-input--focus) {
  background-color: var(--panel-bg);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.1);
}

/* ---- 提示词增强 ---- */
.enhance-loading {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  background: var(--primary-faint);
  font-size: 11.5px;
  font-weight: 500;
  color: var(--primary-hover);
  animation: block-reveal 0.2s var(--ease) both;
}
/* 增强提示条自带一条上边线，紧跟其后的输入区不再重复画线 */
.enhance-loading + .chat-input {
  border-top: none;
}

/* ---- 输入区设置菜单 ---- */
.settings-btn {
  color: var(--text-tertiary);
  transition: color 0.16s var(--ease), background-color 0.16s var(--ease);
}
.settings-btn:not(:disabled):hover {
  color: var(--primary);
}
.composer-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: -2px -4px;
}
/* JSON 处理触发按钮：文字与下箭头之间留一点间距 */
.json-menu-btn :deep(.n-button__content) {
  gap: 5px;
}
.composer-menu-group {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.composer-menu-label {
  padding: 5px 10px 3px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.composer-menu-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s var(--ease);
}
.composer-menu-item:not(:disabled):hover {
  background: var(--surface-soft);
}
.composer-menu-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.menu-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--primary-faint);
  color: var(--primary);
}
.menu-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.menu-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}
.menu-desc {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-tertiary);
}
.composer-menu-divider {
  height: 1px;
  margin: 5px 9px;
  background: var(--border);
}
.mode-options {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.mode-option {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s var(--ease);
}
.mode-option:hover {
  background: var(--surface-soft);
}
.mode-radio {
  position: relative;
  flex: none;
  width: 14px;
  height: 14px;
  margin-top: 2px;
  border: 1.5px solid var(--border-strong);
  border-radius: 50%;
  transition: border-color 0.15s var(--ease);
}
.mode-option.active .mode-radio {
  border-color: var(--primary);
}
.mode-option.active .mode-radio::after {
  content: '';
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: var(--primary);
}
.mode-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.mode-name {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--text);
}
.mode-option.active .mode-name {
  color: var(--primary);
}
.mode-desc {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-tertiary);
}
.mode-check {
  margin-left: auto;
  margin-top: 3px;
  color: var(--primary);
}
.rewrite-mode-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--primary-soft);
  border-radius: 999px;
  background: var(--primary-faint);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s var(--ease), border-color 0.15s var(--ease);
}
.rewrite-mode-chip:hover {
  border-color: var(--primary);
  background: var(--primary-soft);
}

/* 增强前后对比：左 = 原文（安静），右 = 增强结果（靛蓝强调），中间一支箭头 */
.enhance-modal-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.enhance-modal-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 21px;
  height: 21px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  line-height: 1;
}
.enhance-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.enhance-compare {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
}
.enhance-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
}
.enhance-col.before {
  background: var(--surface-soft);
  animation: enhance-col-left 0.34s var(--ease) both;
}
.enhance-col.after {
  border-color: var(--primary-soft);
  background: var(--panel-bg);
  box-shadow: 0 12px 30px -24px rgba(71, 83, 199, 0.5);
  animation: enhance-col-right 0.34s var(--ease) 0.05s both;
}
.enhance-col-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.enhance-col.after .enhance-col-head {
  border-bottom-color: var(--primary-soft);
  background: var(--primary-faint);
  color: var(--primary-hover);
}
.enhance-col-icon {
  color: var(--primary);
  font-size: 10px;
  line-height: 1;
}
/* 「可编辑」小标签：明确告诉用户这里不是只读结果 */
.enhance-editable {
  margin-left: auto;
  padding: 1px 7px;
  border: 1px solid var(--primary-soft);
  border-radius: 999px;
  background: var(--panel-bg);
  font-size: 10px;
  font-weight: 500;
  color: var(--primary-hover);
}
.enhance-text {
  max-height: 46vh;
  overflow: auto;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}
.enhance-col.after .enhance-text {
  color: var(--text);
}
/* 增强结果直接在原位置编辑：去掉 textarea 自带边框，沿用列卡片的边框 */
.enhance-editor {
  display: block;
  width: 100%;
  min-height: 220px;
  border: none;
  outline: none;
  background: transparent;
  font-family: inherit;
  resize: none;
}
.enhance-editor:focus-visible {
  outline: none;
}
.enhance-col.after:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.1);
}
.enhance-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  animation: arrow-fade 0.3s var(--ease) 0.12s both;
}
.enhance-arrow svg {
  width: 18px;
  height: 18px;
}
.enhance-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 640px) {
  .enhance-compare {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }
  /* 只转箭头本身，整行宽度保持正常，避免旋转后的元素撑出弹窗 */
  .enhance-arrow svg {
    transform: rotate(90deg);
  }
  .enhance-text {
    max-height: 32vh;
  }
  .enhance-editor {
    min-height: 140px;
  }
}

/* ---- 对话栏动效：新消息落下、折叠内容展开、弹窗内容分段出现 ---- */
@keyframes msg-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes block-reveal {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes diag-item-in {
  from {
    opacity: 0;
    transform: translateY(5px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes enhance-col-left {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes enhance-col-right {
  from {
    opacity: 0;
    transform: translateX(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes arrow-fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 0.6;
  }
}
</style>
