<script setup lang="ts">
/**
 * 对比弹窗里"一处改动"的切换按钮。
 *
 * 语义（三种改动统一）：
 *  - 当前采用 AI 的修改 → ↺「还原为修改前」
 *  - 已还原             → ↻「恢复 AI 修改」
 *
 * 颜色不在这里写死：取所在元素继承下来的 --diff-color ——
 * 左栏（修改前）是绿色、右栏（AI 修改）是红色、已还原的处是绿色。
 * 按钮只负责把点击冒泡给父级（ChangeView.toggle 由弹窗注入），
 * 具体挂在哪一栏、哪个位置由三个预览组件决定。
 */
import { computed } from 'vue'
import type { ChangeView } from '@/utils/resumeDiff'

const props = defineProps<{ view: ChangeView }>()

/** 图标 = 点击后这处会变成什么：↺ 回到修改前 / ↻ 恢复 AI 修改 */
const icon = computed(() => (props.view.reverted ? '↻' : '↺'))

const tooltip = computed(() =>
  props.view.reverted ? '恢复 AI 修改（↻）' : '还原为修改前的内容（↺）',
)
</script>

<template>
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
</template>

<style scoped>
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
</style>
