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
import { onKeyStroke } from '@vueuse/core'
import { VueDraggable } from 'vue-draggable-plus'
import SectionCard from './SectionCard.vue'
import { useResumeStore } from '@/stores/resume'
import { createSectionFromPreset } from '@/data/presets'
import { message } from '@/utils/feedback'

const store = useResumeStore()

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
      <span class="canvas-title">编辑画布</span>
      <span class="canvas-hint">从左侧拖入内容 · 拖动 ⋮⋮ 手柄排序</span>
    </div>

    <div class="canvas-scroll">
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
            <div class="empty-icon">🧱</div>
            <p>
              画布是空的<br />
              从左侧拖一个章节到这里
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
  height: 100%;
  min-width: 0;
  background: #eef0f4;
}

.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid var(--border);
}
.canvas-title {
  font-weight: 600;
  font-size: 14px;
}
.canvas-hint {
  font-size: 12px;
  color: #9ca3af;
}

.canvas-scroll {
  flex: 1;
  overflow: auto;
  padding: 20px 14px 48px;
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
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06), 0 6px 20px rgba(15, 23, 42, 0.07);
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
  gap: 6px;
  text-align: center;
  color: #9ca3af;
  pointer-events: none;
}
.empty-icon {
  font-size: 44px;
}
.canvas-empty p {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
}

/* 画布底部缓冲空间（拖拽自动滚动的目标余量） */
.canvas-bottom-space {
  height: 24px;
}
</style>
