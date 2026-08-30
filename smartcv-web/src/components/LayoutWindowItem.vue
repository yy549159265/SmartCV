<script setup lang="ts">
/**
 * 布局窗口（编辑态，递归组件）
 *
 * 两种形态：
 *  - 叶子窗口（🧩 窗口布局）：放内容（ContentCard 列表）；
 *  - 横排（⇋ 横排）：由 ＋左/＋右 自动形成，放多个布局窗口并排。
 *
 * 窗口头部：⋮⋮ 手柄拖动窗口、删除窗口；
 * 窗口四周有 ＋ 按钮添加相邻窗口（悬停窗口即显示）。
 * 排列规则（不需要"容器"概念）：
 *  - ＋上 / ＋下 = 上下堆叠（新的一行）；
 *  - ＋左 / ＋右 = 左右并排（自动形成横排）。
 *
 * 拖拽用 vue-draggable-plus（内部 SortableJS）：
 *  - 横排里的布局窗口列表 / 叶子窗口里的内容列表都可拖拽排序；
 *  - 从组件库「布局」分组拖入横排 = 加一个布局窗口；
 *  - 从组件库「内容」分组拖入叶子窗口 = 加一个内容。
 */
import { computed, nextTick } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import ContentCard from './ContentCard.vue'
import { useResumeStore } from '@/stores/resume'
import { createContentFromPreset, createRowFromPreset } from '@/data/presets'
import { computeTableCols, spanForIndex } from '@/utils/layout'
import type { Section, LayoutWindow, SectionLayout } from '@/types'
import { message } from '@/utils/feedback'

const props = defineProps<{
  section: Section
  row: LayoutWindow
  /** 父级窗口的排列方向（决定"前/后"是上下还是左右）；顶层默认竖向 */
  parentDirection?: SectionLayout
  /** 父级"纵向堆叠"列表算出的全局列数（表格行对齐用）；不传则自己算 */
  tableCols?: number
}>()

const store = useResumeStore()

/** 是否被选中（点了窗口本身；点内容选中的是内容，不算窗口） */
const isSelected = computed(() => store.selectedId === props.row.id)

/** 是否为横排（有 rows 字段就算，即使还是空的） */
const isContainer = computed(() => Array.isArray(props.row.rows))

/** 本窗口所在"纵向堆叠"里的全局列数（横向容器用来均分格子宽度） */
const cols = computed(() => props.tableCols ?? computeTableCols(props.row.rows ?? []))

/** 横向容器里，第 index 个子窗口占几列（竖向/叶子整行不与列数挂钩） */
function childSpan(index: number): number {
  return spanForIndex(index, props.row.rows?.length ?? 0, cols.value)
}

/** 横向容器内每个子窗口的 grid-column span（竖向容器/叶子窗口不设，占满整行） */
function childGridStyle(index: number): Record<string, string> | undefined {
  if (props.row.layout !== 'horizontal') return undefined
  return { gridColumn: `span ${childSpan(index)}` }
}

/* ---------- 窗口操作 ---------- */

function onRemove() {
  store.removeRow(props.section.id, props.row.id)
  message.success('布局窗口已删除')
}

/**
 * ＋上/下/左/右 添加按钮：
 *  - 上/下 = 在上方/下方添加（竖向堆叠，占满整行）；
 *  - 左/右 = 左右并排（自动形成横排）。
 */
const INSERT_TITLES = {
  top: '在上方添加布局窗口（新的一行）',
  bottom: '在下方添加布局窗口（新的一行）',
  left: '在左侧添加（左右并排）',
  right: '在右侧添加（左右并排）',
}

function onInsert(side: 'top' | 'bottom' | 'left' | 'right') {
  const row = store.insertRowRelative(props.section.id, props.row.id, side)
  if (row) message.success('已添加布局窗口')
}

/* ---------- 拖拽（vue-draggable-plus） ---------- */

/** 判断拖进来的数据是不是"预设"（预设才有 name；真实数据没有） */
function isPresetLike(x: unknown): boolean {
  const p = x as { name?: unknown }
  return !!p && typeof p === 'object' && typeof p.name === 'string'
}

/** 按 id 找 vue-draggable-plus 插入的占位对象：它插入的是深拷贝（引用不同），indexOf 找不到 */
function indexOfId<T extends { id?: unknown }>(arr: T[], id: unknown): number {
  if (typeof id !== 'string') return -1
  return arr.findIndex((x) => x && x.id === id)
}

/** 把占位替换/插入到目标数组里（在 nextTick 里调用，此时 vue-draggable-plus 内部已把数据插进数组） */
function replacePlaceholder<T extends { id?: unknown }>(arr: T[], data: unknown, real: T, newIndex: number | undefined) {
  const existing = indexOfId(arr, (data as { id?: unknown } | null)?.id)
  if (existing >= 0) {
    arr.splice(existing, 1, real)
  } else {
    // 兜底：克隆体就落在 newIndex 上，原位替换即可（不能"插入"，否则会多一份）
    arr.splice(Math.min(newIndex ?? arr.length, arr.length), 1, real)
  }
}

/** 移除错误的占位（拖进来的类型不对） */
function removePlaceholder<T extends { id?: unknown }>(arr: T[], data: unknown, newIndex: number | undefined) {
  const existing = indexOfId(arr, (data as { id?: unknown } | null)?.id)
  if (existing >= 0) {
    arr.splice(existing, 1)
  } else if (newIndex !== undefined && newIndex >= 0 && newIndex < arr.length) {
    arr.splice(newIndex, 1)
  }
}

/**
 * vue-draggable-plus 在触发 add 前已把克隆同步插进数组（onAdd 里先内部插入、再派发事件），
 * 所以这里可以【同步】把占位替换成真实数据 —— 占位永远不会被渲染成组件（渲染崩溃的根源）。
 * 只有极少数找不到占位的边缘情况才退回 nextTick 兜底。
 */
function syncReplace<T extends { id?: unknown }>(arr: T[], data: unknown, real: T, newIndex: number | undefined) {
  const existing = indexOfId(arr, (data as { id?: unknown } | null)?.id)
  if (existing >= 0) arr.splice(existing, 1, real)
  else nextTick(() => replacePlaceholder(arr, data, real, newIndex))
}

/** 横排列表：从组件库「布局」拖入 → 生成布局窗口；真实窗口跨列表移动则原样放入 */
function onChildRowAdd(evt: { data?: unknown; newIndex?: number }) {
  const arr = props.row.rows
  if (!arr) return
  const data = evt.data as { id?: unknown; type?: unknown; title?: unknown; layout?: unknown } | undefined
  if (!data) {
    removePlaceholder(arr, evt.data, evt.newIndex)
    return
  }
  if (isPresetLike(data)) {
    // 预设：只接受"布局预设"（有 layout，没有 type/title）
    if (data.type !== undefined || data.title !== undefined) {
      removePlaceholder(arr, data, evt.newIndex)
      message.warning('这里只能放布局（从组件库「布局」分组拖入）')
      return
    }
    const real = createRowFromPreset(data as never)
    syncReplace(arr, data, real, evt.newIndex)
  } else {
    // 真实布局窗口从别的列表拖过来 → 原样放入
    syncReplace(arr, data, data as unknown as LayoutWindow, evt.newIndex)
  }
}

/** 内容列表：从组件库「内容」拖入 → 生成内容；真实内容跨列表移动则原样放入 */
function onContentAdd(evt: { data?: unknown; newIndex?: number }) {
  const arr = props.row.contents
  const data = evt.data as { id?: unknown; type?: unknown } | undefined
  if (!data) {
    removePlaceholder(arr, evt.data, evt.newIndex)
    return
  }
  if (isPresetLike(data)) {
    // 预设：只接受"内容预设"（有 type）
    if (data.type === undefined) {
      removePlaceholder(arr, data, evt.newIndex)
      message.warning('这里只能放内容（从组件库「内容」分组拖入）')
      return
    }
    const real = createContentFromPreset(data as never)
    syncReplace(arr, data, real, evt.newIndex)
    store.select(real.id)
  } else {
    // 真实内容从别的列表拖过来 → 原样放入
    syncReplace(arr, data, data as never, evt.newIndex)
  }
}

/**
 * vue-draggable-plus 跨列表拖拽时，SortableJS 会直接"从源 DOM 摘走、再塞回"被拖元素
 * （onRemove 里 Tt 回插），这会破坏 Vue 对源列表 v-for 的 keyed-diff 跟踪：
 * 源列表重新渲染（store 已正确移除该元素）后，DOM 里仍残留一个没有 vnode 的幽灵卡片，
 * 且之后 Vue 永远不再动它（于是出现"复制后拖拽变 3 个、刷新变 2 个"）。
 * store 始终是对的，所以拖拽结束后按 model 把多出来的 DOM 卡片清掉即可。
 */
function reconcileDragDom(list: HTMLElement | null | undefined, ids: string[]) {
  if (!list) return
  nextTick(() => {
    const set = new Set(ids)
    list
      .querySelectorAll<HTMLElement>(':scope > [data-content-id], :scope > [data-row-id]')
      .forEach((el) => {
        const id = el.getAttribute('data-content-id') || el.getAttribute('data-row-id')
        if (id && !set.has(id)) el.remove()
      })
  })
}

/** 内容列表拖拽结束：清理源列表残留的幽灵卡片（跨行/跨章拖动后） */
function onContentDragEnd(evt: { from?: HTMLElement }) {
  reconcileDragDom(evt.from, (props.row.contents ?? []).map((b) => b.id))
}

/** 窗口列表拖拽结束：清理源列表残留的幽灵窗口（跨章移动后） */
function onRowDragEnd(evt: { from?: HTMLElement }) {
  reconcileDragDom(evt.from, (props.row.rows ?? []).map((r) => r.id))
}
</script>

<template>
  <div
    class="layout-row"
    :class="{ selected: isSelected }"
    :data-row-id="row.id"
    @click.stop="store.select(row.id)"
  >
    <!-- 窗口头部 -->
    <div class="row-header">
      <span class="row-drag-handle" title="按住拖动窗口（排序 / 移到其他章节）">
        ⋮⋮
      </span>
      <span class="row-tag">{{ isContainer ? '⇋ 横排' : '🧩 窗口布局' }}</span>
      <span class="row-spacer" />
      <n-button size="tiny" quaternary type="error" title="删除窗口" @click.stop="onRemove">✕</n-button>
    </div>

    <!-- 四边 ＋ 按钮（只在布局窗口上，横排不显示）：
         上/下 = 竖向堆叠（新的一行）；左/右 = 左右并排（自动形成横排） -->
    <template v-if="!isContainer">
      <button class="add-edge add-top" :title="INSERT_TITLES.top" @click.stop="onInsert('top')">＋</button>
      <button class="add-edge add-bottom" :title="INSERT_TITLES.bottom" @click.stop="onInsert('bottom')">＋</button>
      <button class="add-edge add-left" :title="INSERT_TITLES.left" @click.stop="onInsert('left')">＋</button>
      <button class="add-edge add-right" :title="INSERT_TITLES.right" @click.stop="onInsert('right')">＋</button>
    </template>

    <!-- 横排：放多个布局窗口并排（按住 ⋮⋮ 排序；从组件库「布局」拖入 = 加布局）。
         以一张"连接表格"渲染：同一行格子自动均分全局列数、贴边，形成 ┌┬┬┐ 观感 -->
    <div
      v-if="isContainer"
      class="row-children"
      :class="row.layout === 'horizontal' ? 'children-h' : 'children-v'"
      :style="row.layout === 'horizontal' ? { '--cols': cols } : undefined"
    >
      <VueDraggable
        v-model="row.rows!"
        :group="{ name: 'smartcv-row', put: ['smartcv-row'] }"
        handle=".row-drag-handle"
        :animation="150"
        class="row-drag-list"
        @add="onChildRowAdd"
        @end="onRowDragEnd"
      >
        <LayoutWindowItem
          v-for="(child, i) in row.rows"
          :key="child.id"
          :section="section"
          :row="child"
          :parent-direction="row.layout"
          :table-cols="cols"
          :style="childGridStyle(i)"
        />
      </VueDraggable>
      <!-- 空横排提示：铺满落点区并居中，pointer-events:none 不挡拖放 -->
      <div v-if="(row.rows?.length ?? 0) === 0" class="row-empty">
        📥 从组件库拖「窗口布局」到这里
      </div>
    </div>

    <!-- 窗口布局：放内容（按住 ⋮⋮ 排序；从组件库「内容」拖入 = 加内容） -->
    <div v-else class="row-body" :class="row.layout === 'horizontal' ? 'row-h' : 'row-v'">
      <VueDraggable
        v-model="row.contents"
        :group="{ name: 'smartcv-content', put: ['smartcv-content'] }"
        handle=".content-drag-handle"
        :animation="150"
        class="content-drag-list"
        @add="onContentAdd"
        @end="onContentDragEnd"
      >
        <ContentCard
          v-for="b in row.contents"
          :key="b.id"
          :section="section"
          :row="row"
          :content="b"
        />
      </VueDraggable>
      <!-- 空窗口提示：铺满落点区并居中，pointer-events:none 不挡拖放 -->
      <div v-if="(row.contents ?? []).length === 0" class="row-empty">
        📥 从组件库把内容拖到这里
      </div>
    </div>
  </div>
</template>

<style scoped>
.layout-row {
  --table-line: #e4e9f1; /* 表格线颜色 */
  position: relative;
  /* 不再画独立边框：窗口靠所在"表格"的统一边线区分，格与格贴边 */
  border: none;
  border-radius: 0;
  padding: 4px 8px 8px;
  background: #fff;
  cursor: default;
}

/* 选中窗口：内侧蓝色描边（与章节/内容卡片的选中样式一致） */
.layout-row.selected {
  box-shadow: inset 0 0 0 1.5px var(--primary);
  background: #f7faff;
}

/* 四边 ＋ 按钮：贴在布局窗口的上下左右边缘，只在悬停该窗口时淡入 */
.add-edge {
  position: absolute;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 1px solid #e2e8f2;
  border-radius: 50%;
  background: #fff;
  color: #9aa6b8;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.15s, background 0.15s, transform 0.15s, visibility 0.15s;
}
.add-edge:hover {
  opacity: 0.9;
  visibility: visible;
  background: #eef3ff;
  color: var(--primary);
}
.add-top {
  top: -9px;
  left: 50%;
  transform: translateX(-50%);
}
.add-bottom {
  bottom: -9px;
  left: 50%;
  transform: translateX(-50%);
}
.add-left {
  left: -9px;
  top: 50%;
  transform: translateY(-50%);
}
.add-right {
  right: -9px;
  top: 50%;
  transform: translateY(-50%);
}
/* 只在悬停窗口时才显示四周 ＋ 按钮（默认隐藏，不挡住拖拽区） */
.layout-row:hover .add-edge {
  opacity: 0.9;
  visibility: visible;
}

/* 窗口拖拽手柄 */
.row-drag-handle {
  flex: none;
  cursor: grab;
  color: #b6bdc9;
  font-size: 13px;
  letter-spacing: 1px;
  padding: 0 4px;
  border-radius: 4px;
  user-select: none;
}
.row-drag-handle:hover {
  background: #e8edf5;
  color: #5b6675;
}
.row-drag-handle:active {
  cursor: grabbing;
}

.row-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.row-tag {
  font-size: 11px;
  color: #8b95a7;
}
.row-spacer {
  flex: 1;
}

/* 横排：布局窗口列表（一张连接表格，格子贴边） */
.row-children {
  position: relative;
  display: flex;
}
.children-v {
  flex-direction: column;
}
.children-h {
  flex-direction: row;
}

/* 竖向容器：子窗口上下堆叠（分层），1px 间隙被容器背景填成横线；外框由所在表格统一提供 */
.children-v .row-drag-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
  background: var(--table-line);
  /* 空容器也能把「窗口布局」拖进来（空列表要有足够大的落点面积） */
  min-height: 64px;
}

/* 横向容器：一张表格行 —— 同一行格子贴边、均分全局列数（--cols），1px 间隙被背景填成竖线 */
.children-h .row-drag-list {
  display: grid;
  grid-template-columns: repeat(var(--cols, 1), minmax(0, 1fr));
  gap: 1px;
  flex: 1;
  min-width: 0;
  background: var(--table-line);
  min-height: 64px;
}
.children-h .row-drag-list > :deep(.layout-row) {
  min-width: 0;
}

/* 窗口布局主体：内容列表 */
.row-body {
  position: relative;
  display: flex;
}
.row-v {
  flex-direction: column;
}
.row-h {
  flex-direction: row;
  align-items: flex-start;
}
.content-drag-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
  /* 空窗口也能把内容拖进来（空列表要有足够大的落点面积） */
  min-height: 56px;
}
.row-h .content-drag-list {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 8px;
}
.row-h .content-drag-list :deep(.content-card) {
  flex: 1 1 0;
  min-width: 0;
}

/* 空态提示：绝对定位铺满落点区并居中，pointer-events:none 不拦截拖放 */
.row-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px dashed #d3dae6;
  border-radius: 8px;
  background: #fff;
  color: #8b95a7;
  font-size: 12px;
  pointer-events: none;
}
</style>
