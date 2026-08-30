<script setup lang="ts">
/**
 * 主页：简历的唯一入口。
 * 三种方式开始编辑：
 *   1. 导入 PDF / Word —— 后端 agent 解析成简历 JSON（api/document.ts 占位）；
 *   2. 导入 JSON —— 读取本地 .json 简历文件；
 *   3. 新建 —— 空白简历。
 * 任一种完成后 emit('enter')，由 App.vue 切到编辑页展示/编辑。
 */
import { ref } from 'vue'
import { useStorage } from '@vueuse/core'
import { useResumeStore } from '@/stores/resume'
import { parseResumeFile, type ParseProgress, type ParseStep } from '@/api/document'
import { message } from '@/utils/feedback'

const store = useResumeStore()
const emit = defineEmits<{ enter: [] }>()

/** 当前是否已有简历（用于提示可直接继续编辑） */
const hasResume = () => store.resume.length > 0

/* ---------- 导入 PDF / Word ---------- */
const docInputEl = ref<HTMLInputElement | null>(null)
/** 导入对话框：点「导入 PDF / Word」先在这里选解析引擎，再选文件 */
const showImportDialog = ref(false)
/** 默认 docling（本地解析）；mineru 走云 API */
const parser = ref<'docling' | 'mineru'>('docling')
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
</script>

<template>
  <div class="home-page">
    <div class="home-hero">
      <div class="home-brand">
        <span class="home-brand-icon">🧱</span>
        <h1>SmartCV</h1>
      </div>
      <p class="home-sub">选择一份简历开始编辑</p>
      <p v-if="hasResume()" class="home-hint">
        当前已有 {{ store.resume.length }} 个章节，可在下方「新建」外的入口导入后直接编辑
      </p>
    </div>

    <div class="home-cards">
      <!-- 导入 PDF / Word -->
      <button class="home-card" @click="pickDoc">
        <span class="home-card-icon">📄</span>
        <span class="home-card-title">导入 PDF / Word</span>
        <span class="home-card-desc">上传文档，AI 解析成可编辑简历</span>
      </button>

      <!-- 导入 JSON -->
      <button class="home-card" @click="pickJson">
        <span class="home-card-icon">📦</span>
        <span class="home-card-title">导入 JSON</span>
        <span class="home-card-desc">读取本地的简历 JSON 文件</span>
      </button>

      <!-- 新建 -->
      <button class="home-card" @click="onNew">
        <span class="home-card-icon">✨</span>
        <span class="home-card-title">新建空白简历</span>
        <span class="home-card-desc">从零开始搭建</span>
      </button>
    </div>

    <p class="home-privacy">
      🔒 你的简历只存在本机浏览器里，不收集任何数据；仅在使用 AI 功能时，内容才会发送到你配置的模型服务商
    </p>

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
          💡 目前 AI 识别还不够准，解析结果可能出错。若要用解析，建议优先选
          MinerU；最稳的方式是直接「新建」手动搭建简历。
        </p>
        <div class="import-dialog-row">
          <span class="import-dialog-label">解析引擎</span>
          <n-radio-group v-model:value="parser" size="small">
            <n-radio-button value="docling">docling（本地解析）</n-radio-button>
            <n-radio-button value="mineru">MinerU（云解析）</n-radio-button>
          </n-radio-group>
        </div>
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
        <p v-if="parser === 'docling'" class="progress-advice">
          建议使用 MinerU 以及更强的推理模型加速解析
        </p>
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
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 40px;
  padding: 24px;
  overflow: auto;
}

.home-hero {
  text-align: center;
}
.home-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.home-brand-icon {
  font-size: 34px;
}
.home-brand h1 {
  margin: 0;
  font-size: 34px;
  color: #1f2937;
}
.home-sub {
  margin: 12px 0 0;
  font-size: 15px;
  color: #6b7280;
}
.home-hint {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--primary);
}
.home-privacy {
  margin: 0;
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
  line-height: 1.6;
  max-width: 460px;
}

.home-cards {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  justify-content: center;
}

.import-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 4px;
}
.import-tip {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 8px 10px;
}
.import-dialog-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.import-dialog-label {
  flex: none;
  font-size: 13px;
  color: #374151;
}
.home-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  width: 220px;
  padding: 32px 24px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: #fff;
  cursor: pointer;
  transition:
    transform 0.15s,
    box-shadow 0.15s,
    border-color 0.15s;
}
.home-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
}
.home-card-icon {
  font-size: 30px;
}
.home-card-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}
.home-card-desc {
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
}

.progress-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.progress-estimate {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
}
.progress-tip {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
}
.progress-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.progress-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #374151;
}
.progress-icon {
  width: 16px;
  text-align: center;
  font-weight: 700;
}
.step-done .progress-icon {
  color: #16a34a;
}
.step-failed .progress-icon {
  color: #dc2626;
}
.step-running .progress-icon {
  color: var(--primary);
}
.step-pending .progress-icon {
  color: #d1d5db;
}
.progress-error {
  margin: 0;
  font-size: 13px;
  color: #dc2626;
}
.progress-actions {
  display: flex;
  justify-content: flex-end;
}
.progress-advice {
  margin: 0;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.5;
}

.hidden-input {
  display: none;
}
</style>
