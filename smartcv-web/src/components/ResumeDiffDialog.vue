<script setup lang="ts">
/**
 * AI 修改对比弹窗 —— 「诊断简历」页收到后端改好的简历后弹出来给用户过目。
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
import { computed, nextTick, ref, watch } from 'vue'
import PreviewSection from './PreviewSection.vue'
import {
  buildControls,
  collectContentUnits,
  coordToTarget,
  diffResume,
  inlineDiffHtml,
  mergeResume,
  type DiffControls,
  type DiffMarks,
} from '@/utils/resumeDiff'
import { useSyncScroll } from '@/composables/useSyncScroll'
import { previewZoom } from '@/composables/usePreviewZoom'
import { contentWidth } from '@/composables/usePageSize'
import type { DiagnosisItem } from '@/api/chat'
import type { Section } from '@/types'

const props = withDefaults(
  defineProps<{
    show: boolean
    /** 修改前的简历（发请求前深拷贝的快照） */
    before: Section[]
    /** 修改后的简历（后端返回的原始 JSON） */
    after: Section[]
    /** 已还原的改动 key 列表（`section:id` / `row:id` / `content:id`） */
    reverted: string[]
    /** 弹窗标题：聊天修改 / 全文纠错共用这个弹窗 */
    title?: string
    /** 本次诊断项（带 s/r/c/i 坐标），用于把每处改动关联到对应诊断卡片 */
    diagnosis?: DiagnosisItem[]
    /** 从诊断页「查看对比」跳回来时的目标：{ key, nonce }，nonce 保证连点同一处也重新闪烁 */
    flash?: { key: string; nonce: number } | null
  }>(),
  { title: 'AI 修改对比' },
)

const emit = defineEmits<{
  'update:show': [boolean]
  apply: []
  /** 放弃本次修改：简历保持原样，并清掉待确认状态 */
  discard: []
  /** 切换某一处：接受 ↔ 还原 */
  toggle: [key: string]
  'revert-all': []
  'accept-all': []
  /** 跳到某条诊断（打开诊断结论弹窗并定位到对应卡片） */
  'jump-diagnosis': [index: number]
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
    // 单元表是两层结构：外层复制一份，避免和 diff.after 共用引用
    units: Object.fromEntries(
      Object.entries(diff.value.after.units).map(([id, map]) => [id, { ...map }]),
    ),
  }
  for (const change of diff.value.changes) {
    if (change.kind !== 'removed') continue
    if (!revertedSet.value.has(change.key)) continue
    // 单元级只会出现"文字被替换"，不会有删除，所以只处理三层
    if (change.level === 'unit') continue
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
  buildControls(diff.value, 'before', revertedSet.value, (key) => emit('toggle', key), diagIndexByKey.value, jumpToDiagnosis),
)
const controlsAfter = computed<DiffControls>(() =>
  buildControls(diff.value, 'after', revertedSet.value, (key) => emit('toggle', key), diagIndexByKey.value, jumpToDiagnosis),
)

/** 跳转到某条诊断：转发给父组件（打开诊断结论弹窗并定位） */
function jumpToDiagnosis(index: number) {
  emit('jump-diagnosis', index)
}

/**
 * 诊断坐标 → 改动 key 的映射。
 * 诊断项 [s r c i] 指向一个「文字单元」；对应改动可能是单元级（只改文字）
 * 也可能是内容级（类型/样式/项数也变了）。两种 key 都登记，单元级优先。
 */
const diagIndexByKey = computed<ReadonlyMap<string, number>>(() => {
  const map = new Map<string, number>()
  for (let idx = 0; idx < (props.diagnosis?.length ?? 0); idx++) {
    const d = props.diagnosis![idx]
    if (d.s == null || d.r == null || d.c == null || d.i == null) continue
    const target = coordToTarget(props.before, d.s, d.r, d.c, d.i)
    if (!target) continue
    const unitKey = `unit:${target.contentId}:${target.unitIndex}`
    if (!map.has(unitKey)) map.set(unitKey, idx)
    const contentKey = `content:${target.contentId}`
    if (!map.has(contentKey)) map.set(contentKey, idx)
  }
  return map
})

/**
 * 右栏「修改后」一栏的内联词级 diff：内容 id → 单元序号 → diff HTML。
 * 只对单元级改动（纯文字替换）生成：原文删除线 + 新文高亮，其余照常渲染。
 */
const afterInlineDiffs = computed<Record<string, Record<number, string>>>(() => {
  const beforeUnits = collectContentUnits(props.before)
  const afterUnits = collectContentUnits(props.after)
  const out: Record<string, Record<number, string>> = {}
  for (const change of diff.value.changes) {
    if (change.level !== 'unit') continue
    const i = change.unitIndex ?? 0
    const before = beforeUnits.get(change.nodeId)?.[i]
    const after = afterUnits.get(change.nodeId)?.[i]
    if (before === undefined || after === undefined || before === after) continue
    ;(out[change.nodeId] ??= {})[i] = inlineDiffHtml(before, after)
  }
  return out
})

/** 某一侧被标记的处数（内容块 + 内容里的文字单元；栏头显示"本侧改动几处"） */
const markedCount = (marks: DiffMarks) =>
  Object.keys(marks.contents).length +
  Object.values(marks.units).reduce((n, map) => n + Object.keys(map).length, 0)

/* ---------- 同步滚动 ---------- */
const leftEl = ref<HTMLElement | null>(null)
const rightEl = ref<HTMLElement | null>(null)

/**
 * 正在执行「跳到某处改动」的滚动定位。
 *
 * 两栏是比例同步滚动的：直接 scrollIntoView 两栏时，左栏滚一下会按比例把右栏
 * 拽回去，右栏滚一下又反过来拽左栏，两个平滑动画互相覆盖，最后停在哪算哪 ——
 * 表现就是「跳过来不定位」。定位期间先关掉同步，让两栏各自滚到自己的目标。
 */
const jumping = ref(false)
let jumpTimer = 0

useSyncScroll(leftEl, rightEl, () => props.show && !jumping.value)

/** 诊断页「查看对比」跳回来：滚动定位到目标改动并红框闪烁几秒 */
watch(
  () => props.flash?.nonce,
  (nonce) => {
    if (nonce == null) return
    const key = props.flash!.key
    // 对比弹窗可能刚好从「关闭」状态被重新打开（onJumpToDiff 会先 diffOpen=true），
    // 两侧 A4 预览比诊断列表重得多，一次 nextTick 甚至十几帧都可能还没挂载完；
    // 用时间预算（最多约 2s）逐帧重试，直到目标元素出现，而不是固定只试 12 帧。
    const deadline = performance.now() + 2000
    const locate = () => {
      const sel = `[data-diff-key="${key}"]`
      const elL = leftEl.value?.querySelector<HTMLElement>(sel)
      const elR = rightEl.value?.querySelector<HTMLElement>(sel)
      // 元素找到了但两栏还没真正排出来（弹窗刚挂载 / 还在 display:none 里）时，
      // scrollIntoView 算不出距离、滚不动 —— 必须等容器有了高度再滚。
      const laidOut = (pane: HTMLElement | null) => !!pane && pane.clientHeight > 0
      const panesReady = (!elL || laidOut(leftEl.value)) && (!elR || laidOut(rightEl.value))
      if ((elL || elR) && panesReady) {
        // 定位期间关掉同步滚动，否则两栏的平滑滚动会互相覆盖
        jumping.value = true
        window.clearTimeout(jumpTimer)
        jumpTimer = window.setTimeout(() => {
          jumping.value = false
        }, 900)
        // 新增/删除只在其中一栏有元素，另一栏不滚动；都有的两边各自滚到可见
        elL?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        elR?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        ;[elL, elR].forEach((el) => {
          if (!el) return
          el.classList.remove('diff-flash')
          // 强制重排，让连点同一处时动画能重新播放
          void el.offsetWidth
          el.classList.add('diff-flash')
          window.setTimeout(() => el.classList.remove('diff-flash'), 2400)
        })
        return
      }
      if (performance.now() < deadline) requestAnimationFrame(locate)
    }
    void nextTick(() => locate())
  },
  // 对比弹窗可能刚好从「关闭」状态被重新打开（此时 flash 已就位），
  // immediate 让首次挂载也执行一次，否则这次跳转不会闪烁。
  { immediate: true },
)

/** 栏内纸张：与页面预览同宽同缩放，两边看到的排版、换行都一致 */
const paperStyle = computed(() => ({
  width: `${contentWidth.value}px`,
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
    :title="props.title"
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
              :unit-diffs="afterInlineDiffs"
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
          <!-- 明确放弃：清掉待确认状态，否则它会一直挡着下一次纠错 / 对话 -->
          <n-button size="small" type="error" ghost @click="emit('discard')">放弃修改</n-button>
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
  gap: 8px;
  flex-wrap: wrap;
}
.diff-count {
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--warning-soft);
  font-size: 12px;
  font-weight: 600;
  color: var(--warning);
  white-space: nowrap;
}
.diff-count.none {
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-weight: 400;
}
.diff-reverted {
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--success-soft);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--success);
  white-space: nowrap;
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
  width: 9px;
  height: 9px;
  border-radius: 2px;
}
.legend-dot.before {
  background: var(--success);
}
.legend-dot.after {
  background: var(--danger);
}
.legend-dot.reverted {
  background: transparent;
  border: 1px dashed var(--success);
}

/* ---------- 左 / 右两栏 ---------- */
.diff-body {
  display: flex;
  align-items: stretch;
  gap: 14px;
}
.diff-col {
  flex: 1 1 50%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--panel-bg);
}
/* 打开弹窗时两栏从各自一侧轻轻对齐到中间；只动内容，不碰弹窗开合 */
.diff-col-before {
  animation: diff-col-left 0.32s var(--ease) both;
}
.diff-col-after {
  animation: diff-col-right 0.32s var(--ease) 0.05s both;
}
/* ---------- 改动的配色：按「栏」区分，而不是按改动类型 ----------
 * 左栏 = 修改前的原始内容（绿色）；右栏 = AI 修改（红色）。
 * 用户在某处点了 ↺ 后，右栏那块会渲染成修改前的原文，并落到 data-diff="restored"
 * （绿色）—— 与"仍是 AI 修改"的红色一眼可分。
 * 这里用 :deep 是因为 [data-diff] 挂在三个预览子组件的内部元素上。 */
.diff-col-before :deep([data-diff]) {
  --diff-color: var(--success);
  --diff-bg: rgba(63, 143, 90, 0.12);
}
.diff-col-after :deep([data-diff]) {
  --diff-color: var(--danger);
  --diff-bg: rgba(169, 79, 74, 0.11);
}
.diff-col-after :deep([data-diff='restored']) {
  --diff-color: var(--success);
  --diff-bg: rgba(63, 143, 90, 0.1);
}
.diff-col-after :deep([data-diff='ignored']) {
  --diff-color: var(--text-tertiary);
  --diff-bg: rgba(138, 145, 166, 0.1);
}
/* 逐处还原 / 恢复时，标记颜色平滑过渡，让"这一块变了"看得见 */
.diff-col :deep([data-diff]) {
  transition: background-color 0.18s var(--ease), box-shadow 0.18s var(--ease);
}

.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 14px;
  background: var(--surface-soft);
  border-bottom: 1px solid var(--border);
}
/* 栏头小圆点：颜色与这一栏的改动标记一致（左绿 / 右红） */
.col-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.col-title::before {
  content: '';
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.diff-col-before .col-title::before {
  background: var(--success);
}
.diff-col-after .col-title::before {
  background: var(--danger);
}
.col-hint {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--panel-bg);
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
/* 滚动容器：高度固定，超出才有得滚（同步滚动的前提）；
   工作区 / 纸面阴影与页面预览共用同一组变量 */
.col-scroll {
  height: 68vh;
  overflow: auto;
  padding: 20px 18px 40px;
  background: var(--doc-workspace);
}
/* 纸面：宽度 / 缩放走 inline style（与页面预览共用 previewZoom） */
.col-paper {
  margin: 0 auto;
  background: var(--doc-paper);
  box-shadow: var(--doc-paper-shadow);
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
  color: var(--success);
  font-weight: 600;
}
.tip-after {
  color: var(--danger);
  font-weight: 600;
}
.diff-footer-actions {
  display: flex;
  gap: 8px;
}

/* 两栏从各自一侧轻微收拢，给弹窗内部一个"打开"的节奏（弹窗本身仍瞬时开合） */
@keyframes diff-col-left {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes diff-col-right {
  from {
    opacity: 0;
    transform: translateX(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
