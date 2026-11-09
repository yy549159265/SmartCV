<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useWindowSize } from '@vueuse/core'
import IconGlyph from '@/components/IconGlyph.vue'
import PreviewSection from '@/components/PreviewSection.vue'
import { message } from '@/utils/feedback'
import { toSections } from '@/api/examples'
import { analyzeResume } from '@/api/analyze'
import {
  createReferenceExample,
  getReferenceExample,
  listReferenceExamples,
  type ReferenceExampleMeta,
} from '@/api/referenceExamples'
import { PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'
import type { Section } from '@/types'

const props = withDefaults(defineProps<{ prefillJson?: string }>(), { prefillJson: '' })
const emit = defineEmits<{ 'prefill-consumed': [] }>()

const THUMB_ZOOM = 250 / PAGE_WIDTH

interface Card {
  meta: ReferenceExampleMeta
  state: 'pending' | 'loading' | 'ready' | 'error'
  sections: Section[]
  error?: string
}

const cards = ref<Card[]>([])
const listState = ref<'loading' | 'ready' | 'error'>('loading')
const listError = ref('')

const pageEl = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

const thumbStyle = {
  width: `${PAGE_WIDTH}px`,
  minHeight: `${PAGE_HEIGHT}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: THUMB_ZOOM,
}

function ensureObserver(): IntersectionObserver | null {
  if (observer) return observer
  if (!pageEl.value) return null
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        observer?.unobserve(entry.target)
        const index = Number((entry.target as HTMLElement).dataset.index)
        void loadCard(index)
      }
    },
    { root: pageEl.value, rootMargin: '300px' },
  )
  return observer
}

function observeCard(el: unknown, index: number) {
  if (!(el instanceof HTMLElement)) return
  el.dataset.index = String(index)
  if (cards.value[index]?.state !== 'pending') return
  ensureObserver()?.observe(el)
}

async function loadCard(index: number) {
  const card = cards.value[index]
  if (!card || card.state !== 'pending') return
  card.state = 'loading'
  try {
    const detail = await getReferenceExample(card.meta.id)
    const sections = toSections(detail.resume)
    if (!sections) throw new Error('示例内容不是合法的简历数据')
    card.sections = sections
    card.state = 'ready'
  } catch (err) {
    card.error = err instanceof Error ? err.message : '加载失败'
    card.state = 'error'
  }
}

async function refresh() {
  listState.value = 'loading'
  listError.value = ''
  cards.value = []
  observer?.disconnect()
  observer = null
  try {
    const list = await listReferenceExamples()
    cards.value = list.map((meta) => ({ meta, state: 'pending', sections: [] }))
    listState.value = 'ready'
    await nextTick()
  } catch (err) {
    listError.value = err instanceof Error ? err.message : '示例列表加载失败'
    listState.value = 'error'
  }
}

onMounted(() => {
  void refresh()
  if (props.prefillJson) {
    form.jsonText = props.prefillJson
    validateJson()
    uploadShow.value = true
    emit('prefill-consumed')
  }
})
onBeforeUnmount(() => observer?.disconnect())

function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

const detailShow = ref(false)
const detailIndex = ref(-1)
const detailCard = computed(() => cards.value[detailIndex.value] ?? null)

const { width: viewportWidth } = useWindowSize()
const detailZoom = computed(() =>
  Math.min(1, Math.max(0.5, (viewportWidth.value - 150) / PAGE_WIDTH)),
)
const detailPaperStyle = computed(() => ({
  width: `${PAGE_WIDTH}px`,
  minHeight: `${PAGE_HEIGHT}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: detailZoom.value,
}))

function openDetail(card: Card) {
  const index = cards.value.indexOf(card)
  detailIndex.value = index
  detailShow.value = true
  if (card.state === 'pending') void loadCard(index)
  else if (card.state === 'error') retry(card)
}

function retry(card: Card) {
  card.state = 'pending'
  card.error = undefined
  void loadCard(cards.value.indexOf(card))
}

const uploadShow = ref(false)
const jsonInputEl = ref<HTMLInputElement | null>(null)
const form = reactive({ direction: '', description: '', jsonText: '' })
const parsedSections = ref<Section[] | null>(null)
const parseError = ref('')

const analyzing = ref(false)

const canAnalyze = computed(() => !!parsedSections.value && !analyzing.value)

async function runAnalyze() {
  if (!canAnalyze.value) {
    message.warning(parsedSections.value ? '正在分析，请稍候' : '请先上传有效的简历 JSON')
    return
  }

  analyzing.value = true
  try {
    const result = await analyzeResume(parsedSections.value!)
    if (!result.direction && !result.highlights) {
      throw new Error('分析结果为空，请稍后重试')
    }
    form.direction = result.direction
    form.description = result.highlights
    message.success('分析完成，已填入职业名称与可借鉴写法')
  } catch (err) {
    message.error(err instanceof Error ? err.message : '简历分析失败')
  } finally {
    analyzing.value = false
  }
}

function resetForm() {
  form.direction = ''
  form.description = ''
  form.jsonText = ''
  parsedSections.value = null
  parseError.value = ''
  if (jsonInputEl.value) jsonInputEl.value.value = ''
}

function openUpload() {
  resetForm()
  uploadShow.value = true
}

function pickJson() {
  jsonInputEl.value?.click()
}

function onJsonFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    form.jsonText = String(reader.result ?? '')
    validateJson()
  }
  reader.onerror = () => message.error('文件读取失败，请重试')
  reader.readAsText(file)
}

function onJsonTextInput() {
  parsedSections.value = null
  parseError.value = ''
}

function validateJson(): boolean {
  const text = form.jsonText.trim()
  if (!text) {
    parsedSections.value = null
    parseError.value = '请上传 JSON'
    return false
  }
  try {
    const sections = toSections(JSON.parse(text))
    if (!sections) throw new Error('顶层必须是非空章节数组，且每个章节包含 rows 数组')
    parsedSections.value = sections
    parseError.value = ''
    return true
  } catch (err) {
    parsedSections.value = null
    parseError.value = `JSON 无法解析：${err instanceof Error ? err.message : '格式不正确'}`
    return false
  }
}

const previewShow = ref(false)
const previewSections = ref<Section[]>([])
const previewDirection = ref('')
const previewDescription = ref('')
const submitting = ref(false)

function goPreview() {
  if (!form.direction.trim()) {
    message.warning('请填写职业名称')
    return
  }
  if (!form.description.trim()) {
    message.warning('请填写可借鉴的写法')
    return
  }
  if (!validateJson() || !parsedSections.value) return

  previewDirection.value = form.direction.trim()
  previewDescription.value = form.description.trim()
  previewSections.value = parsedSections.value
  uploadShow.value = false
  previewShow.value = true
}

function backToForm() {
  previewShow.value = false
  uploadShow.value = true
}

async function confirmUpload() {
  if (submitting.value) return
  submitting.value = true
  try {
    await createReferenceExample({
      direction: previewDirection.value,
      description: previewDescription.value,
      resume: previewSections.value,
    })
    previewShow.value = false
    resetForm()
    message.success('已加入优秀示例库')
    await refresh()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '上传失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div ref="pageEl" class="ref-page">
    <div class="ref-container">
      <header class="ref-head">
        <div class="ref-head-copy">
          <h1 class="ref-title">优秀示例库</h1>
          <p class="ref-desc">
            优化时最多挑选 3 份参考；AI 只借鉴写作方式与结构，不借用其中的事实。
          </p>
        </div>
        <div class="ref-head-actions">
          <span v-if="listState === 'ready'" class="ref-count">共 {{ cards.length }} 份</span>
          <button type="button" class="ref-upload-btn" @click="openUpload">
            <IconGlyph name="file-plus-2" :size="15" />
            上传示例
          </button>
        </div>
      </header>

      <div class="ref-note">
        <IconGlyph name="shield-check" :size="14" />
        <span>示例库全局共享；提交后不可编辑、不可删除。</span>
      </div>

      <div v-if="listState === 'loading'" class="ref-status">
        <n-spin size="small" />
        <span>正在读取示例库…</span>
      </div>

      <div v-else-if="listState === 'error'" class="ref-status">
        <span>{{ listError }}</span>
        <n-button size="small" @click="refresh">重试</n-button>
      </div>

      <div v-else-if="cards.length === 0" class="ref-empty">
        <span class="ref-empty-icon"><IconGlyph name="layout-template" :size="22" /></span>
        <p class="ref-empty-title">示例库还是空的</p>
        <p class="ref-empty-desc">上传第一份优秀简历，之后优化时可以把它选为写作参考。</p>
        <button type="button" class="ref-upload-btn" @click="openUpload">
          <IconGlyph name="file-plus-2" :size="15" />
          上传示例
        </button>
      </div>

      <div v-else class="ref-grid">
        <button
          v-for="(card, i) in cards"
          :key="card.meta.id"
          :ref="(el) => observeCard(el, i)"
          type="button"
          class="ref-card"
          @click="openDetail(card)"
        >
          <div class="ref-thumb">
            <div v-if="card.state === 'ready'" class="ref-paper" :style="thumbStyle">
              <PreviewSection v-for="(s, si) in card.sections" :key="si" :section="s" />
            </div>
            <div v-else class="ref-thumb-mask">
              <template v-if="card.state === 'error'">
                <span class="ref-thumb-text">{{ card.error }}</span>
                <span class="ref-thumb-retry">点击重试</span>
              </template>
              <template v-else>
                <n-spin size="small" />
                <span class="ref-thumb-text">加载中…</span>
              </template>
            </div>
          </div>

          <div class="ref-card-body">
            <div class="ref-card-top">
              <span class="ref-direction">{{ card.meta.direction }}</span>
              <span class="ref-date">{{ formatDate(card.meta.createdAt) }}</span>
            </div>
            <p class="ref-card-desc">{{ card.meta.description }}</p>
            <div class="ref-card-meta">
              <span>{{ card.meta.sectionCount }} 个章节</span>
              <span class="ref-readonly">只读</span>
            </div>
          </div>
        </button>
      </div>
    </div>

    <n-modal
      v-model:show="detailShow"
      display-directive="if"
      preset="card"
      style="width: 1040px; max-width: 94vw"
    >
      <template #header>
        <div class="ref-modal-head">
          <span class="ref-modal-title">优秀示例</span>
          <span v-if="detailCard" class="ref-direction">{{ detailCard.meta.direction }}</span>
          <span class="ref-readonly">只读</span>
        </div>
      </template>

      <div v-if="detailCard" class="ref-detail">
        <p class="ref-detail-desc">{{ detailCard.meta.description }}</p>
        <div class="ref-detail-paper-wrap">
          <div v-if="detailCard.state === 'ready'" class="ref-paper" :style="detailPaperStyle">
            <PreviewSection v-for="(s, si) in detailCard.sections" :key="si" :section="s" />
          </div>
          <div v-else class="ref-status">
            <template v-if="detailCard.state === 'error'">
              <span>{{ detailCard.error }}</span>
              <n-button size="small" @click="retry(detailCard)">重试</n-button>
            </template>
            <template v-else>
              <n-spin size="small" />
              <span>正在加载示例内容…</span>
            </template>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="ref-modal-footer">
          <span class="ref-modal-hint">示例内容仅供优化参考，不可编辑或删除</span>
          <n-button size="small" type="primary" @click="detailShow = false">关闭</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal
      v-model:show="uploadShow"
      display-directive="if"
      :mask-closable="false"
      preset="card"
      style="width: 680px; max-width: 94vw"
    >
      <template #header>
        <div class="ref-modal-head">
          <span class="ref-modal-title">上传优秀示例</span>
          <span class="ref-step">第 1 步 / 共 2 步</span>
        </div>
      </template>

      <div class="ref-form">
        <div class="ref-field">
          <span class="ref-field-label">
            职业名称
            <n-tooltip trigger="hover">
              <template #trigger>
                <span class="ref-field-info" tabindex="0">
                  <IconGlyph name="info" :size="13" />
                </span>
              </template>
              最多 60 字，填招聘网站上能搜到的岗位名，如「后端开发工程师」
            </n-tooltip>
          </span>
          <n-input
            v-model:value="form.direction"
            maxlength="60"
            show-count
            placeholder="如 后端开发工程师"
          />
        </div>

        <div class="ref-field">
          <span class="ref-field-label">
            可借鉴的写法
            <n-tooltip trigger="hover">
              <template #trigger>
                <span class="ref-field-info" tabindex="0">
                  <IconGlyph name="info" :size="13" />
                </span>
              </template>
              这份示例的可迁移写作规范（最多 2000 字）；优化时会作为示例说明交给 AI
            </n-tooltip>
          </span>
          <n-input
            v-model:value="form.description"
            type="textarea"
            maxlength="2000"
            show-count
            :autosize="{ minRows: 3, maxRows: 7 }"
            placeholder="如：1. 先给项目定位…&#10;2. 用版本号讲架构演进…"
          />
        </div>

        <div class="ref-field">
          <span class="ref-field-label">
            上传JSON
            <n-tooltip trigger="hover">
              <template #trigger>
                <span class="ref-field-info" tabindex="0">
                  <IconGlyph name="info" :size="13" />
                </span>
              </template>
              与「导出 JSON」格式一致；可选文件或填入内容
            </n-tooltip>
          </span>
          <div class="ref-json-actions">
            <n-button size="small" @click="pickJson">
              <IconGlyph name="file-json" :size="14" />
              选择文件
            </n-button>
            <n-button
              size="small"
              type="primary"
              secondary
              :disabled="!parsedSections || analyzing"
              :loading="analyzing"
              @click="runAnalyze"
            >
              <IconGlyph v-if="!analyzing" name="sparkles" :size="14" />
              AI 分析
            </n-button>
            <span v-if="parsedSections" class="ref-json-ok">
              ✓ 已识别 {{ parsedSections.length }} 个章节
            </span>
          </div>
          <n-input
            v-model:value="form.jsonText"
            class="ref-json-input"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 12 }"
            placeholder="JSON 内容"
            @update:value="onJsonTextInput"
          />
          <p v-if="parseError" class="ref-json-error">{{ parseError }}</p>
          <p v-else-if="!parsedSections" class="ref-json-hint">
            先上传或粘贴简历 JSON，才能使用 AI 分析
          </p>
        </div>
      </div>

      <template #footer>
        <div class="ref-modal-footer">
          <div class="ref-modal-actions">
            <n-button size="small" @click="uploadShow = false">取消</n-button>
            <n-button size="small" type="primary" @click="goPreview">预览并下一步</n-button>
          </div>
        </div>
      </template>
    </n-modal>

    <n-modal
      v-model:show="previewShow"
      display-directive="if"
      :mask-closable="false"
      preset="card"
      style="width: 1040px; max-width: 94vw"
    >
      <template #header>
        <div class="ref-modal-head">
          <span class="ref-modal-title">确认上传</span>
          <span class="ref-step">第 2 步 / 共 2 步</span>
          <span class="ref-direction">{{ previewDirection }}</span>
        </div>
      </template>

      <div class="ref-preview">
        <div class="ref-warning">
          <IconGlyph name="shield-check" :size="14" />
          <span>示例库全局共享，没有用户区分；提交后不可编辑、不可删除，请确认内容无误。</span>
        </div>
        <p class="ref-preview-desc">{{ previewDescription }}</p>
        <div class="ref-detail-paper-wrap">
          <div class="ref-paper" :style="detailPaperStyle">
            <PreviewSection v-for="(s, si) in previewSections" :key="si" :section="s" />
          </div>
        </div>
      </div>

      <template #footer>
        <div class="ref-modal-footer">
          <span class="ref-modal-hint">共 {{ previewSections.length }} 个章节</span>
          <div class="ref-modal-actions">
            <n-button size="small" :disabled="submitting" @click="backToForm">返回修改</n-button>
            <n-button size="small" type="primary" :loading="submitting" @click="confirmUpload">
              确认上传
            </n-button>
          </div>
        </div>
      </template>
    </n-modal>

    <input
      ref="jsonInputEl"
      type="file"
      accept="application/json,.json"
      class="ref-hidden-input"
      @change="onJsonFile"
    />
  </div>
</template>

<style scoped>
.ref-page {
  height: 100%;
  overflow: auto;
}
.ref-container {
  width: min(1120px, 100%);
  margin: 0 auto;
  padding: 36px 28px 56px;
}

.ref-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}
.ref-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--text);
}
.ref-desc {
  margin: 9px 0 0;
  max-width: 660px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.ref-head-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 2px;
}
.ref-count {
  font-size: 12px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ref-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 38px;
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
.ref-upload-btn:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px -10px rgba(71, 83, 199, 0.55);
}
.ref-upload-btn:active {
  background: #343da0;
  transform: translateY(0);
}

.ref-note {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.ref-note .icon-glyph {
  color: var(--text-tertiary);
}

.ref-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 16px;
  font-size: 12.5px;
  color: var(--text-secondary);
  text-align: center;
}

.ref-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  padding: 64px 24px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface-soft);
  text-align: center;
}
.ref-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  margin-bottom: 4px;
  border-radius: 13px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  color: var(--primary);
}
.ref-empty-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.ref-empty-desc {
  margin: 0 0 10px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.ref-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 18px;
  margin-top: 20px;
}
.ref-card {
  display: flex;
  flex-direction: column;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--panel-bg);
  overflow: hidden;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease),
    transform 0.16s var(--ease);
}
.ref-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: var(--shadow-raised);
}
.ref-thumb {
  position: relative;
  height: 300px;
  overflow: hidden;
  display: flex;
  justify-content: center;
  background: var(--surface-soft);
}
.ref-thumb::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 52px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0), var(--panel-bg));
  pointer-events: none;
}
.ref-paper {
  background: #fff;
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.06);
}
.ref-thumb-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 16px;
}
.ref-thumb-text {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  text-align: center;
}
.ref-thumb-retry {
  font-size: 12px;
  color: var(--primary);
}

.ref-card-body {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 11px 13px 12px;
  border-top: 1px solid var(--border);
}
.ref-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ref-direction {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-hover);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ref-date {
  flex: none;
  font-size: 10.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ref-card-desc {
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.ref-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.ref-readonly {
  padding: 1px 7px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 10px;
  color: var(--text-tertiary);
}

.ref-modal-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.ref-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.ref-step {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-sunken);
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.ref-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}
.ref-modal-hint {
  flex: 1;
  font-size: 11px;
  color: var(--text-tertiary);
}
.ref-modal-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ref-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ref-detail-desc {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.ref-detail-paper-wrap {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  max-height: 64vh;
  overflow: auto;
  padding: 24px;
  border-radius: 10px;
  background: var(--doc-workspace);
}

.ref-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 4px;
}
.ref-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ref-field-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.ref-field-info {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  color: var(--text-tertiary);
  cursor: help;
  transition:
    color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.ref-field-info:hover,
.ref-field-info:focus-visible {
  color: var(--primary);
  background: var(--primary-faint);
  outline: none;
}
.ref-json-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.ref-json-ok {
  font-size: 11.5px;
  color: var(--success);
}
.ref-json-input :deep(.n-input__textarea-el) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.6;
}
.ref-json-error {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--danger);
  overflow-wrap: anywhere;
}
.ref-json-hint {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}

.ref-preview {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ref-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid rgba(166, 118, 63, 0.22);
  border-radius: 10px;
  background: var(--warning-soft);
  font-size: 12px;
  line-height: 1.6;
  color: var(--warning);
}
.ref-warning .icon-glyph {
  flex: none;
  margin-top: 2px;
}
.ref-preview-desc {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 120px;
  overflow-y: auto;
}

.ref-hidden-input {
  display: none;
}

@media (max-width: 720px) {
  .ref-container {
    padding: 28px 18px 44px;
  }
  .ref-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
  .ref-head-actions {
    width: 100%;
    justify-content: space-between;
  }
  .ref-detail-paper-wrap {
    padding: 14px;
  }
}
</style>
