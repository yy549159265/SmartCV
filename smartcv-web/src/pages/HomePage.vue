<script setup lang="ts">
/**
 * 主页：简历的唯一入口。
 * 四种方式开始编辑：
 *   1. 导入 PDF / Word —— 后端解析成简历 JSON（api/document.ts）；
 *   2. 导入 JSON —— 读取本地 .json 简历文件；
 *   3. 新建 —— 空白简历；
 *   4. 加载示例 —— 从仓库 example/ 目录挑一份现成的（见 ExampleGallery.vue）。
 * 任一种完成后 emit('enter')，由 App.vue 切到编辑页展示/编辑。
 *
 * 页面结构：Hero（左文案 + 右真实渲染的 A4 演示简历）→ 三步流程 → 继续编辑 → 页脚。
 * Hero 右侧的演示简历是纯展示数据（data/heroResume.ts），直接走预览渲染链。
 */
import { computed, onMounted, ref } from 'vue'
import { useElementSize, useStorage, useWindowSize } from '@vueuse/core'
import { useResumeStore } from '@/stores/resume'
import { useStatsStore } from '@/stores/stats'
import { parseResumeFile, type ParseProgress, type ParseStep } from '@/api/document'
import { message } from '@/utils/feedback'
import { PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'
import ExampleGallery from '@/components/ExampleGallery.vue'
import PreviewSection from '@/components/PreviewSection.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { heroResume } from '@/data/heroResume'

const store = useResumeStore()
const statsStore = useStatsStore()

/** 打开主页时拉一次导出统计（失败静默，不打扰） */
onMounted(() => {
  statsStore.load()
})
const emit = defineEmits<{ enter: [] }>()

/** 当前是否已有简历（用于提示可直接继续编辑） */
const hasResume = () => store.resume.length > 0

/* ---------- Hero 右侧：A4 演示简历 ---------- */

/** 视口宽度（setup 作用域只创建一次，computed 里只读它的值） */
const { width: viewportWidth } = useWindowSize()

/** 视口宽度 → 演示简历的缩放档（纸宽 794px，缩到右栏能舒服地放下） */
const heroZoom = computed(() => {
  if (viewportWidth.value >= 1100) return 0.55
  if (viewportWidth.value >= 900) return 0.47
  return 0.42
})

/** A4 纸张样式：固定 A4 尺寸 + 页边距 + 缩放（与预览/画廊同一套技术） */
const paperStyle = computed(() => ({
  width: `${PAGE_WIDTH}px`,
  minHeight: `${PAGE_HEIGHT}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: heroZoom.value,
}))

/** 裁切容器高度：只露到一页的 78%，底部渐变暗示「下面还有内容」 */
const paperWrapStyle = computed(() => ({
  height: `${Math.round(PAGE_HEIGHT * heroZoom.value * 0.78)}px`,
}))

/* ---------- 组件库功能介绍：编辑器缩略图（固定设计尺寸 + 等比缩放） ---------- */

/** 缩略图设计尺寸：mock 按 560 × 400 绘制，标注用像素级锚点。
 * 宽度取 560 是为了在两栏布局（视觉列约 550px）下标签也能以接近原尺寸显示 */
const FEATURE_STAGE_W = 560
const FEATURE_STAGE_H = 400

const featureVisualEl = ref<HTMLElement | null>(null)
// 初始宽度按设计尺寸算，避免挂载前缩放为 0 闪一下
const { width: featureVisualW } = useElementSize(featureVisualEl, {
  width: FEATURE_STAGE_W,
  height: 0,
})

/** 缩放到容器宽度（容器比设计尺寸窄时等比缩小，标注与标签跟着一起缩） */
const featureScale = computed(() => Math.min(1, featureVisualW.value / FEATURE_STAGE_W))

/** 舞台占位高度 = 设计高度 × 缩放（transform 不占布局空间，高度手动补上） */
const featureStageStyle = computed(() => ({
  height: `${Math.round(FEATURE_STAGE_H * featureScale.value)}px`,
}))

const featureStageInnerStyle = computed(() => ({
  transform: `scale(${featureScale.value})`,
}))

/* ---------- 导入 PDF / Word ---------- */
const docInputEl = ref<HTMLInputElement | null>(null)
/** 导入对话框：点「导入 PDF / Word」先在这里选解析引擎，再选文件 */
const showImportDialog = ref(false)
/** 默认 mineru（云解析）；docling 本地解析太耗服务器资源，前端已停用 */
const parser = ref<'docling' | 'mineru'>('mineru')
/** MinerU token，useStorage 记忆到 localStorage，下次免填 */
const mineruToken = useStorage('smartcv-mineru-token', '')

/* ---------- 解析进度弹窗 ---------- */
/** 阻塞进度弹窗是否显示（解析期间不让用户干别的） */
const showProgress = ref(false)
const progressState = ref<ParseProgress['state']>('pending')
const progressSteps = ref<ParseProgress['steps']>([])
const progressError = ref('')
/** 取消按钮持有的 AbortController：abort 掉 POST，服务端检测断开 → cancelled */
const progressAbort = ref<AbortController | null>(null)

const stepIcon = (s: ParseStep['status']) =>
  s === 'done' ? '✓' : s === 'failed' ? '✕' : s === 'running' ? '…' : '·'

function onCancelParse() {
  progressAbort.value?.abort()
}

function pickDoc() {
  showImportDialog.value = true
}

/** 对话框里点「选择文件」：关掉对话框，再唤起系统文件选择 */
function confirmImport() {
  showImportDialog.value = false
  docInputEl.value?.click()
}

async function onDocChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复导入同一个文件
  if (!file) return

  // 弹阻塞进度窗，解析期间轮询 status 更新各步骤状态（步骤列表由后端返回）
  const abort = new AbortController()
  progressAbort.value = abort
  showProgress.value = true
  progressState.value = 'pending'
  progressSteps.value = []
  progressError.value = ''

  try {
    const data = await parseResumeFile(
      file,
      { parser: parser.value, mineruToken: mineruToken.value },
      (p) => {
        progressState.value = p.state
        progressSteps.value = p.steps
        progressError.value = p.error ?? ''
      },
      abort.signal,
    )
    const ok = store.importResume(data)
    if (ok) {
      message.success(`解析完成，已导入 ${store.resume.length} 个章节`)
      emit('enter')
    } else {
      message.error('导入失败：解析结果不是合法的简历数据')
    }
  } catch (err) {
    // 用户点「取消」触发 abort：静默关闭，不弹错误提示
    if (!(err instanceof DOMException && err.name === 'AbortError')) {
      message.error(err instanceof Error ? err.message : '文档解析失败，请重试')
    }
  } finally {
    showProgress.value = false
    progressAbort.value = null
  }
}

/* ---------- 导入 JSON ---------- */
const jsonInputEl = ref<HTMLInputElement | null>(null)

function pickJson() {
  jsonInputEl.value?.click()
}

function onJsonChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复导入同一个文件
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(String(reader.result))
      const ok = store.importResume(data)
      if (ok) {
        message.success(`已导入：${store.resume.length} 个章节`)
        emit('enter')
      } else {
        message.error('导入失败：JSON 格式不对（顶层需要是章节数组）')
      }
    } catch {
      message.error('导入失败：文件不是合法的 JSON')
    }
  }
  reader.readAsText(file)
}

/* ---------- 新建 ---------- */
function onNew() {
  store.clearAll()
  emit('enter')
}

/* ---------- 加载示例 ---------- */
/** 示例画廊弹层（清单与缩略图都在子组件里按需加载） */
const showGallery = ref(false)
</script>

<template>
  <div class="home-page">
    <div class="home-container">
      <!-- Hero：左文案与操作 / 右真实渲染的 A4 演示简历 -->
      <section class="home-hero">
        <div class="hero-copy">
          <!-- 品牌眉标：应用图标 + 产品定位，署名单独占一行、右对齐 -->
          <div class="hero-eyebrow">
            <img class="hero-eyebrow-icon" src="/favicon.svg" alt="" width="48" height="48" />
            <div class="hero-eyebrow-copy">
              <span class="hero-eyebrow-desc">基于 LangGraph 的多 Agent 工作流简历编辑器</span>
              <span class="hero-eyebrow-sign">
                <span class="hero-eyebrow-dash">——</span>
                <span class="hero-eyebrow-brand">SmartCV</span>
              </span>
            </div>
          </div>
          <h1 class="hero-title">做一份配得上你的简历</h1>
          <p class="hero-sub">
            导入 PDF / Word，AI 自动解析成可编辑简历；<br class="sub-break" />
            也可以从空白或模板开始，再用 AI 逐段打磨措辞与亮点。
          </p>

          <div class="hero-actions">
            <button class="hero-btn hero-btn-primary" @click="pickDoc">
              <IconGlyph name="file-up" :size="16" />
              导入简历
            </button>
            <button class="hero-btn hero-btn-secondary" @click="onNew">
              <IconGlyph name="file-plus-2" :size="16" />
              新建空白简历
            </button>
          </div>

          <div class="hero-quiet">
            <button class="quiet-btn" @click="pickJson">
              <IconGlyph name="file-json" :size="14" />
              导入 JSON
            </button>
            <button class="quiet-btn" @click="showGallery = true">
              <IconGlyph name="layout-template" :size="14" />
              加载示例
            </button>
          </div>

          <ul class="hero-trust">
            <li>
              <IconGlyph name="check" :size="13" />
              支持 PDF / DOCX / JSON
            </li>
            <li>
              <IconGlyph name="shield-check" :size="13" />
              数据只保存在本机浏览器
            </li>
          </ul>
        </div>

        <!-- 演示简历：PreviewSection 真实渲染，所见即所得 -->
        <div class="hero-visual" aria-hidden="true">
          <div class="hero-visual-panel">
            <div class="hero-paper-wrap" :style="paperWrapStyle">
              <div class="hero-paper" :style="paperStyle">
                <PreviewSection v-for="s in heroResume" :key="s.id" :section="s" />
              </div>
            </div>
            <div class="hero-chip hero-chip-parse">
              <span class="hero-chip-icon"><IconGlyph name="scan-line" :size="15" /></span>
              <span class="hero-chip-text">
                <span class="hero-chip-title">PDF 智能解析</span>
                <span class="hero-chip-sub">自动识别章节与内容</span>
              </span>
            </div>
            <div class="hero-chip hero-chip-polish">
              <span class="hero-chip-icon"><IconGlyph name="sparkles" :size="15" /></span>
              <span class="hero-chip-text">
                <span class="hero-chip-title">AI 逐段优化</span>
                <span class="hero-chip-sub">3 处润色建议已应用</span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- 三步流程：单面板 + 发丝分隔线，编号对应真实的操作顺序 -->
      <section class="home-steps">
        <div class="steps-head">
          <h2 class="steps-title">三步，把旧简历变成新机会</h2>
          <p class="steps-sub">不需要学习排版，从解析到导出，SmartCV 全程代劳</p>
        </div>
        <div class="steps-panel">
          <div class="step-col">
            <div class="step-top">
              <span class="step-icon"><IconGlyph name="scan-line" :size="16" /></span>
              <span class="step-num">01</span>
            </div>
            <h3 class="step-title">导入或新建</h3>
            <p class="step-desc">上传 PDF / Word，AI 解析成结构化简历；也可以从空白或示例模板开始。</p>
          </div>
          <div class="step-col">
            <div class="step-top">
              <span class="step-icon"><IconGlyph name="move" :size="16" /></span>
              <span class="step-num">02</span>
            </div>
            <h3 class="step-title">自由排版</h3>
            <p class="step-desc">拖拽调整章节与布局，字号、行距、分页精细控制，A4 实时预览。</p>
          </div>
          <div class="step-col">
            <div class="step-top">
              <span class="step-icon"><IconGlyph name="sparkles" :size="16" /></span>
              <span class="step-num">03</span>
            </div>
            <h3 class="step-title">AI 优化导出</h3>
            <p class="step-desc">AI 逐段润色措辞、按目标岗位个性化，最后导出 PDF 或 JSON。</p>
          </div>
        </div>
      </section>

      <!-- 组件库功能介绍：自由组合章节/布局/组件，右侧为编辑器缩略图 + 三点标注 -->
      <section class="home-feature">
        <div class="feature-copy">
          <h2 class="feature-title">自由组合，打造专属简历</h2>
          <p class="feature-sub">
            不局限于固定模板，从内容章节到页面布局，自由组合简历的每个细节，让简历更符合你的个人风格。
          </p>
          <ul class="feature-list">
            <li class="feature-item">
              <span class="feature-item-icon"><IconGlyph name="layout-list" :size="15" /></span>
              <span class="feature-item-text">
                <span class="feature-item-title">章节</span>
                <span class="feature-item-desc">丰富的简历内容模块，支持教育经历、工作经历、项目经历、个人简介等内容。</span>
              </span>
            </li>
            <li class="feature-item">
              <span class="feature-item-icon"><IconGlyph name="columns-2" :size="15" /></span>
              <span class="feature-item-text">
                <span class="feature-item-title">布局</span>
                <span class="feature-item-desc">灵活调整页面结构，支持单列、双列等布局方式，自由组织简历内容。</span>
              </span>
            </li>
            <li class="feature-item">
              <span class="feature-item-icon"><IconGlyph name="shapes" :size="15" /></span>
              <span class="feature-item-text">
                <span class="feature-item-title">组件</span>
                <span class="feature-item-desc">丰富的基础元素，提供文字、图片、标签、分割线等组件，并支持常用内容预设。</span>
              </span>
            </li>
          </ul>
          <button class="feature-cta" @click="emit('enter')">
            开始编辑简历
            <IconGlyph name="arrow-right" :size="14" />
          </button>
        </div>

        <!-- 编辑器缩略图：组件库在上、画布在下（真实编辑器的上下结构）；标注直接圈在简历内容上 -->
        <div ref="featureVisualEl" class="feature-visual" aria-hidden="true">
          <div class="feature-stage" :style="featureStageStyle">
            <div class="feature-stage-inner" :style="featureStageInnerStyle">
              <div class="editor-mock">
                <!-- 顶部工具栏 -->
                <div class="mock-toolbar">
                  <span class="mock-dots"><i /><i /><i /></span>
                  <span class="mock-title">简历编辑器</span>
                </div>

                <!-- 组件库：位于画布上方的三个分类入口 -->
                <div class="mock-library">
                  <span class="lib-label">组件库</span>
                  <span class="lib-tab lib-tab-active"><IconGlyph name="layout-list" :size="11" />章节</span>
                  <span class="lib-tab"><IconGlyph name="columns-2" :size="11" />布局</span>
                  <span class="lib-tab"><IconGlyph name="shapes" :size="11" />组件</span>
                </div>

                <!-- 画布：简历内容 + 三处圈注（① 章节模块 ② 章节内左右布局 ③ 标签组件） -->
                <div class="mock-canvas">
                  <div class="mock-paper">
                    <span class="pk pk-name">林知远</span>
                    <span class="pk pk-bar" style="width: 76px" />
                    <span class="pk-hr" />
                    <span class="pk-sec">个人简介</span>
                    <span class="pk pk-bar" style="width: 100%" />
                    <span class="pk pk-bar" style="width: 76%" />

                    <!-- ① 章节：圈出整个「教育经历」模块 -->
                    <span class="pk-wrap">
                      <span class="pk-sec">教育经历</span>
                      <span class="pk-row">
                        <span class="pk pk-bar" style="width: 56%" />
                        <span class="pk pk-bar" style="width: 24%" />
                      </span>
                      <span class="annot-ring">
                        <i class="ring-badge">1</i>
                        <i class="ring-line" />
                        <span class="annot-label">
                          <span class="annot-label-title">章节</span>
                          <span class="annot-label-sub">添加和管理简历内容模块</span>
                        </span>
                      </span>
                    </span>

                    <!-- ② 布局：圈出章节内部的左右分布（左内容块 + 虚线分隔 + 右内容块） -->
                    <span class="pk-sec">工作经历</span>
                    <span class="pk-wrap">
                      <span class="layout-split">
                        <span class="layout-left">
                          <span class="pk-bar" style="width: 100%" />
                          <span class="pk-bar" style="width: 88%" />
                          <span class="pk-bar" style="width: 72%" />
                        </span>
                        <i class="layout-divider" />
                        <span class="layout-right">
                          <span class="pk-bar" style="width: 100%" />
                          <span class="tag-pill" style="width: 62%" />
                        </span>
                      </span>
                      <span class="annot-ring">
                        <i class="ring-badge">2</i>
                        <i class="ring-line" />
                        <span class="annot-label">
                          <span class="annot-label-title">布局</span>
                          <span class="annot-label-sub">自由调整单列、双列等页面结构</span>
                        </span>
                      </span>
                    </span>
                    <span class="pk-bullets">
                      <span class="pk-bullet"><i class="bullet-dot" /><span class="pk-bar" style="width: 90%" /></span>
                      <span class="pk-bullet"><i class="bullet-dot" /><span class="pk-bar" style="width: 80%" /></span>
                    </span>

                    <!-- ③ 组件：圈出标签行 -->
                    <span class="pk-sec">专业技能</span>
                    <span class="pk-wrap">
                      <span class="pk-tags"><span class="pk-tag" /><span class="pk-tag" /><span class="pk-tag" /><span class="pk-tag" /></span>
                      <span class="annot-ring">
                        <i class="ring-badge">3</i>
                        <i class="ring-line" />
                        <span class="annot-label">
                          <span class="annot-label-title">组件</span>
                          <span class="annot-label-sub">添加文字、图片、标签等基础元素</span>
                        </span>
                      </span>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 窄屏替代：标签改成普通列表（不随缩略图缩放，保证可读） -->
          <div class="feature-annot-list">
            <p class="annot-row"><span class="annot-row-dot">1</span><span><b>章节</b> · 添加和管理简历内容模块</span></p>
            <p class="annot-row"><span class="annot-row-dot">2</span><span><b>布局</b> · 自由调整单列、双列等页面结构</span></p>
            <p class="annot-row"><span class="annot-row-dot">3</span><span><b>组件</b> · 添加文字、图片、标签等基础元素</span></p>
          </div>
        </div>
      </section>

      <!-- 已有简历：直接继续编辑 -->
      <section v-if="hasResume()" class="home-continue">
        <div class="continue-card">
          <span class="continue-icon"><IconGlyph name="pen-line" :size="16" /></span>
          <span class="continue-copy">
            <span class="continue-title">继续编辑当前简历</span>
            <span class="continue-desc">已有 {{ store.resume.length }} 个章节，上次的内容还保存在本机</span>
          </span>
          <button class="continue-btn" @click="emit('enter')">
            打开编辑器
            <IconGlyph name="arrow-right" :size="14" />
          </button>
        </div>
      </section>

      <!-- 页脚：隐私说明 + 导出统计 -->
      <footer class="home-footer">
        <p class="home-privacy">
          你的简历只存在本机浏览器里，不收集任何数据；仅在使用 AI 功能时，内容才会发送到你配置的模型服务商（仅匿名统计导出次数，不涉及简历内容）
        </p>
        <p class="home-stats">
          <span>PDF {{ statsStore.pdf }} 次</span>
          <span>JSON {{ statsStore.json }} 次</span>
        </p>
      </footer>
    </div>

    <!-- 示例模板画廊；载入成功后直接进编辑器 -->
    <ExampleGallery v-model:show="showGallery" @enter="emit('enter')" />

    <!-- 导入 PDF / Word 对话框：选解析引擎 → 选文件 -->
    <n-modal
      v-model:show="showImportDialog"
      :mask-closable="false"
      preset="dialog"
      title="导入 PDF / Word"
      positive-text="选择文件"
      negative-text="取消"
      @positive-click="confirmImport"
    >
      <div class="import-dialog-body">
        <p class="import-tip">
          💡 目前 AI 识别还不够准，解析结果可能出错；最稳的方式是直接「新建」手动搭建简历。
        </p>
        <div class="import-dialog-row">
          <span class="import-dialog-label">解析引擎</span>
          <n-radio-group v-model:value="parser" size="small">
            <n-radio-button value="mineru">MinerU（云解析）</n-radio-button>
            <n-radio-button value="docling" disabled>docling（本地解析）</n-radio-button>
          </n-radio-group>
        </div>
        <p class="import-docling-note">⚠️ docling 本地解析太耗服务器资源，已停用，请用 MinerU 云解析</p>
        <n-input
          v-if="parser === 'mineru'"
          v-model:value="mineruToken"
          type="password"
          show-password-on="click"
          placeholder="MinerU API Token（官网 API 管理页创建）"
        />
      </div>
    </n-modal>

    <!-- 解析进度弹窗：阻塞，直到解析完成/失败/取消 -->
    <n-modal
      v-model:show="showProgress"
      :mask-closable="false"
      :close-on-esc="false"
      preset="card"
      title="正在解析简历"
      style="width: 380px"
    >
      <div class="progress-body">
        <p class="progress-estimate">大概预计 2-3 分钟</p>
        <p class="progress-tip">正在解析，请勿关闭页面</p>
        <ul class="progress-list">
          <li
            v-for="s in progressSteps"
            :key="s.name"
            class="progress-step"
            :class="`step-${s.status}`"
          >
            <span class="progress-icon">{{ stepIcon(s.status) }}</span>
            <span class="progress-name">{{ s.name }}</span>
          </li>
        </ul>
        <p
          v-if="progressState === 'failed' || progressState === 'cancelled'"
          class="progress-error"
        >
          {{ progressError || (progressState === 'cancelled' ? '已取消' : '解析失败') }}
        </p>
        <div class="progress-actions">
          <n-button size="small" @click="onCancelParse">取消</n-button>
        </div>
      </div>
    </n-modal>

    <!-- 隐藏的文件输入框 -->
    <input
      ref="docInputEl"
      type="file"
      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      class="hidden-input"
      @change="onDocChange"
    />
    <input ref="jsonInputEl" type="file" accept="application/json,.json" class="hidden-input" @change="onJsonChange" />
  </div>
</template>

<style scoped>
/* ============================================================
 * 主页整体：居中内容容器，页面本身可滚动
 * ============================================================ */
.home-page {
  height: 100%;
  overflow: auto;
}
.home-container {
  width: min(1120px, 100%);
  margin: 0 auto;
  padding: 56px 28px 0;
}

/* ============================================================
 * Hero：左文案 / 右演示简历
 * ============================================================ */
.home-hero {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
  align-items: center;
  gap: 40px;
}

/* ---------- 左侧文案 ---------- */
/* 品牌眉标：图标 + 两行文案（定位句 / 右对齐署名） */
.hero-eyebrow {
  display: flex;
  align-items: center;
  gap: 14px;
  animation: rise-in 0.55s var(--ease) both;
}
.hero-eyebrow-icon {
  display: block;
  flex: none;
  width: 48px;
  height: 48px;
}
.hero-eyebrow-copy {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.hero-eyebrow-desc {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: -0.01em;
  color: var(--text);
}
.hero-eyebrow-sign {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 8px;
  line-height: 1.1;
}
.hero-eyebrow-dash {
  font-family: var(--font-display);
  font-size: 17px;
  letter-spacing: 0.04em;
  color: var(--text-tertiary);
}
.hero-eyebrow-brand {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text);
}
.hero-title {
  margin: 22px 0 0;
  font-size: clamp(30px, 4.2vw, 42px);
  font-weight: 600;
  line-height: 1.16;
  letter-spacing: -0.02em;
  color: var(--text);
  text-wrap: balance;
  animation: rise-in 0.55s 0.06s var(--ease) both;
}
.hero-sub {
  margin: 18px 0 0;
  max-width: 480px;
  font-size: 15.5px;
  line-height: 1.75;
  color: var(--text-secondary);
  animation: rise-in 0.55s 0.12s var(--ease) both;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 30px;
  animation: rise-in 0.55s 0.18s var(--ease) both;
}
.hero-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 46px;
  padding: 0 24px;
  border-radius: 11px;
  font-size: 15px;
  font-weight: 550;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    border-color 0.16s var(--ease),
    color 0.16s var(--ease),
    box-shadow 0.16s var(--ease),
    transform 0.16s var(--ease);
}
.hero-btn:active {
  transform: translateY(0);
}
.hero-btn-primary {
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
}
.hero-btn-primary:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px -10px rgba(71, 83, 199, 0.55);
}
.hero-btn-primary:active {
  background: #343da0;
}
.hero-btn-secondary {
  border: 1px solid var(--border-strong);
  background: var(--panel-bg);
  color: var(--text);
}
.hero-btn-secondary:hover {
  border-color: #c9cdd9;
  background: var(--surface-soft);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px -8px rgba(28, 33, 48, 0.18);
}

/* ---------- 次要入口：比主按钮小一号的描边图标按钮 ---------- */
.hero-quiet {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  animation: rise-in 0.55s 0.24s var(--ease) both;
}
.quiet-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 13px;
  border: 1px solid var(--border-strong);
  border-radius: 9px;
  background: var(--panel-bg);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    border-color 0.16s var(--ease),
    color 0.16s var(--ease),
    transform 0.16s var(--ease);
}
.quiet-btn .icon-glyph {
  color: var(--primary);
}
.quiet-btn:hover {
  background: var(--surface-soft);
  border-color: #c9cdd9;
  color: var(--text);
  transform: translateY(-1px);
}
.quiet-btn:active {
  transform: translateY(0);
}

/* ---------- 信任行：格式支持 + 本地存储 ---------- */
.hero-trust {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  list-style: none;
  margin: 22px 0 0;
  padding: 0;
  animation: rise-in 0.55s 0.3s var(--ease) both;
}
.hero-trust li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.hero-trust .icon-glyph {
  color: var(--primary);
  opacity: 0.75;
}

/* ---------- 右侧：演示简历 ---------- */
.hero-visual {
  animation: rise-in 0.7s 0.16s var(--ease) both;
}
.hero-visual-panel {
  position: relative;
  display: flex;
  justify-content: center;
  padding: 30px 24px 0;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 20px;
}
/* 裁切容器：只露一页的 78%，底部渐变暗示「下面还有内容」 */
.hero-paper-wrap {
  position: relative;
  overflow: hidden;
}
.hero-paper-wrap::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 64px;
  background: linear-gradient(to bottom, transparent, var(--surface-soft));
  pointer-events: none;
}
.hero-paper {
  background: #fff;
  box-shadow: var(--shadow-paper);
}

/* ---------- 浮动芯片：AI 解析 / AI 优化 ---------- */
.hero-chip {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-raised);
  z-index: 2;
}
.hero-chip-parse {
  top: 26px;
  right: -14px;
}
.hero-chip-polish {
  bottom: 34px;
  left: -16px;
}
.hero-chip-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary);
}
.hero-chip-text {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}
.hero-chip-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.hero-chip-sub {
  font-size: 11px;
  color: var(--text-tertiary);
}

/* ---------- 入场动画：一次性的上浮显现 ---------- */
@keyframes rise-in {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ============================================================
 * 三步流程：单面板 + 发丝分隔线（编号对应真实顺序）
 * ============================================================ */
.home-steps {
  margin-top: 64px;
}
.steps-head {
  text-align: center;
}
.steps-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text);
}
.steps-sub {
  margin: 7px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}
.steps-panel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 22px;
  padding: 26px 30px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 16px;
}
.step-col {
  padding: 0 28px;
}
.step-col:first-child {
  padding-left: 0;
}
.step-col:last-child {
  padding-right: 0;
}
.step-col + .step-col {
  border-left: 1px solid var(--border);
}
.step-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.step-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary);
}
.step-num {
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
}
.step-title {
  margin: 14px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.step-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-secondary);
}

/* ============================================================
 * 组件库功能介绍：左文案 / 右编辑器缩略图 + 三点标注
 * ============================================================ */
.home-feature {
  display: grid;
  /* 右侧缩略图需要约 550px 才不用缩小，视觉列多分一点 */
  grid-template-columns: minmax(0, 4.5fr) minmax(0, 6.5fr);
  align-items: center;
  gap: 48px;
  margin-top: 64px;
}

/* ---------- 左侧文案 ---------- */
.feature-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--text);
}
.feature-sub {
  margin: 12px 0 0;
  max-width: 430px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.feature-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin: 22px 0 0;
  padding: 0;
}
.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.feature-item-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary);
}
.feature-item-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.feature-item-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.feature-item-desc {
  max-width: 400px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-secondary);
}
.feature-cta {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 38px;
  margin-top: 26px;
  padding: 0 18px;
  border: 1px solid var(--primary);
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  font-size: 13.5px;
  font-weight: 550;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    border-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease),
    transform 0.16s var(--ease);
}
.feature-cta:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px -10px rgba(71, 83, 199, 0.55);
}
.feature-cta:active {
  background: #343da0;
  transform: translateY(0);
}

/* ---------- 右侧缩略图舞台：固定设计尺寸 + 等比缩放 ---------- */
.feature-visual {
  position: relative;
  min-width: 0;
}
.feature-stage {
  position: relative;
  width: 100%;
}
.feature-stage-inner {
  position: absolute;
  top: 0;
  left: 50%;
  margin-left: -280px; /* 560 设计宽的一半：缩放后仍水平居中 */
  width: 560px;
  height: 400px;
  transform-origin: top center;
}

/* ---------- 编辑器缩略图本体 ---------- */
.editor-mock {
  width: 560px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: var(--shadow-raised);
}

/* 顶部工具栏 */
.mock-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border);
}
.mock-dots {
  display: flex;
  gap: 5px;
}
.mock-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #e2e5ee;
}
.mock-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
}

/* 组件库：画布上方的三个分类入口（上下结构，对应真实编辑器） */
.mock-library {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 64px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border);
}
.lib-label {
  margin-right: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.lib-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
}
.lib-tab .icon-glyph {
  opacity: 0.65;
}
.lib-tab-active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.lib-tab-active .icon-glyph {
  opacity: 1;
}

/* 画布：凹面灰底，纸面靠左、说明标签在右侧 */
.mock-canvas {
  position: relative;
  height: 300px;
  background: var(--surface-sunken);
}
.mock-paper {
  position: absolute;
  top: 14px;
  left: 56px;
  display: flex;
  flex-direction: column;
  width: 240px;
  height: 272px;
  padding: 13px;
  background: #fff;
  box-shadow: var(--shadow-paper);
}

/* ---------- 纸面骨架 ---------- */
.pk {
  display: block;
  flex: none;
}
.pk-name {
  height: 15px;
  text-align: center;
  font-size: 12.5px;
  font-weight: 700;
  color: #262c3d;
}
.pk-bar {
  height: 4px;
  margin-top: 4px;
  border-radius: 3px;
  background: #e8ebf2;
}
.pk-name + .pk-bar {
  margin-top: 6px;
}
.pk-hr {
  height: 1px;
  margin-top: 8px;
  background: #eef0f5;
}
.pk-sec {
  margin-top: 9px;
  font-size: 9px;
  font-weight: 600;
  line-height: 1.3;
  color: #39415a;
}
.pk-sec + .pk-bar,
.pk-sec + .pk-row {
  margin-top: 6px;
}
.pk-wrap {
  position: relative;
  display: block;
  margin-top: 10px;
}
.pk-wrap > :first-child {
  margin-top: 0;
}
.pk-wrap + .pk-sec,
.pk-bullets + .pk-sec {
  margin-top: 12px;
}
.pk-row {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
}
.pk-row .pk-bar {
  margin-top: 0;
}
.pk-bullets {
  display: block;
  margin-top: 10px;
}
.pk-bullet {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 4px;
}
.pk-bullet:first-child {
  margin-top: 0;
}
.pk-bullet .pk-bar {
  flex: 1;
  margin-top: 0;
}
.bullet-dot {
  flex: none;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #c6cbd8;
}
.pk-tags {
  display: flex;
  gap: 5px;
}
.pk-tag {
  width: 30px;
  height: 8px;
  border-radius: 999px;
  background: #eef0f7;
}

/* ---------- ② 布局演示：章节内部的左右分布 ---------- */
.layout-split {
  display: flex;
  align-items: stretch;
  gap: 10px;
}
.layout-left {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 118px;
  padding: 5px 7px;
  border-radius: 6px;
  background: rgba(71, 83, 199, 0.055);
}
.layout-right {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 74px;
  padding: 5px 7px;
  border-radius: 6px;
  background: rgba(71, 83, 199, 0.1);
}
.layout-left .pk-bar,
.layout-right .pk-bar {
  margin-top: 0;
}
.layout-divider {
  align-self: stretch;
  width: 0;
  border-left: 1px dashed rgba(71, 83, 199, 0.5);
}
.tag-pill {
  height: 7px;
  border-radius: 999px;
  background: #e2e6f5;
}

/* ---------- 圈注：描边圈 + 编号圆点 + 引导线 + 说明标签 ----------
 * 标签锚定在圈注环上（top 50% 相对环居中），与内容块的实际高度解耦，
 * 内容怎么改标签都始终和圈注中心对齐，不需要任何像素级手工坐标。 */
.annot-ring {
  position: absolute;
  inset: -6px;
  border: 1.5px solid rgba(71, 83, 199, 0.85);
  border-radius: 8px;
  background: rgba(71, 83, 199, 0.04);
  pointer-events: none;
  z-index: 1;
}
.annot-ring * {
  pointer-events: none;
}
.ring-badge {
  position: absolute;
  top: 50%;
  right: -8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  transform: translateY(-50%);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.15);
}
.ring-line {
  position: absolute;
  top: 50%;
  left: 100%;
  width: 14px;
  height: 1.5px;
  margin-top: -0.75px;
  background: rgba(71, 83, 199, 0.5);
}

/* ---------- 说明标签：挂在圈注右侧，垂直方向与圈注中心对齐 ---------- */
.annot-label {
  position: absolute;
  top: 50%;
  left: calc(100% + 14px);
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 168px;
  padding: 7px 10px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: var(--shadow-raised);
  transform: translateY(-50%);
}
.annot-label-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.annot-label-sub {
  font-size: 9.5px;
  line-height: 1.45;
  color: var(--text-tertiary);
}

/* 窄屏替代：标注改普通列表，文字不随缩略图缩放 */
.feature-annot-list {
  display: none;
}
.annot-row {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.annot-row b {
  font-weight: 600;
  color: var(--text);
}
.annot-row-dot {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.16);
}

/* ============================================================
 * 继续编辑：已有简历时的快捷入口
 * ============================================================ */
.home-continue {
  margin-top: 16px;
}
.continue-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  background: var(--primary-faint);
  border: 1px solid var(--border);
  border-radius: 14px;
}
.continue-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  color: var(--primary);
}
.continue-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.4;
}
.continue-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.continue-desc {
  font-size: 12px;
  color: var(--text-secondary);
}
.continue-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  margin-left: auto;
  height: 34px;
  padding: 0 14px;
  border: none;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    transform 0.16s var(--ease);
}
.continue-btn:hover {
  background: var(--primary-hover);
  transform: translateY(-1px);
}
.continue-btn:active {
  transform: translateY(0);
}

/* ============================================================
 * 页脚：隐私说明 + 导出统计
 * ============================================================ */
.home-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-top: 48px;
  padding: 16px 0 28px;
  border-top: 1px solid var(--border);
}
.home-privacy {
  margin: 0;
  max-width: 640px;
  font-size: 11.5px;
  line-height: 1.75;
  color: var(--text-tertiary);
}
.home-stats {
  flex: none;
  display: flex;
  gap: 14px;
  margin: 0;
  padding-top: 1px;
  font-size: 11.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

/* ---------- 导入对话框 ---------- */
.import-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 4px;
}
.import-tip {
  margin: 0;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--warning);
  background: var(--warning-soft);
  border: 1px solid rgba(166, 118, 63, 0.18);
  border-radius: var(--radius-md);
}
.import-dialog-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.import-dialog-label {
  flex: none;
  font-size: 12px;
  color: var(--text-secondary);
}
.import-docling-note {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
}

/* ---------- 解析进度 ---------- */
.progress-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.progress-estimate {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--primary);
}
.progress-tip {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.progress-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.progress-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-secondary);
}
.progress-icon {
  width: 16px;
  text-align: center;
  font-weight: 700;
}
.step-done .progress-icon {
  color: var(--primary);
}
.step-failed .progress-icon {
  color: var(--danger);
}
.step-running .progress-icon {
  color: var(--primary);
}
.step-pending .progress-icon {
  color: var(--text-tertiary);
  opacity: 0.5;
}
.progress-error {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--danger-soft);
  font-size: 12px;
  line-height: 1.6;
  color: var(--danger);
}
.progress-actions {
  display: flex;
  justify-content: flex-end;
}

.hidden-input {
  display: none;
}

/* ============================================================
 * 响应式
 * ============================================================ */
/* 组件库功能介绍：两栏下视觉列不足 550px 时整体改上下结构（缩略图全宽展示） */
@media (max-width: 1024px) {
  .home-feature {
    grid-template-columns: 1fr;
    gap: 40px;
  }
  .feature-copy {
    max-width: 560px;
  }
}

/* 窄屏：缩略图里的说明标签会缩得太小，改显示缩略图下方的普通标注列表 */
@media (max-width: 640px) {
  .annot-label,
  .ring-line {
    display: none;
  }
  .feature-annot-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 14px;
    padding: 0 4px;
  }
}

/* 双栏但文案列较窄（约 900–1080px）时眉标收一档，避免定位句被拆开 */
@media (min-width: 901px) and (max-width: 1080px) {
  .hero-eyebrow-icon {
    width: 44px;
    height: 44px;
  }
  .hero-eyebrow-desc {
    font-size: 17px;
  }
  .hero-eyebrow-brand {
    font-size: 21px;
  }
}

@media (max-width: 900px) {
  .home-hero {
    grid-template-columns: 1fr;
    gap: 40px;
  }
  .hero-copy {
    max-width: 560px;
  }
  .hero-visual-panel {
    max-width: 480px;
    margin: 0 auto;
  }
  .hero-chip-parse {
    right: 10px;
  }
  .hero-chip-polish {
    left: 10px;
  }
}

@media (max-width: 760px) {
  .home-container {
    padding: 40px 20px 0;
  }
  .home-steps {
    margin-top: 48px;
  }
  .steps-panel {
    grid-template-columns: 1fr;
    gap: 0;
    padding: 22px 24px;
  }
  .step-col {
    padding: 18px 0;
  }
  .step-col + .step-col {
    border-left: none;
    border-top: 1px solid var(--border);
  }
  .step-col:first-child {
    padding-top: 0;
  }
  .step-col:last-child {
    padding-bottom: 0;
  }
  .continue-card {
    flex-wrap: wrap;
  }
  .continue-btn {
    width: 100%;
    justify-content: center;
  }
  .home-footer {
    flex-direction: column;
    gap: 12px;
  }
}

@media (max-width: 560px) {
  .sub-break {
    display: none;
  }
  .hero-eyebrow {
    gap: 10px;
  }
  .hero-eyebrow-icon {
    width: 40px;
    height: 40px;
  }
  .hero-eyebrow-desc {
    font-size: 15.5px;
  }
  .hero-eyebrow-dash {
    font-size: 15px;
  }
  .hero-eyebrow-brand {
    font-size: 19px;
  }
  .hero-actions {
    flex-direction: column;
    align-items: stretch;
  }
  .hero-btn {
    justify-content: center;
  }
  .hero-trust {
    flex-direction: column;
    gap: 8px;
  }
  .hero-chip-parse {
    right: 8px;
  }
  .hero-chip-polish {
    left: 8px;
  }
}
</style>
