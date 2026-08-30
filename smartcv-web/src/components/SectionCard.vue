<script setup lang="ts">
/**
 * 章节的"编辑卡片"（中间画布用）
 *
 * 章节内部是一组"布局行"（LayoutWindowItem 递归渲染）：
 * 行内可以放多个布局窗口并排（横排），也可以再套行。
 *
 * 功能：
 *  - 章节标题直接编辑；⋮⋮ 手柄拖动章节排序（vue-draggable-plus）；
 *  - 强制分页开关、样式设置、复制、删除；
 *  - ▾/▸ 折叠：折叠后只显示标题栏（v-show 保留 DOM，展开后内容不丢）。
 */
import { computed, nextTick, ref } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import LayoutWindowItem from './LayoutWindowItem.vue'
import StylePopover from './StylePopover.vue'
import { useResumeStore } from '@/stores/resume'
import { useClickPopover } from '@/composables/useClickPopover'
import { DEFAULT_CHAPTER_GAP, DEFAULT_TITLE_SIZE } from '@/utils/constants'
import { createRowFromPreset } from '@/data/presets'
import { computeTableCols } from '@/utils/layout'
import type { Section, LayoutWindow } from '@/types'
import { message } from '@/utils/feedback'

const props = defineProps<{ section: Section }>()

const store = useResumeStore()

const isSelected = computed(() => store.selectedId === props.section.id)
const collapsed = computed(() => store.isSectionCollapsed(props.section.id))

/** 顶层窗口列表算出的全局列数（横向容器用来均分格子宽度，实现跨列对齐） */
const tableCols = computed(() => computeTableCols(props.section.rows))

/** 样式弹层（受控，点外部自动关闭） */
const { show: styleShow, triggerRef: styleTriggerRef } = useClickPopover()

/* ---------- 标题编辑 ---------- */

const titleModel = computed({
  get: () => props.section.title,
  set: (v: string) => store.updateSection(props.section.id, { title: v }),
})

/* ---------- 布局行拖拽（vue-draggable-plus） ---------- */

/** 按 id 找 vue-draggable-plus 插入的占位对象：它插入的是深拷贝（引用不同），indexOf 找不到 */
function indexOfId<T extends { id?: unknown }>(arr: T[], id: unknown): number {
  if (typeof id !== 'string') return -1
  return arr.findIndex((x) => x && x.id === id)
}

/** 判断拖进来的数据是不是"预设"（预设才有 name；真实窗口数据没有 name 字段） */
function isPresetLike(x: unknown): boolean {
  const p = x as { name?: unknown }
  return !!p && typeof p === 'object' && typeof p.name === 'string'
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

/** 布局行列表：从组件库「布局」拖入 → 生成布局行；真实窗口跨章节移动 → 原样放入 */
function onRowAdd(evt: { data?: unknown; newIndex?: number }) {
  const data = evt.data as { id?: unknown; name?: string; type?: unknown; title?: unknown } | undefined
  const arr = props.section.rows
  if (!data) {
    removePlaceholder(arr, evt.data, evt.newIndex)
    return
  }
  if (isPresetLike(data)) {
    // 预设：只接受"布局预设"（有 name、没有 type/title）
    if (data.type !== undefined || data.title !== undefined) {
      removePlaceholder(arr, data, evt.newIndex)
      message.warning('这里只能放布局（从组件库「布局」分组拖入）')
      return
    }
    const real = createRowFromPreset(data as never)
    syncReplace(arr, data, real, evt.newIndex)
  } else {
    // 真实布局窗口从别的章节/列表拖过来 → 原样放入
    syncReplace(arr, data, data as unknown as LayoutWindow, evt.newIndex)
  }
}

/* ---------- 操作 ---------- */

function togglePageBreak() {
  store.updateSection(props.section.id, { pageBreakBefore: !props.section.pageBreakBefore })
}

function onDuplicate() {
  store.duplicateSection(props.section.id)
}

function onRemove() {
  store.removeSection(props.section.id)
  message.success('章节已删除')
}
</script>

<template>
  <div
    class="section-card"
    :class="{ selected: isSelected }"
    :style="{ marginTop: `${section.style?.spaceBefore ?? DEFAULT_CHAPTER_GAP}px` }"
    :data-section-id="section.id"
    @click.stop="store.select(section.id)"
  >
    <!-- 强制分页角标 -->
    <span v-if="section.pageBreakBefore" class="forced-badge" title="该章节从下一页开头开始">
      ⤒ 强制分页
    </span>

    <!-- 章节头部 -->
    <div class="section-header" :class="{ collapsed }">
      <button
        class="collapse-btn"
        :title="collapsed ? '展开章节' : '折叠章节'"
        @click.stop="store.toggleSectionCollapsed(section.id)"
      >
        {{ collapsed ? '▸' : '▾' }}
      </button>
      <span class="section-drag-handle" title="按住拖动章节排序">
        ⋮⋮
      </span>
      <input
        v-model="titleModel"
        class="section-title-input"
        :style="{ fontSize: `${section.style?.titleSize ?? DEFAULT_TITLE_SIZE}px` }"
        placeholder="章节标题"
        @click.stop="store.select(section.id)"
      />
      <div class="section-toolbar" @click.stop>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              size="tiny"
              quaternary
              :type="section.pageBreakBefore ? 'warning' : 'default'"
              @click="togglePageBreak"
            >
              ⤒ 分页
            </n-button>
          </template>
          开启后，该章节强制从下一页开头开始
        </n-tooltip>
        <n-popover v-model:show="styleShow" trigger="click" placement="bottom-start" :width="288">
          <template #trigger>
            <span ref="styleTriggerRef" class="trigger-wrap">
              <n-button size="tiny" quaternary>🎨 样式</n-button>
            </span>
          </template>
          <template #default>
            <StylePopover mode="section" :section-id="section.id" />
          </template>
        </n-popover>
        <n-button size="tiny" quaternary @click="onDuplicate">复制</n-button>
        <n-button size="tiny" quaternary type="error" @click="onRemove">删除</n-button>
      </div>
    </div>

    <!-- 布局行列表（折叠时隐藏，DOM 保留）：按住 ⋮⋮ 手柄排序；从组件库「布局」分组拖入 = 生成布局行 -->
    <div v-show="!collapsed" class="section-rows">
      <VueDraggable
        v-model="section.rows"
        :group="{ name: 'smartcv-row', put: ['smartcv-row'] }"
        handle=".row-drag-handle"
        :animation="150"
        class="section-rows-inner"
        @add="onRowAdd"
      >
        <LayoutWindowItem
          v-for="row in section.rows"
          :key="row.id"
          :section="section"
          :row="row"
          parent-direction="vertical"
          :table-cols="tableCols"
        />
      </VueDraggable>

      <!-- 无窗口提示：铺满整个落点区并居中，pointer-events:none 不挡拖放（空白章节也能承接拖入） -->
      <div v-if="section.rows.length === 0" class="section-empty">
        📥 从左侧拖「布局窗口」或内容到这里
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-card {
  position: relative;
  padding: 8px 10px 4px;
  border-radius: 8px;
  background: #fbfcfe;
  box-shadow: inset 0 0 0 1px #e2e6ee;
  transition:
    box-shadow 0.15s,
    background 0.15s;
}
.section-card:hover {
  box-shadow: inset 0 0 0 1px #c8d0dd;
}
.section-card.selected {
  box-shadow: inset 0 0 0 1.5px var(--primary);
  background: #f7faff;
}

.forced-badge {
  position: absolute;
  top: -9px;
  right: 12px;
  z-index: 2;
  background: #fff7ed;
  color: #ea580c;
  border: 1px solid #fdba74;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  padding: 0 8px;
  pointer-events: none;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-bottom: 6px;
  border-bottom: 1px dashed #e5e9f1;
  margin-bottom: 8px;
}
.section-header.collapsed {
  border-bottom: none;
  margin-bottom: 0;
}

.collapse-btn {
  flex: none;
  width: 22px;
  height: 24px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #6b7280;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s;
}
.collapse-btn:hover {
  background: #e8edf5;
}

.section-drag-handle {
  flex: none;
  align-self: stretch;
  display: flex;
  align-items: center;
  cursor: grab;
  color: #b6bdc9;
  font-size: 15px;
  letter-spacing: 1px;
  padding: 0 8px;
  margin: -2px 0 -2px -4px;
  border-radius: 5px;
  user-select: none;
}
.section-drag-handle:hover {
  background: #e8edf5;
  color: #5b6675;
}
.section-drag-handle:active {
  cursor: grabbing;
}
.section-title-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-weight: 600;
  color: #1f2937;
  padding: 2px 4px;
  border-radius: 4px;
}
.section-title-input:hover,
.section-title-input:focus {
  background: #eef2f8;
}
.section-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}
/* 触发器包装：给 ref 一个原生元素（n-button 的实例没有 contains） */
.trigger-wrap {
  display: inline-flex;
}
.section-card:hover .section-toolbar,
.section-card.selected .section-toolbar {
  opacity: 1;
}

.section-rows {
  position: relative;
  display: flex;
  flex-direction: column;
}
.section-rows-inner {
  --table-line: #e4e9f1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--table-line);
  border: 1px solid var(--table-line);
  border-radius: 8px;
  /* 空章节也能把「窗口布局」拖进来（空列表要有足够大的落点面积） */
  min-height: 96px;
}
.section-rows-inner > * {
  background: #fff;
}

/* 无窗口提示：绝对定位铺满落点区并居中；pointer-events:none 让它不拦截拖放 */
.section-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px dashed #d3dae6;
  border-radius: 8px;
  background: #fcfdff;
  color: #8b95a7;
  font-size: 12px;
  pointer-events: none;
}

.section-footer {
  display: flex;
  justify-content: flex-end;
  padding: 2px 0 4px;
}
</style>
