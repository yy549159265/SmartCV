<script setup lang="ts">
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
    before: Section[]
    after: Section[]
    reverted: string[]
    title?: string
    diagnosis?: DiagnosisItem[]
    flash?: { key: string; nonce: number } | null
  }>(),
  { title: 'AI 修改对比' },
)

const emit = defineEmits<{
  'update:show': [boolean]
  apply: []
  discard: []
  toggle: [key: string]
  'revert-all': []
  'accept-all': []
  'jump-diagnosis': [index: number]
}>()

const diff = computed(() => diffResume(props.before, props.after))

const revertedSet = computed(() => new Set(props.reverted ?? []))

const revertedCount = computed(
  () => diff.value.changes.filter((c) => revertedSet.value.has(c.key)).length,
)

const hasChanges = computed(() => diff.value.changedCount > 0)

const result = computed(() => mergeResume(props.before, props.after, revertedSet.value).sections)

const marksAfter = computed<DiffMarks>(() => {
  const marks: DiffMarks = {
    sections: { ...diff.value.after.sections },
    rows: { ...diff.value.after.rows },
    contents: { ...diff.value.after.contents },
    units: Object.fromEntries(
      Object.entries(diff.value.after.units).map(([id, map]) => [id, { ...map }]),
    ),
  }
  for (const change of diff.value.changes) {
    if (change.kind !== 'removed') continue
    if (!revertedSet.value.has(change.key)) continue
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

const controlsBefore = computed<DiffControls>(() =>
  buildControls(diff.value, 'before', revertedSet.value, (key) => emit('toggle', key), diagIndexByKey.value, jumpToDiagnosis),
)
const controlsAfter = computed<DiffControls>(() =>
  buildControls(diff.value, 'after', revertedSet.value, (key) => emit('toggle', key), diagIndexByKey.value, jumpToDiagnosis),
)

function jumpToDiagnosis(index: number) {
  emit('jump-diagnosis', index)
}

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

const markedCount = (marks: DiffMarks) =>
  Object.keys(marks.contents).length +
  Object.values(marks.units).reduce((n, map) => n + Object.keys(map).length, 0)

const leftEl = ref<HTMLElement | null>(null)
const rightEl = ref<HTMLElement | null>(null)

const jumping = ref(false)
let jumpTimer = 0

useSyncScroll(leftEl, rightEl, () => props.show && !jumping.value)

watch(
  () => props.flash?.nonce,
  (nonce) => {
    if (nonce == null) return
    const key = props.flash!.key
    const deadline = performance.now() + 2000
    const locate = () => {
      const sel = `[data-diff-key="${key}"]`
      const elL = leftEl.value?.querySelector<HTMLElement>(sel)
      const elR = rightEl.value?.querySelector<HTMLElement>(sel)
      const laidOut = (pane: HTMLElement | null) => !!pane && pane.clientHeight > 0
      const panesReady = (!elL || laidOut(leftEl.value)) && (!elR || laidOut(rightEl.value))
      if ((elL || elR) && panesReady) {
        jumping.value = true
        window.clearTimeout(jumpTimer)
        jumpTimer = window.setTimeout(() => {
          jumping.value = false
        }, 900)
        elL?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        elR?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        ;[elL, elR].forEach((el) => {
          if (!el) return
          el.classList.remove('diff-flash')
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
  { immediate: true },
)

const paperStyle = computed(() => ({
  width: `${contentWidth.value}px`,
  zoom: previewZoom.value,
}))

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
    <template #header-extra>
      <div class="diff-header-extra">
        <span class="diff-count" :class="{ none: !hasChanges }">
          {{ hasChanges ? `共 ${diff.changedCount} 处修改` : '本次没有修改' }}
        </span>
        <span v-if="revertedCount" class="diff-reverted">已还原 {{ revertedCount }} 处</span>
        <span v-if="hasChanges" class="diff-legend">
          <span class="legend-item"><i class="legend-dot before"></i>修改前</span>
          <span class="legend-item"><i class="legend-dot after"></i>AI 修改</span>
          <span class="legend-item"><i class="legend-dot reverted"></i>已还原</span>
        </span>
      </div>
    </template>

    <div class="diff-body">
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
.diff-col-before {
  animation: diff-col-left 0.32s var(--ease) both;
}
.diff-col-after {
  animation: diff-col-right 0.32s var(--ease) 0.05s both;
}
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
.col-scroll {
  height: 68vh;
  overflow: auto;
  padding: 20px 18px 40px;
  background: var(--doc-workspace);
}
.col-paper {
  margin: 0 auto;
  background: var(--doc-paper);
  box-shadow: var(--doc-paper-shadow);
  padding: 24px;
}

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
