<script setup lang="ts">
/**
 * 对比弹窗里"一处改动"的切换按钮。
 *
 * 语义（三种改动统一）：
 *  - 当前采用 AI 的修改 → ↺「还原为修改前」
 *  - 已还原             → ↻「恢复 AI 修改」
 *
 * 另外：当这处改动能关联到某条诊断（ChangeView.jumpToDiagnosis 有值）时，
 * 在旁边多一个「查看诊断」按钮，点它跳到对应的诊断卡片。
 *
 * 颜色不在这里写死：取所在元素继承下来的 --diff-color ——
 * 左栏（修改前）是绿色、右栏（AI 修改）是红色、已还原的处是绿色。
 * 按钮只负责把点击冒泡给父级（ChangeView.toggle / jumpToDiagnosis 由弹窗注入），
 * 具体挂在哪一栏、哪个位置由三个预览组件决定。
 */
import { computed } from 'vue'
import IconGlyph from './IconGlyph.vue'
import type { ChangeView } from '@/utils/resumeDiff'

const props = defineProps<{ view: ChangeView }>()

/** 图标 = 点击后这处会变成什么：↺ 回到修改前 / ↻ 恢复 AI 修改 */
const icon = computed(() => (props.view.reverted ? '↻' : '↺'))

const tooltip = computed(() =>
  props.view.reverted ? '恢复 AI 修改（↻）' : '还原为修改前的内容（↺）',
)
</script>

<template>
  <!-- 外框只负责横排多个按钮；定位（.diff-action-float）由父组件挂在外框上 -->
  <span class="diff-actions">
    <!-- 查看诊断放左边，还原/恢复按钮留在贴近正文的位置（左边缘 -20px 处） -->
    <button
      v-if="view.jumpToDiagnosis"
      type="button"
      class="diff-action diff-action-jump"
      title="查看这条诊断"
      aria-label="查看这条诊断"
      @click.stop="view.jumpToDiagnosis()"
      @mousedown.stop
    >
      <IconGlyph name="file-text" :size="11" :stroke-width="2.2" />
    </button>
    <button
      type="button"
      class="diff-action"
      :class="{ reverted: view.reverted }"
      :title="tooltip"
      :aria-label="tooltip"
      @click.stop="view.toggle()"
      @mousedown.stop
    >
      {{ icon }}
    </button>
  </span>
</template>

<style scoped>
/* 外框本身不占位（绝对定位由父级 .diff-action-float 提供）；
   多按钮时整体向左挪，让还原按钮始终贴着正文左缘（见下面的 transform）。 */
.diff-actions {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  /* 还原按钮是最后一项，右缘应对准正文左缘（x=0）。父级 .diff-action-float
     把外框左缘钉在 -20px 处，这里按「外框总宽 - 20px」整体左移，
     于是右侧多出来的按钮会向左扩展，还原按钮位置不变。 */
  transform: translateX(calc(-100% + 20px));
}

.diff-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 20px;
  height: 20px;
  padding: 0;
  /* 颜色跟随所在区块：左栏绿 / 右栏红 / 已还原绿（见 global.css 的 --diff-color） */
  border: 1.5px solid currentColor;
  border-radius: 50%;
  background: var(--panel-bg, #fff);
  color: var(--diff-color, #a6763f);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  user-select: none;
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.12),
    0 4px 10px -6px rgba(28, 33, 48, 0.28);
  transition:
    transform 0.16s var(--ease),
    background-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
/* 已还原：虚线圈 + 淡底色，和"仍采用 AI 修改"一眼区分 */
.diff-action.reverted {
  border-style: dashed;
  background: var(--diff-bg, rgba(0, 0, 0, 0.04));
}
.diff-action:hover {
  transform: scale(1.12);
  background: var(--panel-bg, #fff);
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.12),
    0 6px 14px -6px rgba(28, 33, 48, 0.32);
}
.diff-action:active {
  transform: scale(0.94);
}

/* 查看诊断：中性靛蓝，和还原按钮（红/绿）区分开，视觉上是次级操作 */
.diff-action-jump {
  color: var(--primary, #4753c7);
  border-width: 1px;
  font-weight: 400;
}
.diff-action-jump:hover {
  background: var(--primary-soft, #eceffb);
  color: var(--primary-hover, #3c46b2);
}
</style>
