<script setup lang="ts">
/**
 * 页面 2 · 优化简历（AI 辅助修改）
 *
 * 布局：
 *  - 左侧：当前简历的只读渲染（连续流，与预览同款组件）；
 *  - 右侧：JD 输入（可选，有 JD 就粘贴，没有就不填）+ AI 对话栏。
 *
 * 对话走 SSE 流式（见 src/api/chat.ts）：诊断"思考"正文 + steps 执行过程 +
 * 摘要"修改说明"气泡；供应商配置在「供应商设置」页（localStorage 保存）。
 */
import { nextTick, ref, computed, watch } from 'vue'
import type { InputInst } from 'naive-ui'
import PreviewSection from '@/components/PreviewSection.vue'
import ResumeDiffDialog from '@/components/ResumeDiffDialog.vue'
import AskQuestionCard from '@/components/AskQuestionCard.vue'
import { useResumeStore } from '@/stores/resume'
import { useOptimizeStore, type ChatItem, type ChatStep } from '@/stores/optimize'
import { useStatsStore } from '@/stores/stats'
import type { ChatAnswer } from '@/api/chat'

/** 各 agent 生命周期的友好文案：running（进行中）/ done（完成） */
const AGENT_STATUS: Record<string, { running: string; done: string }> = {
  diagnose: { running: '诊断简历中', done: '诊断完成' },
  optimize: { running: '优化简历中', done: '优化完成' },
  summarize: { running: '总结中', done: '总结完成' },
}

/** 取出 agent 块当前应该显示的状态文案 */
function statusText(m: Extract<ChatItem, { kind: 'agent' }>): string {
  const map = AGENT_STATUS[m.agent]
  if (!map) return m.label
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
import { usePagination } from '@/composables/usePagination'
import { previewZoom, ZOOM_LEVELS } from '@/composables/usePreviewZoom'
import { CONTENT_WIDTH, PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'
import { pageRunSpecs, type PageUnit, type RunSpec } from '@/utils/pagination'
import { exportResumePdf } from '@/api/pdf'
import { polishTexts } from '@/api/polish'
import type { Section } from '@/types'
import { downloadJson } from '@/utils/download'
import { renderMarkdown } from '@/utils/markdown'
import { message } from '@/utils/feedback'
import { getAgentSessionId, resetAgentSessionId } from '@/api/session'

const resumeStore = useResumeStore()
const optimizeStore = useOptimizeStore()
const statsStore = useStatsStore()

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
 * 分页 A4 纸样式：和「实时预览」的 A4 纸张保持完全一致 ——
 * 同样的纸宽 / 最小高 / 页边距 / 缩放，这样两边显示的字号、换行、分页完全一样，
 * 不会出现"优化简历页看起来更大/不分页"的问题。
 */
const pageStyle = computed(() => ({
  width: `${PAGE_WIDTH}px`,
  minHeight: `${PAGE_HEIGHT}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: previewZoom.value,
}))

/* ---------- 导出 ---------- */

/** 导出 JSON：下载当前简历数据文件（下载成功后计数 +1） */
function onExportJson() {
  downloadJson(resumeStore.resume, 'smartcv-resume.json')
  statsStore.inc('json')
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

    await exportResumePdf(exportFlowEl.value)
    await statsStore.inc('pdf')
    message.success('PDF 已导出（后端生成，与预览一致）')
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

async function onSend() {
  const text = draft.value
  draft.value = ''
  if (!text.trim()) return
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
  () => optimizeStore.messages.some((m) => m.kind === 'question' && m.status === 'pending'),
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

/**
 * 把输入框里的口语化要求发给后端改写成更明确、可执行的提示词。
 * 复用 /api/polish（mode='enhance'），已填的 JD 作为参考材料一起传。
 * 不直接覆盖输入框：先弹窗对比，用户点「确定」才写回。
 */
async function onEnhancePrompt() {
  const text = draft.value.trim()
  if (enhancing.value || optimizeStore.sending) return
  if (!text) {
    message.warning('先输入修改要求再增强')
    return
  }

  enhancing.value = true
  try {
    const [enhanced] = await polishTexts([text], '', 'enhance', optimizeStore.jd)
    const result = (enhanced ?? '').trim()
    if (!result) throw new Error('增强结果为空，请稍后重试')
    enhanceBefore.value = text
    enhanceAfter.value = result
    enhanceShow.value = true
  } catch (e) {
    message.error(e instanceof Error ? e.message : '提示词增强失败')
  } finally {
    enhancing.value = false
  }
}

/** 确认采用增强结果：写回输入框，光标移到末尾 */
function onApplyEnhance() {
  draft.value = enhanceAfter.value
  enhanceShow.value = false
  nextTick(() => chatInputRef.value?.focus())
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

/**
 * 应用对比弹窗里的修改：这时候才真正把（逐处筛选过的）结果写回 store。
 * importResume 会重生成 id 并整体替换，同时被 main.ts 的 $onAction 记一次撤销快照，
 * 所以提示里告诉用户可以 Ctrl+Z 撤回。
 * 全部还原时 store 不会写回，提示也换成"简历未改动"。
 */
function onApplyDiff() {
  const applied = optimizeStore.applyPendingDiff()
  if (applied) message.success('已应用 AI 修改，可用 Ctrl+Z 撤销')
  else message.info('所有改动都已还原，简历保持不变')
}
</script>

<template>
  <!-- 隐藏测量层：始终挂载，连续渲染全部章节用于算分页（与预览同宽，页数才能一致） -->
  <div ref="measureFlowEl" class="measure-flow" :style="{ width: `${CONTENT_WIDTH}px` }">
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
    <div ref="exportFlowEl" class="export-flow" :style="{ width: `${PAGE_WIDTH}px` }">
      <div
        v-for="(page, i) in pages"
        :key="i"
        class="export-page"
        :style="{
          height: `${PAGE_HEIGHT}px`,
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
        <!-- 导出：JSON 文件 / PDF（文字版，浏览器打印 → 另存为 PDF） -->
        <n-button size="small" quaternary @click="onExportJson">导出 JSON</n-button>
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
        <button class="jd-toggle" @click="jdExpanded = !jdExpanded">
          <span>{{ jdExpanded ? '▾' : '▸' }}</span>
          JD 职位描述（可选，有就粘贴）
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

      <!-- 对话栏 -->
      <div class="chat-header">
        <span class="panel-title">简历修改对话</span>
        <span class="panel-spacer" />
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

      <div ref="chatListEl" class="chat-list">
        <!-- 空状态 -->
        <div v-if="optimizeStore.messages.length === 0" class="chat-empty">
          描述你想怎么改这份简历，例如：<br />
          「把工作经历写得更量化一点」「帮我把自我评价改得简洁有力」
        </div>

        <!-- 时间线：用户消息 / 过程 agent 块 / 摘要回答气泡 -->
        <div
          v-for="(m, i) in optimizeStore.messages"
          :key="i"
          class="chat-msg"
          :class="{ 'from-user': m.kind === 'user', 'question-msg': m.kind === 'question' }"
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
          <div v-else-if="m.kind === 'status'" class="msg-block from-process">
            <div class="status-line" :class="{ done: m.done }">
              <span class="status-mark">
                <span v-if="m.done" class="check">✓</span>
                <span v-else class="pulse"></span>
              </span>
              <span class="status-line-text">{{ m.text }}</span>
            </div>
          </div>

          <!-- 诊断 agent 反问：暂停等待用户选择；提交后原 SSE 流继续 -->
          <div v-else-if="m.kind === 'question'" class="msg-block from-process">
            <AskQuestionCard :item="m" @submit="onSubmitQuestion" />
          </div>

          <!-- agent 块：诊断 / 优化 / 摘要统一卡片，状态头 + 回答(常显) + 思考/工具(各自折叠) -->
          <div v-else class="msg-block from-process">
            <div class="agent-card">
              <!-- 状态头：running = 绿色闪烁帧，done = 绿色对勾 -->
              <div class="agent-status" :class="m.status">
                <span class="status-mark">
                  <span v-if="m.status === 'done'" class="check">✓</span>
                  <span v-else class="pulse"></span>
                </span>
                <span class="status-text">{{ statusText(m) }}</span>
              </div>

              <div class="agent-body">
                <!-- 💭 思考过程：模型 reasoning_content 字段，折叠；模型没返回思考则给提示 -->
                <div class="agent-block">
                  <button class="agent-sub-toggle" @click="m.thinkingOpen = !m.thinkingOpen">
                    <span class="chevron">{{ m.thinkingOpen ? '▾' : '▸' }}</span>
                    <span>思考过程</span>
                    <span class="field-tip">
                      <span class="field-hint">reasoning_content</span>
                      <span class="tip-bubble">思考参考模型的 reasoning_content 字段；模型没返回这个字段，就是没有思考过程</span>
                    </span>
                  </button>
                  <div v-if="m.thinkingOpen && m.thinking" class="agent-think">{{ m.thinking }}</div>
                </div>

                <!-- 🔧 工具调用：折叠 -->
                <div v-if="m.steps.length" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.toolsOpen = !m.toolsOpen">
                    <span class="chevron">{{ m.toolsOpen ? '▾' : '▸' }}</span>
                    <span>工具调用</span>
                    <span class="field-tip">
                      <span class="field-hint">{{ m.steps.length }} 次</span>
                      <span class="tip-bubble">该 agent 实际调用的工具，如 patch_content 按坐标就地改简历</span>
                    </span>
                  </button>
                  <div v-if="m.toolsOpen" class="steps">
                    <div v-for="(row, si) in groupSteps(m.steps)" :key="si" class="step" :class="row.kind">
                      <div class="tool-line"><span class="tool-name">调用工具 {{ row.tool }}</span><span class="tool-args">{{ row.args }}</span></div>
                      <div v-if="row.result" class="tool-result">↳ {{ row.result }}</div>
                    </div>
                  </div>
                </div>

                <!-- 💬 回答：模型 content 字段，折叠；内容按 Markdown 渲染 -->
                <div v-if="m.text" class="agent-block">
                  <button class="agent-sub-toggle" @click="m.answerOpen = !m.answerOpen">
                    <span class="chevron">{{ m.answerOpen ? '▾' : '▸' }}</span>
                    <span>回答</span>
                  </button>
                  <div v-if="m.answerOpen" class="agent-answer" v-html="renderMarkdown(m.text)"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 增强中：在输入区上方就地提示，不走全局 toast（否则会飘到页面顶部） -->
      <div v-if="enhancing" class="enhance-loading">
        <n-spin :size="12" />
        <span>正在增强提示词…</span>
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
        <!-- 提示词增强：把口语化要求改写成更明确的提示词（悬停显示说明） -->
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              class="enhance-btn"
              quaternary
              size="small"
              :disabled="optimizeStore.sending || enhancing"
              :loading="enhancing"
              aria-label="提示词增强"
              @click="onEnhancePrompt"
            >
              <svg v-if="!enhancing" class="enhance-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 2.5l1.7 4.8L18.5 9l-4.8 1.7L12 15.5l-1.7-4.8L5.5 9l4.8-1.7L12 2.5z" fill="currentColor" />
                <path d="M19 14l.9 2.1 2.1.9-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14z" fill="currentColor" />
              </svg>
            </n-button>
          </template>
          提示词增强
        </n-tooltip>
        <n-button
          type="primary"
          size="small"
          :disabled="optimizeStore.sending"
          @click="onSend"
        >
          发送
        </n-button>
      </div>
    </section>
  </main>

  <!-- AI 修改对比弹窗：后端返回改好的简历后自动弹出；
       每处可单独 ← 还原 / → 恢复，点「确定应用」才把结果写回简历 -->
  <ResumeDiffDialog
    :show="optimizeStore.diffOpen && !!optimizeStore.pendingDiff"
    :before="optimizeStore.pendingDiff?.before ?? []"
    :after="optimizeStore.pendingDiff?.after ?? []"
    :reverted="optimizeStore.pendingDiff?.reverted ?? []"
    @update:show="(v: boolean) => { if (!v) optimizeStore.dismissDiff() }"
    @toggle="(key: string) => optimizeStore.toggleDiffChange(key)"
    @revert-all="optimizeStore.revertAllDiff()"
    @accept-all="optimizeStore.acceptAllDiff()"
    @apply="onApplyDiff"
  />

  <!-- 提示词增强对比：确认后才写回输入框，取消则保持原样 -->
  <n-modal
    v-model:show="enhanceShow"
    display-directive="if"
    preset="card"
    title="提示词增强"
    style="width: 900px; max-width: 94vw"
  >
    <div class="enhance-compare">
      <div class="enhance-col">
        <div class="enhance-col-head">增强前</div>
        <div class="enhance-text">{{ enhanceBefore }}</div>
      </div>
      <div class="enhance-col">
        <div class="enhance-col-head">增强后</div>
        <div class="enhance-text">{{ enhanceAfter }}</div>
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
/* 每一页是一个 A4 纸块：纸宽、四周留白由 inline style 提供，
   固定高度 + overflow hidden + break-inside avoid + break-after 独占一页，
   确保 Chromium 打 PDF 时把"一页的块"当成一整页，绝不硬拆成两页；
   块比物理页多出来的零点几像素（取整测量误差）被裁掉，而不是多出一页。
   高度由 inline style 固定为 PAGE_HEIGHT，配合 @page size 与纸面一致 */
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
  padding: 16px;
}
/* 与「实时预览」同款分页：一张张 A4 纸 + 页间距 + 页码 */
.page-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  padding-bottom: 24px;
}
.a4-page {
  position: relative;
  background: #fff;
  box-shadow: var(--shadow-paper);
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
}
.jd-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 10px 16px;
  border: none;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease), color 0.14s var(--ease);
}
.jd-toggle:hover {
  background: var(--surface-soft);
  color: var(--text);
}
.jd-body {
  padding: 0 16px 12px;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}
.session-id {
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--text-tertiary);
  white-space: nowrap;
  cursor: help;
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
  max-width: 360px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12.5px;
  line-height: 1.9;
}
.chat-msg {
  display: flex;
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
/* 反问卡片是表单，占满对话栏宽度更好操作 */
.chat-msg.question-msg .msg-block {
  width: 100%;
  max-width: 100%;
}
/* 过程 agent（诊断/优化）：可折叠卡片，默认收起 */
.from-process {
  justify-content: flex-start;
}
.agent-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 100%;
  min-width: 0;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 6px 10px;
}
/* 状态头：running 主题色柔光呼吸 / done 主题色对勾 */
.agent-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  max-width: 100%;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: var(--primary-soft);
  color: var(--primary-hover);
  cursor: default;
  user-select: none;
}
.agent-status.running {
  /* 柔光呼吸：背景 + 圆点一起明暗变化，跑到哪个 agent 一眼可见 */
  animation: status-blink 1.2s ease-in-out infinite;
}
.agent-status.done {
  background: var(--primary-soft);
  cursor: default;
}
.status-text {
  white-space: nowrap;
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
  color: var(--primary);
  font-weight: 700;
  line-height: 1;
}
.status-mark .pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  animation: dot-pulse 1.2s ease-in-out infinite;
}
@keyframes status-blink {
  0%,
  100% {
    background: var(--primary-soft);
    box-shadow: 0 0 0 0 rgba(75, 107, 94, 0);
  }
  50% {
    background: var(--primary-faint);
    box-shadow: 0 0 0 4px rgba(75, 107, 94, 0.16);
  }
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
.chevron {
  font-size: 9px;
  color: var(--text-tertiary);
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
  background: var(--primary-soft);
  color: var(--primary-hover);
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
.agent-block + .agent-block {
  border-top: 1px solid var(--border);
  padding-top: 6px;
}
/* 思考/工具的折叠开关行（标题可点） */
.agent-sub-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  cursor: pointer;
}
.agent-sub-toggle:hover {
  color: var(--text-secondary);
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
  border-radius: 6px;
  background: var(--surface-soft);
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
  transition: opacity 0.15s ease, visibility 0.15s ease;
  pointer-events: none;
}
.field-tip:hover .tip-bubble {
  opacity: 1;
  visibility: visible;
}
.agent-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
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
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}
.chat-input :deep(.n-input) {
  flex: 1;
}

/* ---- 提示词增强 ---- */
.enhance-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.enhance-btn {
  align-self: flex-end;
  color: var(--text-secondary);
}
.enhance-icon {
  width: 18px;
  height: 18px;
}
.enhance-compare {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.enhance-col {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-soft);
}
.enhance-col-head {
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.enhance-text {
  max-height: 48vh;
  overflow: auto;
  padding: 12px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.enhance-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
