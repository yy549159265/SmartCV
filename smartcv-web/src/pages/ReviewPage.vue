<script setup lang="ts">
import { nextTick, ref, computed, watch } from 'vue'
import type { InputInst } from 'naive-ui'
import PreviewSection from '@/components/PreviewSection.vue'
import ResumeDiffDialog from '@/components/ResumeDiffDialog.vue'
import AskQuestionCard from '@/components/AskQuestionCard.vue'
import ReferenceExamplePicker from '@/components/ReferenceExamplePicker.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { useResumeStore } from '@/stores/resume'
import { useReviewStore, type ChatItem, type ChatStep } from '@/stores/review'
import { useStatsStore } from '@/stores/stats'
import type { ChatAnswer, DiagnosisItem, RewriteMode } from '@/api/chat'
import { checkResumeGrammar } from '@/api/grammar'
import { coordToTarget, diffResume } from '@/utils/resumeDiff'

const AGENT_STATUS: Record<string, { running: string; done: string }> = {
  diagnose: { running: '诊断简历中', done: '诊断完成' },
  review: { running: '审查中', done: '审查完成' },
  summarize: { running: '总结中', done: '总结完成' },
}

const DIAG_DISPOSITION_LABEL: Record<string, string> = {
  must: '必须修改',
  suggest: '建议修改',
  keep: '可以保留',
  insufficient: '信息不足',
}

const DIAG_STATUS_LABEL: Record<string, string> = {
  pending: '待分析',
  change: '待修改',
  skip: '不更改',
  done: '已修改',
  failed: '未执行',
}

const DIAG_STATUS_ORDER = ['change', 'done', 'skip', 'failed', 'pending'] as const

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

function diagPendingText(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const waiting = m.questions.some((q) => q.status === 'pending' || q.status === 'submitting')
  return waiting ? '等待你的回答' : '正在生成诊断结论'
}

function leadText(m: Extract<ChatItem, { kind: 'agent' }>, i: number): string {
  if (m.lead) return m.lead
  const prev = reviewStore.messages[i - 1]
  return m.agent === 'diagnose' && prev?.kind === 'status' ? prev.text : ''
}

function isMergedStatus(i: number): boolean {
  const next = reviewStore.messages[i + 1]
  return next?.kind === 'agent' && next.agent === 'diagnose'
}

function isNodeBodyOpen(m: Extract<ChatItem, { kind: 'agent' }>): boolean {
  return m.nodeOpen || m.questions.some((q) => q.status === 'pending' || q.status === 'submitting')
}

function showNodePreview(m: Extract<ChatItem, { kind: 'agent' }>): boolean {
  if (isNodeBodyOpen(m)) return false
  if (m.agent === 'diagnose' && (m.diagnosis.length > 0 || m.status === 'running')) return false
  return true
}

function nodePreview(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const text = (m.text ?? '').replace(/[#>*_`]/g, '').replace(/\s+/g, ' ').trim()
  if (m.agent === 'diagnose' && m.diagnosis.length) {
    return diagCounts(m.diagnosis)
      .map((c) => `${c.label} ${c.count}`)
      .join(' · ')
  }
  if (m.agent === 'review') {
    const parts: string[] = []
    if (m.status === 'done') parts.push(`确认修改 ${doneCount()} 处`)
    if (text) parts.push(text)
    return parts.join(' · ') || '正在逐条审查诊断…'
  }
  return text || statusText(m)
}

function isLastFlowNode(i: number): boolean {
  for (let j = i + 1; j < reviewStore.messages.length; j++) {
    const next = reviewStore.messages[j]
    if (next.kind === 'user') break
    if (next.kind === 'agent') return false
  }
  return true
}

function doneCount(): number {
  for (let i = reviewStore.messages.length - 1; i >= 0; i--) {
    const m = reviewStore.messages[i]
    if (m.kind === 'agent' && m.agent === 'diagnose' && m.diagnosis.length) {
      return m.diagnosis.filter((d) => d.status === 'done').length
    }
  }
  return 0
}

const diagShow = ref(false)
const diagDetail = ref<Extract<ChatItem, { kind: 'agent' }> | null>(null)
const diagListEl = ref<HTMLElement | null>(null)

function openDiagDetail(m: Extract<ChatItem, { kind: 'agent' }>) {
  diagDetail.value = m
  diagShow.value = true
}

function diagOwner(): Extract<ChatItem, { kind: 'agent' }> | null {
  for (let i = reviewStore.messages.length - 1; i >= 0; i--) {
    const m = reviewStore.messages[i]
    if (m.kind === 'agent' && m.agent === 'diagnose' && m.diagnosis.length) return m
  }
  return null
}

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
  order.sort((a, b) => {
    const ga = groups.get(a)!
    const gb = groups.get(b)!
    return ga.sectionIndex !== gb.sectionIndex ? ga.sectionIndex - gb.sectionIndex : a.localeCompare(b)
  })
  return order.map((k) => groups.get(k)!)
})

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

const diagFlashIndex = ref<number | null>(null)

function flashDiagCard(index: number) {
  diagFlashIndex.value = null
  void nextTick(() => {
    diagFlashIndex.value = index
    window.setTimeout(() => {
      if (diagFlashIndex.value === index) diagFlashIndex.value = null
    }, 2200)
  })
}

function onJumpToDiagnosis(index: number) {
  const owner = diagOwner()
  if (!owner) return
  openDiagDetail(owner)
  flashDiagCard(index)
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

const latestDiagnosis = computed<DiagnosisItem[]>(() => {
  if (reviewStore.pendingDiff?.source !== 'chat') return []
  return diagOwner()?.diagnosis ?? []
})

const diffKeyByDiagIndex = computed<ReadonlyMap<number, string>>(() => {
  const map = new Map<number, string>()
  const pending = reviewStore.pendingDiff
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

const diffFlash = ref<{ key: string; nonce: number } | null>(null)

function onJumpToDiff(index: number) {
  const key = diffKeyByDiagIndex.value.get(index)
  if (!key) return
  diagShow.value = false
  reviewStore.diffOpen = true
  diffFlash.value = { key, nonce: Date.now() }
}

function statusText(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const map = AGENT_STATUS[m.agent]
  if (!map) return m.label
  if (m.agent === 'diagnose' && m.status === 'done') {
    return m.diagnosis.length
      ? `${map.done} · 发现 ${m.diagnosis.length} 处问题`
      : `${map.done} · 未发现问题`
  }
  if (m.agent === 'review' && m.status === 'done') {
    return `${map.done} · 确认修改 ${doneCount()} 处`
  }
  return m.status === 'done' ? map.done : map.running
}

interface DisplayStep {
  kind: 'tool'
  tool: string
  args: string
  result?: string
}

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
      rows.push({ kind: 'tool', tool: st.tool, args: '', result: st.result })
      i++
    } else {
      i++
    }
  }
  return rows
}

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

const emit = defineEmits<{
  'open-library': []
  'convert-to-example': [json: string]
}>()

const resumeStore = useResumeStore()
const reviewStore = useReviewStore()
const statsStore = useStatsStore()
const documents = useDocumentsStore()

const measureFlowEl = ref<HTMLElement | null>(null)
usePagination(measureFlowEl)

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

const pageStyle = computed(() => ({
  width: `${pageWidth.value}px`,
  minHeight: `${pageHeight.value}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: previewZoom.value,
}))

const measureStyle = computed(() => ({ width: `${contentWidth.value}px` }))

const exportStyle = computed(() => ({ width: `${pageWidth.value}px` }))

const jsonMenuShow = ref(false)

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
  if (result === 'cancelled') return
  downloadJson(resumeStore.resume, `${resumeFilename()}.json`)
  await statsStore.inc('json')
}

function onDownloadJson() {
  jsonMenuShow.value = false
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  downloadJson(resumeStore.resume, `${resumeFilename()}.json`)
  void statsStore.inc('json')
}

function onConvertToExample() {
  jsonMenuShow.value = false
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  emit('convert-to-example', JSON.stringify(resumeStore.resume, null, 2))
}

const exporting = ref(false)

const exportFlowEl = ref<HTMLElement | null>(null)

async function onExportPdf() {
  if (resumeStore.resume.length === 0) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  if (documents.isBound) await documents.ensurePermission()
  exporting.value = true
  try {
    await nextTick()
    await new Promise((r) => setTimeout(r, 350))

    if (!exportFlowEl.value) throw new Error('没有可导出的内容')

    if (exportFlowEl.value.querySelector('.export-page') == null) {
      throw new Error('简历排版还没准备好，请稍后重试')
    }

    const blob = await fetchResumePdf(exportFlowEl.value)
    const filename = resumeFilename()
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

const jdExpanded = ref(false)

const draft = ref('')
const chatInputRef = ref<InputInst | null>(null)
const chatListEl = ref<HTMLElement | null>(null)
const settingsShow = ref(false)
const grammarRunning = ref(false)

async function onSend() {
  if (!draft.value.trim()) return
  if (grammarRunning.value) {
    message.warning('全文纠错进行中，请稍候')
    return
  }
  const text = draft.value
  draft.value = ''
  await reviewStore.send(text)
  await nextTick()
  chatListEl.value?.scrollTo({ top: chatListEl.value.scrollHeight, behavior: 'smooth' })
}

function onSubmitQuestion(questionId: string, answers: ChatAnswer[]) {
  void reviewStore.submitQuestionAnswers(questionId, answers)
}

watch(
  () =>
    reviewStore.messages.some(
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

const enhancing = ref(false)
const enhanceShow = ref(false)
const enhanceBefore = ref('')
const enhanceAfter = ref('')
const enhanceEditorEl = ref<HTMLTextAreaElement | null>(null)

const ENHANCE_DIRECTIONS = [
  '提炼亮点',
  '量化成果',
  '专业表达',
  '精简篇幅',
  '匹配岗位',
] as const
const enhanceDirection = ref('')

function toggleEnhanceDirection(direction: string) {
  enhanceDirection.value = enhanceDirection.value === direction ? '' : direction
}

async function onEnhancePrompt() {
  const text = draft.value.trim()
  if (enhancing.value || reviewStore.sending || grammarRunning.value) return
  if (!text) {
    message.warning('先输入修改要求再增强')
    return
  }
  settingsShow.value = false

  enhancing.value = true
  try {
    const description = enhanceDirection.value ? `增强方向：${enhanceDirection.value}` : ''
    const [enhanced] = await polishTexts([text], description, 'enhance', reviewStore.jd)
    const result = (enhanced ?? '').trim()
    if (!result) throw new Error('增强结果为空，请稍后重试')
    enhanceBefore.value = text
    enhanceAfter.value = result
    enhanceShow.value = true
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
        reviewStore.discardPendingDiff()
        finish(true)
      },
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

function onSetRewriteMode(mode: RewriteMode) {
  reviewStore.setRewriteMode(mode)
  settingsShow.value = false
}

async function onGrammarCheck() {
  settingsShow.value = false
  if (grammarRunning.value || reviewStore.sending) return
  if (!resumeStore.resume.length) {
    message.warning('简历还是空的，先去「编辑简历」页添加内容')
    return
  }
  if (reviewStore.pendingDiff) {
    if (!(await confirmDiscardPendingDiff())) return
  }

  const before = JSON.parse(JSON.stringify(resumeStore.resume)) as Section[]
  grammarRunning.value = true
  try {
    const result = await checkResumeGrammar(before)

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

    reviewStore.setPendingDiff(before, result.resume, 'grammar')
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

const sessionId = ref(getAgentSessionId())
const shortSessionId = computed(() => sessionId.value.slice(0, 8))

function onNewConversation() {
  reviewStore.clearMessages()
  sessionId.value = resetAgentSessionId()
  message.success('已清空会话，并新建会话 id')
}

const diffTitle = computed(() =>
  reviewStore.pendingDiff?.source === 'grammar' ? '全文纠错对比' : 'AI 修改对比',
)

function onApplyDiff() {
  const source = reviewStore.pendingDiff?.source
  const applied = reviewStore.applyPendingDiff()
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

function onDiscardDiff() {
  reviewStore.discardPendingDiff()
  message.info('已放弃本次修改，简历保持不变')
}
</script>

<template>
  <div ref="measureFlowEl" class="measure-flow" :style="measureStyle">
    <PreviewSection
      v-for="g in resumeStore.resume"
      :key="g.id"
      :section="g"
      :data-section-id="g.id"
      :data-forced="g.pageBreakBefore ? 'true' : undefined"
    />
  </div>

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

  <main class="review-page">
    <section class="resume-panel">
      <div class="panel-header">
        <span class="panel-title">当前简历</span>
        <span class="panel-hint">共 {{ resumeStore.resume.length }} 个章节 · {{ pages.length }} 页 · 只读</span>
        <span class="panel-spacer" />
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

    <section class="chat-panel">
      <div class="jd-section">
        <button class="jd-toggle" :class="{ open: jdExpanded }" @click="jdExpanded = !jdExpanded">
          <span class="jd-caret" aria-hidden="true"></span>
          <span class="jd-toggle-text">JD 职位描述（可选，有就粘贴）</span>
        </button>
        <div v-if="jdExpanded" class="jd-body">
          <n-input
            :value="reviewStore.jd"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 10 }"
            placeholder="把招聘 JD 粘贴到这里，AI 会参考它来提修改建议。没有 JD 可以不填。"
            @update:value="(v: string) => reviewStore.setJd(v)"
          />
        </div>
      </div>

      <ReferenceExamplePicker
        :selected="reviewStore.referenceIds"
        @update:selected="reviewStore.setReferenceIds"
        @open-library="emit('open-library')"
      />

      <div class="chat-header">
        <span class="chat-heading">
          <span class="chat-heading-icon" aria-hidden="true">✦</span>
          <span class="panel-title">简历修改对话</span>
        </span>
        <span class="panel-spacer" />
        <div class="chat-actions">
          <button
            v-if="reviewStore.rewriteMode === 'bold'"
            class="rewrite-mode-chip"
            title="当前为大胆优化，点此切换"
            @click="settingsShow = true"
          >
            大胆优化
          </button>
          <n-button
            v-if="reviewStore.pendingDiff"
            size="tiny"
            type="primary"
            ghost
            @click="reviewStore.openDiff()"
          >
            查看修改对比
          </n-button>
          <span
            class="session-id"
            :title="`会话 id：${sessionId}（诊断 / 审查 / 摘要等 agent 共用）`"
          >
            会话 {{ shortSessionId }}
          </span>
          <n-button
            size="tiny"
            quaternary
            :disabled="reviewStore.sending"
            @click="onNewConversation"
          >
            新建会话
          </n-button>
        </div>
      </div>

      <div ref="chatListEl" class="chat-list">
        <div v-if="reviewStore.messages.length === 0" class="chat-empty">
          <span class="chat-empty-icon" aria-hidden="true">✦</span>
          <p class="chat-empty-title">描述你想怎么改这份简历，例如：</p>
          <div class="chat-empty-examples">
            <span>「把工作经历写得更量化一点」</span>
            <span>「帮我把自我评价改得简洁有力」</span>
          </div>
        </div>

        <div
          v-for="(m, i) in reviewStore.messages"
          :key="i"
          class="chat-msg"
          :class="{ 'from-user': m.kind === 'user' }"
        >
          <div v-if="m.kind === 'user'" class="msg-block from-user">
            <div class="bubble">{{ m.text }}</div>
          </div>

          <div v-else-if="m.kind === 'error'" class="msg-block from-ai">
            <div class="bubble error">{{ m.text }}</div>
          </div>

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

          <div v-else class="msg-block from-process">
            <div class="flow-node" :class="[m.status, { 'is-last': isLastFlowNode(i) }]">
              <div class="flow-rail" aria-hidden="true">
                <span class="flow-marker">
                  <span v-if="m.status === 'done'" class="check"><IconGlyph name="check" :size="11" /></span>
                  <span v-else class="pulse"></span>
                </span>
                <span class="flow-line"></span>
                <span class="flow-arrow"></span>
              </div>

              <div class="flow-card">
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

                <div
                  v-if="m.agent === 'diagnose' && m.status === 'running' && !m.diagnosis.length"
                  class="diag-pending"
                >
                  <span class="diag-pending-icon" aria-hidden="true"><IconGlyph name="scan-line" :size="12" /></span>
                  <span class="diag-pending-text">{{ diagPendingText(m) }}</span>
                  <span class="diag-pending-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                </div>

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

                <div v-if="showNodePreview(m)" class="flow-preview">
                  <span>{{ nodePreview(m) }}</span>
                </div>

                <div v-if="isNodeBodyOpen(m)" class="agent-body">
                  <div v-if="leadText(m, i)" class="agent-lead">{{ leadText(m, i) }}</div>
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

                <div v-if="m.references.length" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.examplesOpen = !m.examplesOpen">
                    <span class="chevron" :class="{ open: m.examplesOpen }" aria-hidden="true"></span>
                    <span>优秀示例</span>
                    <span class="field-tip">
                      <span class="field-hint">
                        {{ m.references.length }} 份{{ m.styleNotes.length ? ` · ${m.styleNotes.length} 条规范` : '' }}
                      </span>
                      <span class="tip-bubble">
                        诊断时参考的他人简历：只借写作方式与结构，事实仍来自你的简历；提炼出的写作规范会交给审查 agent 执行
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

                <div v-if="toolRows(m.steps).length" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.toolsOpen = !m.toolsOpen">
                    <span class="chevron" :class="{ open: m.toolsOpen }" aria-hidden="true"></span>
                    <span>工具调用</span>
                    <span class="field-tip">
                      <span class="field-hint">{{ toolRows(m.steps).length }} 次</span>
                      <span class="tip-bubble">该 agent 实际调用的工具，如 patch_content 逐条审查并执行修改</span>
                    </span>
                  </button>
                  <div v-if="m.toolsOpen" class="steps">
                    <div v-for="(row, si) in toolRows(m.steps)" :key="si" class="step" :class="row.kind">
                      <div class="tool-line"><span class="tool-name">调用工具 {{ row.tool }}</span><span class="tool-args">{{ row.args }}</span></div>
                      <div v-if="row.result" class="tool-result">↳ {{ row.result }}</div>
                    </div>
                  </div>
                </div>

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

      <div v-if="enhancing" class="enhance-loading">
        <n-spin :size="12" />
        <span>正在增强提示词…</span>
      </div>
      <div v-if="grammarRunning" class="enhance-loading">
        <n-spin :size="12" />
        <span>正在检查全文语法与拼写…</span>
      </div>

      <div class="chat-input">
        <n-input
          ref="chatInputRef"
          v-model:value="draft"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入修改要求，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="onSend"
        />
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
                :disabled="reviewStore.sending || grammarRunning"
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
                      reviewStore.pendingDiff
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
                :disabled="reviewStore.sending || enhancing || grammarRunning"
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

              <div class="composer-menu-label enhance-directions-label">
                增强方向（可选，不选 = 通用）
              </div>
              <div class="enhance-directions" role="group" aria-label="增强方向">
                <button
                  v-for="direction in ENHANCE_DIRECTIONS"
                  :key="direction"
                  type="button"
                  class="enhance-direction"
                  :class="{ active: enhanceDirection === direction }"
                  :aria-pressed="enhanceDirection === direction"
                  :disabled="reviewStore.sending || enhancing || grammarRunning"
                  @click="toggleEnhanceDirection(direction)"
                >
                  {{ direction }}
                </button>
              </div>
            </div>

            <div class="composer-menu-divider" />

            <div class="composer-menu-group">
              <div class="composer-menu-label">优化强度</div>
              <div class="mode-options" role="radiogroup" aria-label="优化强度">
                <button
                  type="button"
                  role="menuitemradio"
                  class="mode-option"
                  :class="{ active: reviewStore.rewriteMode === 'standard' }"
                  :aria-checked="reviewStore.rewriteMode === 'standard'"
                  @click="onSetRewriteMode('standard')"
                >
                  <span class="mode-radio" aria-hidden="true" />
                  <span class="mode-copy">
                    <span class="mode-name">标准</span>
                    <span class="mode-desc">保留原句式，只做必要改写</span>
                  </span>
                  <IconGlyph
                    v-if="reviewStore.rewriteMode === 'standard'"
                    class="mode-check"
                    name="check"
                    :size="14"
                  />
                </button>
                <button
                  type="button"
                  role="menuitemradio"
                  class="mode-option"
                  :class="{ active: reviewStore.rewriteMode === 'bold' }"
                  :aria-checked="reviewStore.rewriteMode === 'bold'"
                  @click="onSetRewriteMode('bold')"
                >
                  <span class="mode-radio" aria-hidden="true" />
                  <span class="mode-copy">
                    <span class="mode-name">大胆</span>
                    <span class="mode-desc">可大幅重写表达，不新增事实、不改结构</span>
                  </span>
                  <IconGlyph
                    v-if="reviewStore.rewriteMode === 'bold'"
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
          :disabled="reviewStore.sending || grammarRunning"
          @click="onSend"
        >
          发送
        </n-button>
      </div>
    </section>
  </main>

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
                <span class="diag-help-sub">审查阶段</span>
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

  <ResumeDiffDialog
    :show="reviewStore.diffOpen && !!reviewStore.pendingDiff"
    :title="diffTitle"
    :before="reviewStore.pendingDiff?.before ?? []"
    :after="reviewStore.pendingDiff?.after ?? []"
    :reverted="reviewStore.pendingDiff?.reverted ?? []"
    :diagnosis="latestDiagnosis"
    :flash="diffFlash"
    @update:show="(v: boolean) => { if (!v) reviewStore.dismissDiff() }"
    @toggle="(key: string) => reviewStore.toggleDiffChange(key)"
    @revert-all="reviewStore.revertAllDiff()"
    @accept-all="reviewStore.acceptAllDiff()"
    @jump-diagnosis="onJumpToDiagnosis"
    @apply="onApplyDiff"
    @discard="onDiscardDiff"
  />

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
.review-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--app-bg);
}

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

.measure-flow {
  position: absolute;
  top: 0;
  left: -9999px;
  visibility: hidden;
}
.export-pages {
  position: fixed;
  top: 0;
  left: -9999px;
}
.export-flow {
  box-sizing: border-box;
  background: #fff;
}
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
  background: var(--doc-workspace);
}
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
.msg-block.from-process {
  width: 100%;
  max-width: 100%;
}
.agent-lead {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-tertiary);
  line-height: 1.6;
}
.from-process {
  justify-content: flex-start;
}
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
.flow-line {
  position: absolute;
  left: 50%;
  top: 25px;
  bottom: -14px;
  width: 1px;
  margin-left: -0.5px;
  background: var(--border-strong);
}
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
.flow-preview {
  min-width: 0;
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
.agent-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.agent-block + .agent-block {
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
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
.agent-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 11px;
}
.diag-entry + .agent-body,
.diag-pending + .agent-body {
  padding-top: 0;
}
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
.agent-think {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-top: 1px solid var(--border);
  padding-top: 6px;
}
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
.diag-head-right {
  flex: none;
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}
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
.diag-state-value.st-change {
  color: var(--warning);
}
.diag-state-value.st-done {
  color: var(--success);
}
.diag-state-value.st-failed {
  color: var(--danger);
}
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
.question-archive {
  margin-top: 4px;
}
.flow-card :deep(.ask-card) {
  box-shadow: none;
}
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
.enhance-loading + .chat-input {
  border-top: none;
}

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
.enhance-directions-label {
  padding-top: 6px;
  padding-bottom: 4px;
}
.enhance-directions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 10px 6px;
}
.enhance-direction {
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel-bg);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 0.15s var(--ease),
    border-color 0.15s var(--ease),
    color 0.15s var(--ease);
}
.enhance-direction:not(:disabled):hover {
  border-color: var(--primary-soft);
  color: var(--primary);
}
.enhance-direction.active {
  border-color: var(--primary);
  background: var(--primary-faint);
  color: var(--primary);
  font-weight: 600;
}
.enhance-direction:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
