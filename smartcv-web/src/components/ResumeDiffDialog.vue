<script setup lang="ts">
/**
 * AI 修改对比弹窗 —— 「优化简历」页收到后端改好的简历后弹出来给用户过目。
 *
 * 左栏 = 修改前的简历，右栏 = 修改后的简历，改动处按内容块高亮，两栏同步滚动。
 * 用户点「应用修改」才真正写回简历 store（见 stores/optimize.ts 的 applyPendingDiff），
 * 点「取消」则原样保留，简历一个字都不动。
 *
 * 几个刻意的选择：
 *  - **不分页**：两侧高度不同、页数也不同，页与页根本对不齐；连续流 + 固定高度
 *    的滚动容器，才让"按比例同步滚动"这件事有意义（见 useSyncScroll）。
 *  - **不用 n-scrollbar**：普通的 overflow:auto 容器拿 scrollTop/scrollHeight 最直接，
 *    页面里的 .resume-scroll / .chat-list 也是这么写的。
 *  - **只传 marks、不复制渲染逻辑**：两栏复用 PreviewSection 那一套只读渲染组件，
 *    与左侧预览 / PDF 导出是同一份代码，所见即所得。
 */
import { computed, ref } from 'vue'
import PreviewSection from './PreviewSection.vue'
import { diffResume, type DiffMark, type DiffMarks } from '@/utils/resumeDiff'
import { useSyncScroll } from '@/composables/useSyncScroll'
import { previewZoom } from '@/composables/usePreviewZoom'
import { CONTENT_WIDTH } from '@/utils/constants'
import type { Section } from '@/types'

const props = defineProps<{
  show: boolean
  /** 修改前的简历（发请求前深拷贝的快照） */
  before: Section[]
  /** 修改后的简历（后端返回的原始 JSON） */
  after: Section[]
}>()

const emit = defineEmits<{ 'update:show': [boolean]; apply: [] }>()

/** 两侧的标记表 + 改动处数；before/after 是 props，重新比对是自动的 */
const diff = computed(() => diffResume(props.before, props.after))

/** 本次有没有实际改动：没有的话按钮只留「关闭」，「应用修改」点了也是白点 */
const hasChanges = computed(() => diff.value.changedCount > 0)

/** 某一侧被标记的内容块数（栏头显示"本侧改动几处"） */
const markedCount = (marks: DiffMarks) => Object.keys(marks.contents).length

/** 图例的三项：配色与绘制在 styles/global.css 的 [data-diff] 里，这里只列名字 */
const MARK_KINDS: { key: DiffMark; label: string }[] = [
  { key: 'changed', label: '修改' },
  { key: 'added', label: '新增' },
  { key: 'removed', label: '删除' },
]

/**
 * 本次实际出现的标记种类 —— 图例只显示这些。
 *
 * 后端目前只就地改文字（不动结构），所以实际永远是 [changed]；
 * 动态过滤而不是写死"只画修改"：哪天后端支持增删，图例自动跟着长出来，
 * 不用回来改这里（否则会出现"高亮了但图例没有这一项"的怪状态）。
 */
const presentKinds = computed(() => {
  const seen = new Set<DiffMark>()
  for (const marks of [diff.value.before, diff.value.after]) {
    for (const bucket of [marks.sections, marks.rows, marks.contents]) {
      for (const mark of Object.values(bucket)) seen.add(mark)
    }
  }
  return seen
})

/** 只留本次出现过的图例项 */
const legend = computed(() => MARK_KINDS.filter((k) => presentKinds.value.has(k.key)))

/* ---------- 同步滚动 ---------- */
const leftEl = ref<HTMLElement | null>(null)
const rightEl = ref<HTMLElement | null>(null)

useSyncScroll(leftEl, rightEl, () => props.show)

/** 栏内纸张：与页面预览同宽同缩放，两边看到的排版、换行都一致 */
const paperStyle = computed(() => ({
  width: `${CONTENT_WIDTH}px`,
  zoom: previewZoom.value,
}))

/** 关闭 = 不改动简历；真正的"应用"由父组件处理 */
function onClose() {
  emit('update:show', false)
}
</script>

<template>
  <n-modal
    :show="props.show"
    display-directive="if"
    :mask-closable="false"
    preset="card"
    title="AI 修改对比"
    style="width: 96vw; max-width: 1560px"
    @update:show="emit('update:show', $event)"
  >
    <!-- 头部右侧：改动处数 + 图例（颜色 + 角标两个通道，色盲用户也能分辨） -->
    <template #header-extra>
      <div class="diff-header-extra">
        <span class="diff-count" :class="{ none: !hasChanges }">
          {{ hasChanges ? `共 ${diff.changedCount} 处修改` : '本次没有修改' }}
        </span>
        <span v-if="legend.length" class="diff-legend">
          <span v-for="k in legend" :key="k.key" class="legend-item">
            <i class="legend-dot" :class="k.key"></i>{{ k.label }}
          </span>
        </span>
      </div>
    </template>

    <div class="diff-body">
      <!-- 左：原始简历 -->
      <div class="diff-col">
        <div class="col-head">
          <span class="col-title">📄 原始简历</span>
          <span class="col-hint">{{ markedCount(diff.before) }} 处改动</span>
        </div>
        <div ref="leftEl" class="col-scroll">
          <div class="col-paper" :style="paperStyle">
            <PreviewSection
              v-for="s in props.before"
              :key="s.id"
              :section="s"
              :marks="diff.before"
            />
          </div>
        </div>
      </div>

      <!-- 右：修改后简历 -->
      <div class="diff-col">
        <div class="col-head">
          <span class="col-title">✨ 修改后简历</span>
          <span class="col-hint">{{ markedCount(diff.after) }} 处改动</span>
        </div>
        <div ref="rightEl" class="col-scroll">
          <div class="col-paper" :style="paperStyle">
            <PreviewSection
              v-for="s in props.after"
              :key="s.id"
              :section="s"
              :marks="diff.after"
            />
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="diff-footer">
        <span class="diff-footer-tip">
          高亮处 = AI 改动的内容；两侧滚动是联动的，方便逐处对照
        </span>
        <div class="diff-footer-actions">
          <n-button size="small" @click="onClose">
            {{ hasChanges ? '取消' : '关闭' }}
          </n-button>
          <n-button v-if="hasChanges" size="small" type="primary" @click="emit('apply')">
            应用修改
          </n-button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.diff-header-extra {
  display: flex;
  align-items: center;
  gap: 14px;
}
.diff-count {
  font-size: 13px;
  font-weight: 600;
  color: #b45309;
}
.diff-count.none {
  color: #9ca3af;
  font-weight: 400;
}
.diff-legend {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--text-secondary);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
/* 图例色块：与 global.css 里 [data-diff] 的三组配色保持一致 */
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.legend-dot.added {
  background: #10b981;
}
.legend-dot.removed {
  background: #ef4444;
}
.legend-dot.changed {
  background: #f59e0b;
}

/* ---------- 左右分栏 ---------- */
.diff-body {
  display: flex;
  gap: 12px;
}
.diff-col {
  flex: 1 1 50%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: #f8fafc;
  border-bottom: 1px solid var(--border);
}
.col-title {
  font-size: 13px;
  font-weight: 600;
}
.col-hint {
  font-size: 12px;
  color: #9ca3af;
}
/* 滚动容器：高度固定，超出才有得滚（同步滚动的前提） */
.col-scroll {
  height: 68vh;
  overflow: auto;
  padding: 16px;
  background: #eef0f4;
}
/* 纸面：宽度 / 缩放走 inline style（与页面预览共用 previewZoom） */
.col-paper {
  margin: 0 auto;
  background: #fff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
  padding: 24px;
}

/* ---------- 底部 ---------- */
.diff-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.diff-footer-tip {
  font-size: 12px;
  color: #9ca3af;
}
.diff-footer-actions {
  display: flex;
  gap: 8px;
}
</style>
