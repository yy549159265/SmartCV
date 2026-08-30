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
import { nextTick, ref, computed } from 'vue'
import PreviewSection from '@/components/PreviewSection.vue'
import { useResumeStore } from '@/stores/resume'
import { useOptimizeStore, type ChatItem, type ChatStep } from '@/stores/optimize'

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
import type { Section } from '@/types'
import { downloadJson } from '@/utils/download'
import { message } from '@/utils/feedback'

const resumeStore = useResumeStore()
const optimizeStore = useOptimizeStore()

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

/** 导出 JSON：下载当前简历数据文件 */
function onExportJson() {
  downloadJson(resumeStore.resume, 'smartcv-resume.json')
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

function onClearChat() {
  optimizeStore.clearMessages()
  message.success('对话已清空')
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
          minHeight: `${PAGE_HEIGHT}px`,
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
        <span class="panel-title">📄 当前简历</span>
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
        <span class="panel-title">💬 简历修改对话</span>
        <n-button
          v-if="optimizeStore.messages.length > 0"
          size="tiny"
          quaternary
          @click="onClearChat"
        >
          清空对话
        </n-button>
      </div>

      <div ref="chatListEl" class="chat-list">
        <!-- 空状态 -->
        <div v-if="optimizeStore.messages.length === 0" class="chat-empty">
          👋 描述你想怎么改这份简历，例如：<br />
          「把工作经历写得更量化一点」「帮我把自我评价改得简洁有力」
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
          <div v-else-if="m.kind === 'status'" class="msg-block from-process">
            <div class="status-line" :class="{ done: m.done }">
              <span class="status-mark">
                <span v-if="m.done" class="check">✓</span>
                <span v-else class="pulse"></span>
              </span>
              <span class="status-line-text">{{ m.text }}</span>
            </div>
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
                    <span>💭 思考过程</span>
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
                    <span>🔧 工具调用</span>
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

                <!-- 💬 回答：模型 content 字段，常显不折叠 -->
                <div v-if="m.text" class="agent-block">
                  <div class="agent-block-title">💬 回答</div>
                  <div class="agent-think">{{ m.text }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="chat-input">
        <n-input
          v-model:value="draft"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          placeholder="输入修改要求，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="onSend"
        />
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
</template>

<style scoped>
.optimize-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  padding: 12px;
  background: #eef0f4;
}

/* ---- 左：简历渲染 ---- */
.resume-panel {
  flex: 1 1 55%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
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
   靠 min-height 撑满一整页 + break-after 独占一页，避免 Chromium 重新排版 */
.export-page {
  box-sizing: border-box;
  width: 100%;
  background: #fff;
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
  font-size: 14px;
}
.panel-hint {
  font-size: 12px;
  color: #9ca3af;
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
  box-shadow:
    0 1px 3px rgba(15, 23, 42, 0.08),
    0 8px 24px rgba(15, 23, 42, 0.1);
  /* 宽度 / 最小高 / 内边距 / 缩放由 pageStyle 动态设置（与实时预览的 A4 纸张一致） */
}
.page-number {
  position: absolute;
  bottom: 12px;
  right: 16px;
  font-size: 11px;
  color: #9ca3af;
  pointer-events: none;
}
.resume-empty {
  padding: 60px 0;
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
}

/* ---- 右：JD + 对话 ---- */
.chat-panel {
  flex: 1 1 45%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.jd-section {
  border-bottom: 1px solid #f0f1f4;
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
  color: #374151;
  text-align: left;
  cursor: pointer;
}
.jd-toggle:hover {
  background: #f7f9fc;
}
.jd-body {
  padding: 0 16px 12px;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #f0f1f4;
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
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
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
  background: #f8fafc;
  border: 1px solid #eef0f4;
  border-radius: 10px;
  padding: 6px 10px;
}
/* 状态头：running 绿色闪烁帧 / done 绿色对勾 */
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
  background: #dcfce7;
  color: #166534;
  cursor: default;
  user-select: none;
}
.agent-status.running {
  /* 绿色闪动：背景 + 圆点一起明显闪烁，跑到哪个 agent 一眼可见 */
  animation: status-blink 1s ease-in-out infinite;
}
.agent-status.done {
  background: #d1fae5;
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
  color: #15803d;
  font-weight: 700;
  line-height: 1;
}
.status-mark .pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #16a34a;
  animation: dot-pulse 1s ease-in-out infinite;
}
@keyframes status-blink {
  0%,
  100% {
    background: #dcfce7;
    box-shadow: 0 0 0 0 rgba(22, 163, 74, 0);
  }
  50% {
    background: #86efac;
    box-shadow: 0 0 0 4px rgba(22, 163, 74, 0.28);
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
  color: #6b7280;
}
/* 阶段状态行：convert 等非 agent 阶段（灰 pending → 绿色 todo check） */
.status-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  background: #f1f5f9;
  color: #64748b;
}
.status-line.done {
  background: #dcfce7;
  color: #166534;
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
  border-top: 1px solid #eef0f4;
  padding-top: 6px;
}
.agent-block-title {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  display: flex;
  align-items: center;
  gap: 5px;
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
  color: #9ca3af;
  cursor: pointer;
}
.agent-sub-toggle:hover {
  color: #6b7280;
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
  background: #f1f5f9;
  color: #94a3b8;
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
  background: #1f2937;
  color: #f9fafb;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
  white-space: normal;
  text-align: left;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);
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
  color: #374151;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-top: 1px dashed #eef0f4;
  padding-top: 6px;
}
.steps {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  line-height: 1.55;
  color: #9ca3af;
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
  color: #c0c6cf;
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
  background: #f1f3f7;
  color: #1f2937;
  border-bottom-left-radius: 4px;
}
.bubble.typing {
  color: #9ca3af;
  font-style: italic;
}
.bubble.error {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.chat-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid #f0f1f4;
}
.chat-input :deep(.n-input) {
  flex: 1;
}
</style>
