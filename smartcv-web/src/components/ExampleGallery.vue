<script setup lang="ts">
/**
 * 示例模板画廊 —— 主页「加载示例」卡片打开的弹层。
 *
 * 设计要点：
 *   1. 缩略图是【真实渲染】而不是图片：直接把示例 JSON 喂给 PreviewSection 渲染，
 *      所以新增示例永远不需要重新生成图片，看到的缩略图就是导入后的样子。
 *      （PreviewSection → PreviewLayoutWindow → PreviewContent 整条链都不读 store，
 *       只吃 props，所以渲染别人的简历不会碰到用户当前编辑的那一份。）
 *   2. 卡片用 CSS Grid 的 auto-fill 排版：示例多了自动折行，代码不用动。
 *   3. 缩略图懒加载：卡片滚进可视区才去下载 JSON，示例变多也不拖慢打开速度。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { dialog, message } from '@/utils/feedback'
import { clearExampleCache, listExamples, loadExample, toSections, type ExampleItem } from '@/api/examples'
import { useResumeStore } from '@/stores/resume'
import { PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'
import PreviewSection from './PreviewSection.vue'
import type { Section } from '@/types'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [boolean]; enter: [] }>()

const store = useResumeStore()

/** 缩略图缩放比：卡片内容宽约 238px ÷ A4 宽 794px ≈ 0.3 */
const THUMB_ZOOM = 0.3

/** 画廊卡片：一份示例 + 它的加载状态 */
interface Card {
  item: ExampleItem
  state: 'pending' | 'loading' | 'ready' | 'error'
  sections: Section[]
  error?: string
}

const cards = ref<Card[]>([])
/** 整个清单的加载状态（列目录失败时整页报错，而不是每张卡各报各的） */
const listState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const listError = ref('')

/** 滚动容器：既是画廊的滚动区，也是懒加载 IntersectionObserver 的 root */
const bodyEl = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

/** 缩略图内层样式：铺满 A4 宽度，靠 zoom 缩到卡片大小 */
const thumbStyle = {
  width: `${PAGE_WIDTH}px`,
  minHeight: `${PAGE_HEIGHT}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: THUMB_ZOOM,
}

/** 按需创建 observer（root 是弹层里的滚动区，不是视口） */
function ensureObserver(): IntersectionObserver | null {
  if (observer) return observer
  if (!bodyEl.value) return null
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        observer?.unobserve(entry.target)
        const index = Number((entry.target as HTMLElement).dataset.index)
        void loadCard(index)
      }
    },
    // 提前 200px 触发，滚到底部时下一张已经开始加载了
    { root: bodyEl.value, rootMargin: '200px' },
  )
  return observer
}

/** 卡片 DOM 挂载时的回调：登记下标并交给 observer 盯着 */
function observeCard(el: unknown, index: number) {
  if (!(el instanceof HTMLElement)) return
  el.dataset.index = String(index)
  if (cards.value[index]?.state !== 'pending') return
  ensureObserver()?.observe(el)
}

/** 下载并渲染某张卡片的缩略图 */
async function loadCard(index: number) {
  const card = cards.value[index]
  if (!card || card.state !== 'pending') return
  card.state = 'loading'
  try {
    const sections = toSections(await loadExample(card.item))
    if (!sections) throw new Error('文件内容不是合法的简历数据')
    card.sections = sections
    card.state = 'ready'
  } catch (err) {
    card.error = err instanceof Error ? err.message : '加载失败'
    card.state = 'error'
  }
}

/** 拉取示例清单（force = true 跳过缓存，内容和清单一起作废） */
async function refresh(force = false) {
  listState.value = 'loading'
  listError.value = ''
  cards.value = []
  if (force) {
    // 不这么做的话：清单刷了，缩略图还是旧 JSON（contentCache + raw 的 HTTP 缓存）
    clearExampleCache()
    observer?.disconnect()
    observer = null
  }
  try {
    const items = await listExamples(force)
    cards.value = items.map((item) => ({ item, state: 'pending', sections: [] }))
    listState.value = 'ready'
    await nextTick() // 等卡片渲染出来，ref 回调才会把懒加载挂上
  } catch (err) {
    listError.value = err instanceof Error ? err.message : '示例列表加载失败'
    listState.value = 'error'
  }
}

/* 每次打开：首次拉清单；关闭时拆掉 observer，避免盯着已卸载的 DOM */
watch(
  () => props.show,
  (show) => {
    if (!show) {
      observer?.disconnect()
      observer = null
      return
    }
    if (listState.value !== 'ready') void refresh()
  },
)

onBeforeUnmount(() => observer?.disconnect())

/** 已有简历时先问一句：载入示例会整份替换掉当前内容 */
function confirmReplace(title: string): Promise<boolean> {
  return new Promise((resolve) => {
    dialog.warning({
      title: '替换当前简历？',
      content: `当前编辑器里已有 ${store.resume.length} 个章节，载入示例「${title}」会整份替换掉它（载入后仍可按 Ctrl+Z 撤销）。`,
      positiveText: '替换',
      negativeText: '取消',
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    })
  })
}

/** 点缩略图 = 直接用这份模板 */
async function pick(card: Card) {
  if (card.state === 'error') {
    card.state = 'pending'
    card.error = undefined
    void loadCard(cards.value.indexOf(card))
    return
  }
  if (card.state !== 'ready') return

  if (store.resume.length > 0 && !(await confirmReplace(card.item.title))) return

  if (!store.importResume(card.sections)) {
    message.error('导入失败：示例数据不是合法的简历数据')
    return
  }
  message.success(`已载入示例「${card.item.title}」`)
  emit('update:show', false)
  emit('enter')
}

/** 体积显示：KB 取整 */
const formatSize = (bytes: number) => `${Math.max(1, Math.round(bytes / 1024))} KB`
</script>

<template>
  <n-modal
    :show="props.show"
    display-directive="if"
    :mask-closable="false"
    preset="card"
    title="示例模板"
    style="width: 960px; max-width: 92vw"
    @update:show="emit('update:show', $event)"
  >
    <div ref="bodyEl" class="example-body">
      <!-- 清单加载中 -->
      <div v-if="listState === 'loading'" class="example-status">
        <n-spin size="small" />
        <span>正在获取示例列表…</span>
      </div>

      <!-- 清单加载失败：给出原因和重试 -->
      <div v-else-if="listState === 'error'" class="example-status">
        <span class="example-status-icon">⚠️</span>
        <span>{{ listError }}</span>
        <n-button size="small" @click="refresh(true)">重试</n-button>
      </div>

      <!-- 目录下没有示例文件 -->
      <div v-else-if="listState === 'ready' && cards.length === 0" class="example-status">
        <span class="example-status-icon">📭</span>
        <span>仓库 example/ 目录下还没有示例文件</span>
      </div>

      <!-- 示例网格：auto-fill 自动折行，加示例不用改代码 -->
      <div v-else class="example-grid">
        <button
          v-for="(card, i) in cards"
          :key="card.item.name"
          :ref="(el) => observeCard(el, i)"
          class="example-card"
          @click="pick(card)"
        >
          <div class="example-thumb">
            <!-- 真实渲染的缩略图 -->
            <div v-if="card.state === 'ready'" class="example-paper" :style="thumbStyle">
              <PreviewSection v-for="s in card.sections" :key="s.id" :section="s" />
            </div>

            <!-- 加载中 / 失败 -->
            <div v-else class="example-thumb-mask">
              <template v-if="card.state === 'error'">
                <span class="example-status-icon">⚠️</span>
                <span class="example-thumb-text">{{ card.error }}</span>
                <span class="example-thumb-retry">点击重试</span>
              </template>
              <template v-else>
                <n-spin size="small" />
                <span class="example-thumb-text">加载中…</span>
              </template>
            </div>
          </div>

          <div class="example-meta">
            <span class="example-title">{{ card.item.title }}</span>
            <span class="example-size">{{ formatSize(card.item.size) }}</span>
          </div>
        </button>
      </div>
    </div>

    <!-- 刷新：作废清单 + 已下载内容，用于刚往 example/ 推了新示例 / 改了示例之后 -->
    <template #header-extra>
      <n-button
        size="small"
        quaternary
        :loading="listState === 'loading'"
        @click="refresh(true)"
      >
        刷新
      </n-button>
    </template>

    <template #footer>
      <span class="example-footer-tip">点击缩略图直接使用，载入后可以继续编辑</span>
    </template>
  </n-modal>
</template>

<style scoped>
.example-body {
  max-height: 62vh;
  overflow: auto;
  padding: 2px;
}

/* ---------- 状态提示（加载中 / 失败 / 空目录） ---------- */
.example-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 56px 0;
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
}
.example-status-icon {
  font-size: 24px;
}

/* ---------- 网格：列数自适应，示例变多自动折行 ---------- */
.example-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 18px;
}

.example-card {
  display: flex;
  flex-direction: column;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  cursor: pointer;
  text-align: left;
  transition:
    transform 0.15s,
    box-shadow 0.15s,
    border-color 0.15s;
}
.example-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.1);
}

/* ---------- 缩略图：固定高度裁切 + 底部渐变，暗示「下面还有内容」 ---------- */
.example-thumb {
  position: relative;
  height: 340px;
  overflow: hidden;
  background: #eef1f6;
}
.example-thumb::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 56px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0), #fff);
  pointer-events: none;
}

/* A4 纸张：794px 宽（box-sizing: border-box 已全局生效，padding 用 A4 页边距） */
.example-paper {
  background: #fff;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.12);
}

.example-thumb-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 16px;
  background: #f7f9fc;
}
.example-thumb-text {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
  line-height: 1.5;
}
.example-thumb-retry {
  font-size: 12px;
  color: var(--primary);
}

/* ---------- 卡片底部信息 ---------- */
.example-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--border);
}
.example-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.example-size {
  flex: none;
  font-size: 11px;
  color: #9ca3af;
}

.example-footer-tip {
  font-size: 12px;
  color: #9ca3af;
}
</style>
