<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import LayoutWindowItem from './LayoutWindowItem.vue'
import StylePopover from './StylePopover.vue'
import IconGlyph from './IconGlyph.vue'
import { useResumeStore } from '@/stores/resume'
import { useClickPopover } from '@/composables/useClickPopover'
import { DEFAULT_CHAPTER_GAP, DEFAULT_TITLE_SIZE } from '@/utils/constants'
import { createRowFromPreset } from '@/data/presets'
import { ICON_GROUPS } from '@/data/icons'
import { computeTableCols } from '@/utils/layout'
import type { Section, LayoutWindow } from '@/types'
import { message } from '@/utils/feedback'

const props = defineProps<{ section: Section }>()

const store = useResumeStore()

const isSelected = computed(() => store.selectedId === props.section.id)
const collapsed = computed(() => store.isSectionCollapsed(props.section.id))

const tableCols = computed(() => computeTableCols(props.section.rows))

const { show: styleShow, triggerRef: styleTriggerRef } = useClickPopover()

const { show: iconPopoverShow, triggerRef: iconTriggerRef } = useClickPopover()

const titleModel = computed({
  get: () => props.section.title,
  set: (v: string) => store.updateSection(props.section.id, { title: v }),
})

const iconModel = computed({
  get: () => props.section.icon ?? '',
  set: (v: string) => store.updateSection(props.section.id, { icon: v }),
})

function pickIcon(icon: string) {
  iconModel.value = icon
  iconPopoverShow.value = false
}

function clearIcon() {
  iconModel.value = ''
  iconPopoverShow.value = false
}

function indexOfId<T extends { id?: unknown }>(arr: T[], id: unknown): number {
  if (typeof id !== 'string') return -1
  return arr.findIndex((x) => x && x.id === id)
}

function isPresetLike(x: unknown): boolean {
  const p = x as { name?: unknown }
  return !!p && typeof p === 'object' && typeof p.name === 'string'
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

function onRowAdd(evt: { data?: unknown; newIndex?: number }) {
  const data = evt.data as { id?: unknown; name?: string; type?: unknown; title?: unknown } | undefined
  const arr = props.section.rows
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
    <span v-if="section.pageBreakBefore" class="forced-badge" title="该章节从下一页开头开始">
      ⤒ 强制分页
    </span>

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
      <n-popover
        v-model:show="iconPopoverShow"
        trigger="click"
        placement="bottom-start"
        :width="320"
      >
        <template #trigger>
          <button
            ref="iconTriggerRef"
            class="section-icon-trigger"
            :class="{ empty: !section.icon }"
            title="章节标题前的图标（留空则不显示）"
            @click.stop
          >
            <span v-if="section.icon" class="section-icon-content" v-html="section.icon" />
            <span v-else>＋</span>
          </button>
        </template>
        <template #default>
          <div class="section-icon-picker">
            <div v-for="g in ICON_GROUPS" :key="g.name" class="icon-group">
              <div class="icon-section-name">{{ g.name }}</div>
              <div class="icon-grid">
                <button
                  v-for="ic in g.icons"
                  :key="ic"
                  class="icon-cell"
                  :class="{ active: section.icon === ic }"
                  @click="pickIcon(ic)"
                >
                  <span v-html="ic" />
                </button>
              </div>
            </div>
            <div class="pick-actions">
              <n-input
                v-model:value="iconModel"
                size="small"
                placeholder="或输入任意 emoji / 留空则不显示"
              />
              <n-button size="tiny" quaternary type="error" @click.stop="clearIcon">清除</n-button>
            </div>
          </div>
        </template>
      </n-popover>
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
            <button
              type="button"
              class="section-tool-btn"
              :class="{ 'is-on': section.pageBreakBefore }"
              :aria-pressed="section.pageBreakBefore"
              @click="togglePageBreak"
            >
              <IconGlyph name="arrow-down-to-line" :size="13" />
            </button>
          </template>
          {{ section.pageBreakBefore ? '已开启强制分页：该章节从下一页开头开始（点击关闭）' : '强制分页：开启后该章节从下一页开头开始' }}
        </n-tooltip>
        <n-popover v-model:show="styleShow" trigger="click" placement="bottom-start" :width="292">
          <template #trigger>
            <span ref="styleTriggerRef" class="trigger-wrap">
              <button type="button" class="section-tool-btn" :class="{ 'is-open': styleShow }" title="样式设置">
                <IconGlyph name="sliders-horizontal" :size="13" />
              </button>
            </span>
          </template>
          <template #default>
            <StylePopover mode="section" :section-id="section.id" />
          </template>
        </n-popover>
        <n-tooltip trigger="hover">
          <template #trigger>
            <button type="button" class="section-tool-btn" title="复制章节" @click="onDuplicate">
              <IconGlyph name="copy" :size="13" />
            </button>
          </template>
          复制章节
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <button type="button" class="section-tool-btn danger" title="删除章节" @click="onRemove">
              <IconGlyph name="trash-2" :size="13" />
            </button>
          </template>
          删除章节
        </n-tooltip>
      </div>
    </div>

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

      <div v-if="section.rows.length === 0" class="section-empty">
        从上方组件库拖入布局或内容
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-card {
  position: relative;
  padding: 8px 10px 4px;
  border-radius: var(--radius-md);
  background: var(--surface-soft);
  box-shadow: inset 0 0 0 1px var(--border);
  transition:
    box-shadow 0.15s var(--ease),
    background 0.15s var(--ease);
}
.section-card:hover {
  box-shadow: inset 0 0 0 1px var(--border-strong);
}
.section-card.selected {
  box-shadow: inset 0 0 0 1.5px var(--primary);
  background: var(--primary-faint);
}

.forced-badge {
  position: absolute;
  top: -9px;
  right: 12px;
  z-index: 2;
  background: var(--warning-soft);
  color: var(--warning);
  border: 1px solid rgba(166, 118, 63, 0.24);
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
  border-bottom: 1px solid var(--border);
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
  color: var(--text-tertiary);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s var(--ease);
}
.collapse-btn:hover {
  background: var(--primary-soft);
  color: var(--text-secondary);
}

.section-drag-handle {
  flex: none;
  align-self: stretch;
  display: flex;
  align-items: center;
  cursor: grab;
  color: var(--text-tertiary);
  font-size: 15px;
  letter-spacing: 1px;
  padding: 0 8px;
  margin: -2px 0 -2px -4px;
  border-radius: 5px;
  user-select: none;
}
.section-drag-handle:hover {
  background: var(--primary-soft);
  color: var(--text-secondary);
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
  color: var(--text);
  padding: 2px 4px;
  border-radius: 4px;
}
.section-title-input:hover,
.section-title-input:focus {
  background: var(--primary-faint);
}

.section-icon-trigger {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 24px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.12s,
    border-color 0.12s;
}
.section-icon-trigger:hover {
  border-color: var(--border-strong);
  background: var(--primary-soft);
}
.section-icon-trigger.empty {
  border-style: dashed;
  border-color: var(--border-strong);
  background: transparent;
  color: var(--text-tertiary);
}
.section-icon-content {
  display: inline-flex;
}
.section-icon-trigger :deep(svg) {
  width: 16px;
  height: 16px;
  display: block;
}
.section-icon-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
  padding: 2px;
}
.icon-section-name {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}
.icon-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.icon-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.12s,
    border-color 0.12s;
}
.icon-cell :deep(svg) {
  width: 18px;
  height: 18px;
  display: block;
}
.icon-cell:hover {
  background: var(--primary-soft);
}
.icon-cell.active {
  background: var(--primary-soft);
  border-color: var(--primary);
}
.pick-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pick-actions :deep(.n-input) {
  flex: 1;
}
.section-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}
.trigger-wrap {
  display: inline-flex;
}
.section-tool-btn {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.12s var(--ease),
    color 0.12s var(--ease);
}
.section-tool-btn:hover {
  background: var(--surface-soft);
  color: var(--text);
}
.section-tool-btn.is-on {
  background: var(--warning-soft);
  color: var(--warning);
}
.section-tool-btn.is-open {
  background: var(--primary-soft);
  color: var(--primary);
}
.section-tool-btn.danger:hover {
  background: var(--danger-soft);
  color: var(--danger);
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
  --table-line: var(--border);
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--table-line);
  border: 1px solid var(--table-line);
  border-radius: 8px;
  min-height: 96px;
}
.section-rows-inner > * {
  background: var(--panel-bg);
}

.section-empty {
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

.section-footer {
  display: flex;
  justify-content: flex-end;
  padding: 2px 0 4px;
}
</style>
