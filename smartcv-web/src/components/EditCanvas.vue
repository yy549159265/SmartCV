<script setup lang="ts">
/**
 * 中间 · 编辑画布
 *
 * 职责：
 *  - 章节从上到下排列，用 vue-draggable-plus 拖拽排序（按住 ⋮⋮ 手柄）；
 *  - 接收从组件库拖来的"章节预设"（add 事件里生成新章节）；
 *  - Delete 键删除选中内容。
 *
 * 拖拽用 vue-draggable-plus（内部 SortableJS）：
 *  - 章节列表的拖拽分组名 = smartcv-group（SortableJS 的 group 选项），只能接收"章节"类的拖入；
 *  - 布局/内容分别在各自的拖拽分组（smartcv-row / smartcv-content），互不串。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { onKeyStroke } from '@vueuse/core'
import { VueDraggable } from 'vue-draggable-plus'
import SectionCard from './SectionCard.vue'
import BrandMark from './BrandMark.vue'
import IconGlyph from './IconGlyph.vue'
import { useResumeStore } from '@/stores/resume'
import { createSectionFromPreset } from '@/data/presets'
import { message } from '@/utils/feedback'

const store = useResumeStore()

/* ============================================================
 * 拖拽自动滚动（画布上 / 下边缘）
 * ============================================================
 * 画布唯一会滚动的容器是 .canvas-scroll。SortableJS 自带的 auto-scroll
 * 触发区很小（scrollSensitivity 默认 30px），拖到顶部边缘时经常够不着，
 * 表现像"不会滚"。这里自己实现一套：拖拽期间监听指针，指针进入画布上下
 * 边缘区域就用 requestAnimationFrame 匀速滚动画布，松手即停。
 *
 * 通过 document 上 SortableJS 的 start / end 事件（会冒泡）判断拖拽
 * 是否在进行——无论拖章节、拖布局、还是从组件库拖入，都能覆盖到。
 * ============================================================ */

const scrollEl = ref<HTMLElement | null>(null)

/** 边缘触发区：指针距离画布上/下边缘多少像素内开始滚动 */
const EDGE_ZONE = 80
/** 贴着边缘时的最大滚动速度（px/帧，约 60fps → 840px/s） */
const MAX_SCROLL_SPEED = 14

let dragActive = false
let pointerX = 0
let pointerY = 0
let rafId = 0

function onPointerMove(e: PointerEvent) {
  pointerX = e.clientX
  pointerY = e.clientY
}

function tick() {
  rafId = 0
  if (!dragActive) return
  const el = scrollEl.value
  if (el) {
    const rect = el.getBoundingClientRect()
    // 指针水平位置落在画布列内才滚，避免在预览列 / 组件库列上方误触发
    if (pointerX >= rect.left && pointerX <= rect.right) {
      const fromTop = pointerY - rect.top
      const fromBottom = rect.bottom - pointerY
      let speed = 0
      if (fromTop >= 0 && fromTop < EDGE_ZONE && el.scrollTop > 0) {
        // 越贴顶越快，向上滚
        speed = -MAX_SCROLL_SPEED * (1 - fromTop / EDGE_ZONE)
      } else if (
        fromBottom >= 0 &&
        fromBottom < EDGE_ZONE &&
        el.scrollTop < el.scrollHeight - el.clientHeight
      ) {
        // 越贴底越快，向下滚
        speed = MAX_SCROLL_SPEED * (1 - fromBottom / EDGE_ZONE)
      }
      if (speed !== 0) el.scrollTop += speed
    }
  }
  rafId = requestAnimationFrame(tick)
}

function onDragStart(e: Event) {
  const oe = (e as { originalEvent?: { clientX?: number; clientY?: number } }).originalEvent
  if (oe && typeof oe.clientX === 'number' && typeof oe.clientY === 'number') {
    pointerX = oe.clientX
    pointerY = oe.clientY
  }
  dragActive = true
  if (!rafId) rafId = requestAnimationFrame(tick)
}

function onDragEnd() {
  dragActive = false
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = 0
  }
}

onMounted(() => {
  document.addEventListener('start', onDragStart)
  document.addEventListener('end', onDragEnd)
  window.addEventListener('pointermove', onPointerMove, { passive: true })
  // 拖拽中窗口失焦（切走 / 极小概率没触发 end）兜底停掉
  window.addEventListener('blur', onDragEnd)
})

onBeforeUnmount(() => {
  document.removeEventListener('start', onDragStart)
  document.removeEventListener('end', onDragEnd)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('blur', onDragEnd)
  onDragEnd()
})

/* ============================================================
 * 章节拖拽（vue-draggable-plus）
 * ============================================================ */

/** 按 id 找 vue-draggable-plus 插入的占位对象：它插入的是深拷贝（引用不同），indexOf 找不到 */
function indexOfId<T extends { id?: unknown }>(arr: T[], id: unknown): number {
  if (typeof id !== 'string') return -1
  return arr.findIndex((x) => x && x.id === id)
}

/** 从组件库拖入章节预设 → 生成真实章节 */
function onSectionAdd(evt: { data?: unknown; newIndex?: number }) {
  const preset = evt.data as { id?: unknown; name?: string; type?: unknown; layout?: unknown } | undefined
  // 这里只接收章节预设；类型不对清理占位
  if (!preset || typeof preset.name !== 'string' || preset.type !== undefined || preset.layout !== undefined) {
    const i = indexOfId(store.resume, preset?.id)
    if (i >= 0) store.resume.splice(i, 1)
    message.warning('这里只能放章节（从组件库「章节」分组拖入）')
    return
  }
  // vue-draggable-plus 内部已把预设的深拷贝同步插进 store.resume，这里原位替换成真实章节
  const real = createSectionFromPreset(preset as never)
  const arr = store.resume
  const i = indexOfId(arr, preset.id)
  if (i >= 0) {
    arr.splice(i, 1, real)
  } else {
    // 兜底：克隆体就落在 newIndex 上，原位替换即可（不能"插入"，否则会多一份）
    arr.splice(Math.min(evt.newIndex ?? arr.length, arr.length), 1, real)
  }
  store.select(real.id)
}

/* ============================================================
 * 键盘快捷键：Delete 删除选中内容
 * ============================================================ */

onKeyStroke('Delete', () => {
  // 正在输入框里打字时按 Delete 是删除文字，不能误删内容
  const active = document.activeElement as HTMLElement | null
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) {
    return
  }
  const section = store.selectedSection
  if (section) {
    store.removeSection(section.id)
    message.success('章节已删除')
    return
  }
  const row = store.selectedRow
  if (row) {
    store.removeRow(row.section.id, row.row.id)
    message.success('布局窗口已删除')
    return
  }
  const sel = store.selectedContent
  if (sel) {
    store.removeContent(sel.section.id, sel.content.id)
    message.success('内容已删除')
  }
})
</script>

<template>
  <section class="canvas">
    <div class="canvas-toolbar">
      <span class="canvas-title-icon"><IconGlyph name="pen-line" :size="15" /></span>
      <span class="canvas-title">编辑画布</span>
      <span class="canvas-hint">从上方组件库点击添加，或拖到指定位置；拖动 ⋮⋮ 手柄排序</span>
    </div>

    <div ref="scrollEl" class="canvas-scroll">
      <!-- 画布纸面：白色区域，宽度填满画布列（随列宽拉伸） -->
      <div class="canvas-sheet" @click.self="store.select(null)">
        <div class="section-list">
          <!-- 章节列表：按住 ⋮⋮ 手柄排序；从组件库「章节」分组拖入 = 生成新章节 -->
          <VueDraggable
            v-model="store.resume"
            :group="{ name: 'smartcv-group', put: ['smartcv-group'] }"
            handle=".section-drag-handle"
            :animation="200"
            class="section-list-inner"
            @add="onSectionAdd"
          >
            <SectionCard v-for="g in store.resume" :key="g.id" :section="g" />
          </VueDraggable>

          <!-- 空画布提示 -->
          <div v-if="store.resume.length === 0" class="canvas-empty">
            <BrandMark :size="36" class="canvas-empty-mark" />
            <p>
              画布是空的<br />
              从上方组件库点击或拖入章节开始
            </p>
          </div>

        </div>
      </div>

      <!-- 画布底部留白 -->
      <div class="canvas-bottom-space" />
    </div>
  </section>
</template>

<style scoped>
.canvas {
  display: flex;
  flex-direction: column;
  /* 占满组件库下方的剩余高度；min-height: 0 让内部滚动区能收缩并出现滚动条 */
  flex: 1;
  min-height: 0;
  min-width: 0;
  background: var(--surface-sunken);
  /* 只作为容器查询的参照，不影响列宽（列宽由拖动分隔条决定） */
  container-type: inline-size;
}

/* 画布工具栏：与组件库面板头部同款格式（图标块 + 粗标题 + 说明） */
.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 14px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
}
.canvas-title-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--primary-soft);
  color: var(--primary);
}
.canvas-title {
  flex: none;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text);
}
.canvas-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  /* 画布列被拖窄时截断提示文字，而不是折行把工具栏撑高 */
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.canvas-scroll {
  flex: 1;
  overflow: auto;
  padding: 24px 16px 56px;
}

/* 画布纸面：填满画布列（随列宽拉伸，拖动分隔条可以把它调宽/调窄） */
.canvas-sheet {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1000px; /* 上限：防止预览缩到最小时卡片被拉得过长 */
  margin: 0 auto;
  padding: 20px 16px 28px;
  background: var(--panel-bg);
  border-radius: var(--radius-lg);
  /* 用发丝环 + 极淡纸影代替硬投影；box-shadow 不参与布局 */
  box-shadow:
    0 0 0 1px var(--border),
    var(--shadow-paper);
}

/* 章节列表铺满整张纸，空白处也能落点；卡片随纸面一起变宽 */
.section-list {
  position: relative;
  flex: 1;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}
.section-list-inner {
  flex: 1;
  /* 空画布也有足够大的可落点区域（否则清空后拖不进章节） */
  min-height: 240px;
  display: flex;
  flex-direction: column;
  /* 章节间距不再用固定 gap，改由 spaceBefore（章节间距滑块）控制 */
  gap: 0;
}

/* 空画布提示：铺满整块画布区并居中，避免顶部留一大块空白 */
.canvas-empty {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
  color: var(--text-tertiary);
  pointer-events: none;
}
.canvas-empty-mark {
  opacity: 0.35;
}
.canvas-empty p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.8;
}

/* 画布底部缓冲空间（拖拽自动滚动的目标余量） */
.canvas-bottom-space {
  height: 24px;
}
</style>
