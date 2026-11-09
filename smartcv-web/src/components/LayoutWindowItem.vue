<script setup lang="ts">
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
  parentDirection?: SectionLayout
  tableCols?: number
}>()

const store = useResumeStore()

const isSelected = computed(() => store.selectedId === props.row.id)

const isContainer = computed(() => Array.isArray(props.row.rows))

const cols = computed(() => props.tableCols ?? computeTableCols(props.row.rows ?? []))

function childSpan(index: number): number {
  return spanForIndex(index, props.row.rows?.length ?? 0, cols.value)
}

function childGridStyle(index: number): Record<string, string> | undefined {
  if (props.row.layout !== 'horizontal') return undefined
  return { gridColumn: `span ${childSpan(index)}` }
}

function onRemove() {
  store.removeRow(props.section.id, props.row.id)
  message.success('布局窗口已删除')
}

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

function isPresetLike(x: unknown): boolean {
  const p = x as { name?: unknown }
  return !!p && typeof p === 'object' && typeof p.name === 'string'
}

function indexOfId<T extends { id?: unknown }>(arr: T[], id: unknown): number {
  if (typeof id !== 'string') return -1
  return arr.findIndex((x) => x && x.id === id)
}

function replacePlaceholder<T extends { id?: unknown }>(arr: T[], data: unknown, real: T, newIndex: number | undefined) {
  const existing = indexOfId(arr, (data as { id?: unknown } | null)?.id)
  if (existing >= 0) {
    arr.splice(existing, 1, real)
  } else {
    arr.splice(Math.min(newIndex ?? arr.length, arr.length), 1, real)
  }
}

function removePlaceholder<T extends { id?: unknown }>(arr: T[], data: unknown, newIndex: number | undefined) {
  const existing = indexOfId(arr, (data as { id?: unknown } | null)?.id)
  if (existing >= 0) {
    arr.splice(existing, 1)
  } else if (newIndex !== undefined && newIndex >= 0 && newIndex < arr.length) {
    arr.splice(newIndex, 1)
  }
}

function syncReplace<T extends { id?: unknown }>(arr: T[], data: unknown, real: T, newIndex: number | undefined) {
  const existing = indexOfId(arr, (data as { id?: unknown } | null)?.id)
  if (existing >= 0) arr.splice(existing, 1, real)
  else nextTick(() => replacePlaceholder(arr, data, real, newIndex))
}

function onChildRowAdd(evt: { data?: unknown; newIndex?: number }) {
  const arr = props.row.rows
  if (!arr) return
  const data = evt.data as { id?: unknown; type?: unknown; title?: unknown; layout?: unknown } | undefined
  if (!data) {
    removePlaceholder(arr, evt.data, evt.newIndex)
    return
  }
  if (isPresetLike(data)) {
    if (data.type !== undefined || data.title !== undefined) {
      removePlaceholder(arr, data, evt.newIndex)
      message.warning('这里只能放布局（从组件库「布局」分组拖入）')
      return
    }
    const real = createRowFromPreset(data as never)
    syncReplace(arr, data, real, evt.newIndex)
  } else {
    syncReplace(arr, data, data as unknown as LayoutWindow, evt.newIndex)
  }
}

function onContentAdd(evt: { data?: unknown; newIndex?: number }) {
  const arr = props.row.contents
  const data = evt.data as { id?: unknown; type?: unknown } | undefined
  if (!data) {
    removePlaceholder(arr, evt.data, evt.newIndex)
    return
  }
  if (isPresetLike(data)) {
    if (data.type === undefined) {
      removePlaceholder(arr, data, evt.newIndex)
      message.warning('这里只能放内容（从组件库「内容」分组拖入）')
      return
    }
    const real = createContentFromPreset(data as never)
    syncReplace(arr, data, real, evt.newIndex)
    store.select(real.id)
  } else {
    syncReplace(arr, data, data as never, evt.newIndex)
  }
}

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

function onContentDragEnd(evt: { from?: HTMLElement }) {
  reconcileDragDom(evt.from, (props.row.contents ?? []).map((b) => b.id))
}

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
    <div class="row-header">
      <span class="row-drag-handle" title="按住拖动窗口（排序 / 移到其他章节）">
        ⋮⋮
      </span>
      <span class="row-tag">{{ isContainer ? '⇋ 横排' : '窗口布局' }}</span>
      <span class="row-spacer" />
      <n-button size="tiny" quaternary type="error" title="删除窗口" @click.stop="onRemove">✕</n-button>
    </div>

    <template v-if="!isContainer">
      <button class="add-edge add-top" :title="INSERT_TITLES.top" @click.stop="onInsert('top')">＋</button>
      <button class="add-edge add-bottom" :title="INSERT_TITLES.bottom" @click.stop="onInsert('bottom')">＋</button>
      <button class="add-edge add-left" :title="INSERT_TITLES.left" @click.stop="onInsert('left')">＋</button>
      <button class="add-edge add-right" :title="INSERT_TITLES.right" @click.stop="onInsert('right')">＋</button>
    </template>

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
      <div v-if="(row.rows?.length ?? 0) === 0" class="row-empty">
        从组件库拖「窗口布局」到这里
      </div>
    </div>

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
      <div v-if="(row.contents ?? []).length === 0" class="row-empty">
        从组件库把内容拖到这里
      </div>
    </div>
  </div>
</template>

<style scoped>
.layout-row {
  --table-line: var(--border);
  position: relative;
  border: none;
  border-radius: 0;
  padding: 4px 8px 8px;
  background: var(--panel-bg);
  cursor: default;
}

.layout-row.selected {
  box-shadow: inset 0 0 0 1.5px var(--primary);
  background: var(--primary-faint);
}

.add-edge {
  position: absolute;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--panel-bg);
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(36, 42, 38, 0.06);
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.15s var(--ease), background 0.15s var(--ease), transform 0.15s var(--ease), visibility 0.15s;
}
.add-edge:hover {
  opacity: 0.9;
  visibility: visible;
  background: var(--primary-soft);
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
.layout-row:hover .add-edge {
  opacity: 0.9;
  visibility: visible;
}

.row-drag-handle {
  flex: none;
  cursor: grab;
  color: var(--text-tertiary);
  font-size: 13px;
  letter-spacing: 1px;
  padding: 0 4px;
  border-radius: 4px;
  user-select: none;
}
.row-drag-handle:hover {
  background: var(--primary-soft);
  color: var(--text-secondary);
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
  color: var(--text-tertiary);
}
.row-spacer {
  flex: 1;
}

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

.children-v .row-drag-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
  background: var(--table-line);
  min-height: 64px;
}

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
  min-height: 56px;
}
.row-h .content-drag-list {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 8px;
}
.row-h .content-drag-list :deep(.content-card) {
  flex: 1 1 0;
  min-width: 88px;
}

.row-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  background: var(--panel-bg);
  color: var(--text-tertiary);
  font-size: 12px;
  pointer-events: none;
}
</style>
