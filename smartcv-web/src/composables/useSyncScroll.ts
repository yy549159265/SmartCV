import { onBeforeUnmount, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

function syncRatio(one: HTMLElement, two: HTMLElement): void {
  const oneMax = one.scrollHeight - one.clientHeight
  const twoMax = two.scrollHeight - two.clientHeight

  const ratio = oneMax > 0 ? one.scrollTop / oneMax : 0
  if (twoMax > 0) two.scrollTop = ratio * twoMax

  const oneMaxX = one.scrollWidth - one.clientWidth
  const twoMaxX = two.scrollWidth - two.clientWidth
  if (oneMaxX > 0 && twoMaxX > 0) {
    two.scrollLeft = (one.scrollLeft / oneMaxX) * twoMaxX
  }
}

export function useSyncScroll(
  left: Ref<HTMLElement | null>,
  right: Ref<HTMLElement | null>,
  enabled?: () => boolean,
): void {
  let syncing = false

  const onScroll = (from: Ref<HTMLElement | null>, to: Ref<HTMLElement | null>) => () => {
    if (syncing) return
    if (enabled && !enabled()) return
    const one = from.value
    const two = to.value
    if (!one || !two) return

    syncing = true
    syncRatio(one, two)
    requestAnimationFrame(() => {
      syncing = false
    })
  }

  useEventListener(left, 'scroll', onScroll(left, right))
  useEventListener(right, 'scroll', onScroll(right, left))

  onBeforeUnmount(() => {
    syncing = false
  })
}
