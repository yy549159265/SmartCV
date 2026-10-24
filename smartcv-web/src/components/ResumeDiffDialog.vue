<script setup lang="ts">
/**
 * AI 修改对比弹窗 —— 「优化简历」页收到后端改好的简历后弹出来给用户过目。
 *
 * 交互（类似 IntelliJ 的 Git 冲突解决界面）：
 *  左栏 = 修改前的简历（绿色标记）；右栏 = 当前结果（AI 修改为红色标记）。
 *  默认右栏就是"全部采用 AI 修改"的状态；每处改动左侧有一个 ↺ / ↻ 按钮：
 *    ↺ 还原为修改前（右栏这块换成原文，标记变绿）  ↻ 恢复这处 AI 修改（变回红）
 *  每处独立切换，右栏（结果侧）会实时跟着变；最后点「确定应用」
 *  才把合并结果写回简历 store（见 stores/optimize.ts 的 applyPendingDiff）。
 *
 * 几个刻意的选择：
 *  - **不分页**：两侧高度不同、页数也不同，页与页根本对不齐；连续流 + 固定高度
 *    的滚动容器，才让"按比例同步滚动"这件事有意义（见 useSyncScroll）。
 *  - **只传 marks / controls、不复制渲染逻辑**：两栏复用 PreviewSection 那一套只读
 *    渲染组件，与左侧预览 / PDF 导出是同一份代码，所见即所得。
 *  - **状态放 store**：关掉弹窗（比如想再看看对话）再打开，已还原的处不会丢。
 */
import { computed, ref } from 'vue'
import PreviewSection from './PreviewSection.vue'
import {
  buildControls,
  diffResume,
  mergeResume,
  type DiffControls,
  type DiffMarks,
} from '@/utils/resumeDiff'
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
  /** 已还原的改动 key 列表（`section:id` / `row:id` / `content:id`） */
  reverted: string[]
}>()

const emit = defineEmits<{
  'update:show': [boolean]
  apply: []
  /** 切换某一处：接受 ↔ 还原 */
  toggle: [key: string]
  'revert-all': []
  'accept-all': []
}>()

/* ---------- 比对 / 合并 ---------- */

const diff = computed(() => diffResume(props.before, props.after))

// 兜底：开发时 HMR 可能留下旧结构的 pendingDiff（没有 reverted 字段），
// 这里不允许它把整个弹窗的渲染/切换搞挂。
const revertedSet = computed(() => new Set(props.reverted ?? []))

/** 已还原的「改动处数」（只统计真实存在的改动，防止脏 key） */
const revertedCount = computed(
  () => diff.value.changes.filter((c) => revertedSet.value.has(c.key)).length,
)

/** 本次有没有实际改动：没有的话按钮只留「关闭」 */
const hasChanges = computed(() => diff.value.changedCount > 0)

/**
 * 右栏渲染的是「当前合并结果」：
 *  - 默认 = 修改后的简历；
 *  - 某处点了 ↺ = 该处换回修改前的内容（绿色）；
 *  - 删除被点 ↺ = 插回原位置；新增被点 ↺ = 灰色占位（确认时不写入）。
 */
const result = computed(() => mergeResume(props.before, props.after, revertedSet.value).sections)

/**
 * 右栏的标记：先取"改后"那份，再给"被还原的删除"补上标记 ——
 * 这些节点在改后树里不存在，但会插回右栏显示，没有标记就看不见。
 */
const marksAfter = computed<DiffMarks>(() => {
  const marks: DiffMarks = {
    sections: { ...diff.value.after.sections },
    rows: { ...diff.value.after.rows },
    contents: { ...diff.value.after.contents },
  }
  for (const change of diff.value.changes) {
    if (change.kind !== 'removed') continue
    if (!revertedSet.value.has(change.key)) continue
    const bucket =
      change.level === 'section'
        ? marks.sections
        : change.level === 'row'
          ? marks.rows
          : marks.contents
    bucket[change.nodeId] = 'removed'
  }
  return marks
})

/**
 * 每处改动的按钮只放在"节点存在的那一栏"：
 *  - 改 / 增 → 右栏；删除 → 左栏（删除的节点右栏本来就没有）。
 */
const controlsBefore = computed<DiffControls>(() =>
  buildControls(diff.value, 'before', revertedSet.value, (key) => emit('toggle', key)),
)
const controlsAfter = computed<DiffControls>(() =>
  buildControls(diff.value, 'after', revertedSet.value, (key) => emit('toggle', key)),
)

/** 某一侧被标记的内容块数（栏头显示"本侧改动几处"） */
const markedCount = (marks: DiffMarks) => Object.keys(marks.contents).length

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
        <span v-if="revertedCount" class="diff-reverted">已还原 {{ revertedCount }} 处</span>
        <!-- 配色只按「栏」区分：左绿 = 修改前，右红 = AI 修改，已还原回到绿色 -->
        <span v-if="hasChanges" class="diff-legend">
          <span class="legend-item"><i class="legend-dot before"></i>修改前</span>
          <span class="legend-item"><i class="legend-dot after"></i>AI 修改</span>
          <span class="legend-item"><i class="legend-dot reverted"></i>已还原</span>
        </span>
      </div>
    </template>

    <div class="diff-body">
      <!-- 左：原始简历（静态；每处改动都能在这里看到"改前"的样子，绿色） -->
      <div class="diff-col diff-col-before">
        <div class="col-head">
          <span class="col-title">修改前 · 原始简历</span>
          <span class="col-hint">{{ markedCount(diff.before) }} 处改动</span>
        </div>
        <div ref="leftEl" class="col-scroll">
          <div class="col-paper" :style="paperStyle">
            <PreviewSection
              v-for="s in props.before"
              :key="s.id"
              :section="s"
              :marks="diff.before"
              :controls="controlsBefore"
            />
          </div>
        </div>
      </div>

      <!-- 右：修改后 · 当前结果（逐处切换后实时更新；AI 修改为红色，已还原为绿色） -->
      <div class="diff-col diff-col-after">
        <div class="col-head">
          <span class="col-title">修改后 · 当前结果</span>
          <span class="col-hint">
            {{ hasChanges ? `采用 ${diff.changedCount - revertedCount} 处` : '无改动' }}
          </span>
        </div>
        <div ref="rightEl" class="col-scroll">
          <div class="col-paper" :style="paperStyle">
            <PreviewSection
              v-for="s in result"
              :key="s.id"
              :section="s"
              :marks="marksAfter"
              :controls="controlsAfter"
            />
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="diff-footer">
        <span class="diff-footer-tip">
          左栏<span class="tip-before">绿色</span>是修改前原始内容，右栏<span class="tip-after">红色</span>是 AI 修改；
          点每处左侧的 <b>↺</b> 还原为原始内容，<b>↻</b> 恢复 AI 修改。确认后才会写入当前简历
        </span>
        <div class="diff-footer-actions">
          <!-- 全部还原：只要有还没还原的处就能点（一开始就是启用状态）；
               全部接受：只有在已经还原过一些处时才有意义 -->
          <n-button
            v-if="hasChanges"
            size="small"
            quaternary
            :disabled="revertedCount >= diff.changedCount"
            @click="emit('revert-all')"
          >
            全部还原
          </n-button>
          <n-button
            v-if="hasChanges"
            size="small"
            quaternary
            :disabled="revertedCount === 0"
            @click="emit('accept-all')"
          >
            全部接受
          </n-button>
          <n-button size="small" @click="onClose">
            {{ hasChanges ? '取消' : '关闭' }}
          </n-button>
          <n-button v-if="hasChanges" size="small" type="primary" @click="emit('apply')">
            确定应用
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
  color: var(--warning);
}
.diff-count.none {
  color: var(--text-tertiary);
  font-weight: 400;
}
.diff-reverted {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
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
/* 图例色块：与下面两栏的配色保持一致 */
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.legend-dot.before {
  background: #4b6b5e;
}
.legend-dot.after {
  background: #a94f4a;
}
.legend-dot.reverted {
  background: transparent;
  border: 1px dashed #4b6b5e;
}

/* ---------- 左 / 右两栏 ---------- */
.diff-body {
  display: flex;
  align-items: stretch;
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
/* ---------- 改动的配色：按「栏」区分，而不是按改动类型 ----------
 * 左栏 = 修改前的原始内容（绿色）；右栏 = AI 修改（红色）。
 * 用户在某处点了 ↺ 后，右栏那块会渲染成修改前的原文，并落到 data-diff="restored"
 * （绿色）—— 与"仍是 AI 修改"的红色一眼可分。
 * 这里用 :deep 是因为 [data-diff] 挂在三个预览子组件的内部元素上。 */
.diff-col-before :deep([data-diff]) {
  --diff-color: #4b6b5e;
  --diff-bg: rgba(75, 107, 94, 0.12);
}
.diff-col-after :deep([data-diff]) {
  --diff-color: #a94f4a;
  --diff-bg: rgba(169, 79, 74, 0.11);
}
.diff-col-after :deep([data-diff='restored']) {
  --diff-color: #4b6b5e;
  --diff-bg: rgba(75, 107, 94, 0.1);
}
.diff-col-after :deep([data-diff='ignored']) {
  --diff-color: #8a9199;
  --diff-bg: rgba(138, 145, 153, 0.1);
}

.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: var(--surface-soft);
  border-bottom: 1px solid var(--border);
}
.col-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.col-hint {
  font-size: 12px;
  color: var(--text-tertiary);
}
/* 滚动容器：高度固定，超出才有得滚（同步滚动的前提） */
.col-scroll {
  height: 68vh;
  overflow: auto;
  padding: 16px;
  background: var(--surface-sunken);
}
/* 纸面：宽度 / 缩放走 inline style（与页面预览共用 previewZoom） */
.col-paper {
  margin: 0 auto;
  background: var(--panel-bg);
  box-shadow: var(--shadow-paper);
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
  color: var(--text-tertiary);
}
.diff-footer-tip b {
  color: var(--text-secondary);
  font-weight: 700;
}
.tip-before {
  color: #4b6b5e;
  font-weight: 600;
}
.tip-after {
  color: #a94f4a;
  font-weight: 600;
}
.diff-footer-actions {
  display: flex;
  gap: 8px;
}
</style>
