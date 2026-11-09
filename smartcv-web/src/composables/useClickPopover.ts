import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useClickPopover(): { show: Ref<boolean>; triggerRef: Ref<HTMLElement | null> } {
  const show = ref(false)
  const triggerRef = ref<HTMLElement | null>(null)

  function onDocClick(e: MouseEvent) {
    if (!show.value) return
    const el = e.target as Node | null
    if (!el) return
    const trigger = triggerRef.value
    if (trigger instanceof HTMLElement && trigger.contains(el)) return
    for (const pop of document.querySelectorAll('.n-popover')) {
      if (pop.contains(el)) return
    }
    show.value = false
  }

  onMounted(() => document.addEventListener('click', onDocClick, true))
  onBeforeUnmount(() => document.removeEventListener('click', onDocClick, true))

  return { show, triggerRef }
}
