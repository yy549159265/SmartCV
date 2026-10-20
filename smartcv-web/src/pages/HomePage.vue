<script setup lang="ts">
/**
 * 主页：简历的唯一入口。
 * 四种方式开始编辑：
 *   1. 导入 PDF / Word —— 后端 agent 解析成简历 JSON（api/document.ts 占位）；
 *   2. 导入 JSON —— 读取本地 .json 简历文件；
 *   3. 新建 —— 空白简历；
 *   4. 加载示例 —— 从仓库 example/ 目录挑一份现成的（见 ExampleGallery.vue）。
 * 任一种完成后 emit('enter')，由 App.vue 切到编辑页展示/编辑。
 */
import { onMounted, ref } from 'vue'
import { useStorage } from '@vueuse/core'
import { useResumeStore } from '@/stores/resume'
import { useStatsStore } from '@/stores/stats'
import { parseResumeFile, type ParseProgress, type ParseStep } from '@/api/document'
import { message } from '@/utils/feedback'
import ExampleGallery from '@/components/ExampleGallery.vue'
import BrandMark from '@/components/BrandMark.vue'

const store = useResumeStore()
const statsStore = useStatsStore()

/** 打开主页时拉一次导出统计（失败静默，不打扰） */
onMounted(() => {
  statsStore.load()
})
const emit = defineEmits<{ enter: [] }>()

/** 当前是否已有简历（用于提示可直接继续编辑） */
const hasResume = () => store.resume.length > 0

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

  // 弹阻塞进度窗，解析期间轮询 status 更新 5 个步骤的状态
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
    <div class="home-inner">
      <header class="home-hero">
        <div class="home-brand">
          <BrandMark :size="42" />
          <h1>SmartCV</h1>
        </div>
        <p class="home-sub">选择一份简历开始编辑</p>
        <p v-if="hasResume()" class="home-hint">
          已有 {{ store.resume.length }} 个章节，也可从下方导入后直接继续
        </p>
      </header>

      <div class="home-cards">
        <!-- 导入 PDF / Word -->
        <button class="home-card" @click="pickDoc">
          <span class="home-card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M6.5 3.5h6.8l4.2 4.2v12.8H6.5z" />
              <path d="M13.3 3.5v4.2h4.2M9.5 12h5M9.5 15.5h5" />
            </svg>
          </span>
          <span class="home-card-text">
            <span class="home-card-title">导入 PDF / Word</span>
            <span class="home-card-desc">上传文档，AI 解析成可编辑简历</span>
          </span>
        </button>

        <!-- 导入 JSON -->
        <button class="home-card" @click="pickJson">
          <span class="home-card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M9.2 4.5c-2.1 0-2.2 2.4-2.2 3.8 0 1.5-.8 3.7-2.5 3.7 1.7 0 2.5 2.2 2.5 3.7 0 1.4.1 3.8 2.2 3.8" />
              <path d="M14.8 4.5c2.1 0 2.2 2.4 2.2 3.8 0 1.5.8 3.7 2.5 3.7-1.7 0-2.5 2.2-2.5 3.7 0 1.4-.1 3.8-2.2 3.8" />
            </svg>
          </span>
          <span class="home-card-text">
            <span class="home-card-title">导入 JSON</span>
            <span class="home-card-desc">读取本地的简历 JSON 文件</span>
          </span>
        </button>

        <!-- 新建 -->
        <button class="home-card" @click="onNew">
          <span class="home-card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="4.5" y="4.5" width="15" height="15" rx="3.5" />
              <path d="M12 8.5v7M8.5 12h7" />
            </svg>
          </span>
          <span class="home-card-text">
            <span class="home-card-title">新建空白简历</span>
            <span class="home-card-desc">从零开始搭建</span>
          </span>
        </button>

        <!-- 加载示例 -->
        <button class="home-card" @click="showGallery = true">
          <span class="home-card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="4" y="5" width="16" height="14" rx="2.5" />
              <circle cx="9" cy="10" r="1.4" />
              <path d="M5 17l4.5-4 3 2.5L16.5 11 20 15" />
            </svg>
          </span>
          <span class="home-card-text">
            <span class="home-card-title">加载示例</span>
            <span class="home-card-desc">看看现成的简历长什么样</span>
          </span>
        </button>
      </div>

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
.home-page {
  height: 100%;
  overflow: auto;
  display: flex;
  padding: 44px 24px;
}
.home-inner {
  width: min(760px, 100%);
  margin: auto;
  padding: 4px 0;
}

/* ---------- 起始页头部：左对齐的编辑排版 ---------- */
.home-brand {
  display: flex;
  align-items: center;
  gap: 15px;
}
.home-brand h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(34px, 4vw, 44px);
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.01em;
  color: var(--text);
}
.home-sub {
  margin: 16px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.home-hint {
  display: inline-flex;
  margin: 12px 0 0;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--primary-soft);
  font-size: 12px;
  line-height: 1.5;
  color: var(--primary-hover);
}

/* ---------- 四个入口：扁平纸片，无悬浮位移、无投影 ---------- */
.home-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 36px;
}
.home-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--panel-bg);
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    border-color 0.16s var(--ease);
}
.home-card:hover {
  background: var(--surface-soft);
  border-color: var(--border-strong);
}
.home-card:active {
  background: var(--primary-faint);
}
.home-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 9px;
  background: var(--surface-soft);
  color: var(--primary);
  transition: background 0.16s var(--ease);
}
.home-card:hover .home-card-icon {
  background: var(--primary-soft);
}
.home-card-icon svg {
  width: 19px;
  height: 19px;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.home-card-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding-top: 1px;
}
.home-card-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--text);
}
.home-card-desc {
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-tertiary);
}

/* ---------- 页脚：隐私说明 + 导出统计 ---------- */
.home-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-top: 32px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}
.home-privacy {
  margin: 0;
  max-width: 560px;
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

@media (max-width: 640px) {
  .home-page {
    padding: 32px 18px;
  }
  .home-cards {
    grid-template-columns: 1fr;
    margin-top: 28px;
  }
  .home-footer {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
