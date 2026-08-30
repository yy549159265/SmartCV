/**
 * 受控"点击开关"弹层（修复 naive-ui 的 clickoutside 与过渡卡死问题）
 *
 * 用法：
 *   const { show, triggerRef } = useClickPopover()
 *   <n-popover v-model:show="show" trigger="click">
 *     <template #trigger><button ref="triggerRef">...</button></template>
 *     ...
 *   </n-popover>
 *
 * 原理：v-model:show 接管显示状态；本组合式函数在 document 上挂一个
 * capture 阶段的 click 监听：点触发按钮 = 交给 naive 自己切换（开/关），
 * 点弹层内部 = 不动，点其它任何地方 = 关闭。
 *
 * 注意：触发器若是 naive 组件（如 n-button），请把 ref 放在包裹它的原生元素上
 * （组件实例没有 contains 方法）。配合 global.css 里禁用 popover 过渡的样式，
 * 弹层开合都是瞬时完成，不会出现"关不掉"的卡死状态。
 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useClickPopover(): { show: Ref<boolean>; triggerRef: Ref<HTMLElement | null> } {
  const show = ref(false)
  const triggerRef = ref<HTMLElement | null>(null)

  function onDocClick(e: MouseEvent) {
    if (!show.value) return
    const el = e.target as Node | null
    if (!el) return
    // 点触发按钮：交给 naive 的 toggle 逻辑
    const trigger = triggerRef.value
    if (trigger instanceof HTMLElement && trigger.contains(el)) return
    // 点在任意打开的弹层内部（弹层被传送到 body）：不关
    for (const pop of document.querySelectorAll('.n-popover')) {
      if (pop.contains(el)) return
    }
    show.value = false
  }

  onMounted(() => document.addEventListener('click', onDocClick, true))
  onBeforeUnmount(() => document.removeEventListener('click', onDocClick, true))

  return { show, triggerRef }
}
