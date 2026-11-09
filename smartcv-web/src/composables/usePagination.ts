import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'
import { useDebounceFn, useEventListener } from '@vueuse/core'
import { computePages, type PageUnit } from '@/utils/pagination'
import { contentHeight } from '@/composables/usePageSize'
import { useResumeStore } from '@/stores/resume'

export function usePagination(flowEl: Ref<HTMLElement | null>) {
  const store = useResumeStore()

  const measure = () => {
    const el = flowEl.value
    if (!el) return
    const nodes = el.querySelectorAll<HTMLElement>('[data-section-id]')
    if (nodes.length === 0) {
      store.setPagination({ pages: [], pageStartOffsets: [], totalHeight: 0 }, [])
      return
    }

    const base = nodes[0].offsetTop

    const units: PageUnit[] = []
    for (const node of Array.from(nodes)) {
      const id = node.dataset.sectionId
      if (!id) continue

      const titleEl = node.querySelector<HTMLElement>('.preview-section-title')
      const rowEls = Array.from(
        node.querySelectorAll<HTMLElement>(':scope > .preview-rows > .preview-row'),
      )
      const sectionRowCount = rowEls.length
      const spaceBefore = parseFloat(node.style.marginTop) || 0
      const forced = node.dataset.forced === 'true'

      if (titleEl) {
        units.push({
          id: `${id}:title`,
          sectionId: id,
          kind: 'title',
          rowIndex: -1,
          offsetTop: titleEl.offsetTop - base,
          height: titleEl.offsetHeight,
          spaceBefore,
          sectionRowCount,
          forced,
        })
      }
      rowEls.forEach((r, ri) => {
        units.push({
          id: `${id}:row:${ri}`,
          sectionId: id,
          kind: 'row',
          rowIndex: ri,
          offsetTop: r.offsetTop - base,
          height: r.offsetHeight,
          spaceBefore: 0,
          sectionRowCount,
          forced: false,
        })
      })
    }

    const plan = computePages(units, contentHeight.value)
    store.setPagination(plan, units)
  }

  const debouncedMeasure = useDebounceFn(measure, 120)

  watch(
    () => store.resume,
    () => {
      nextTick(debouncedMeasure)
    },
    { deep: true },
  )

  let observer: ResizeObserver | null = null
  watch(flowEl, (el) => {
    observer?.disconnect()
    observer = null
    if (el) {
      observer = new ResizeObserver(debouncedMeasure)
      observer.observe(el)
      nextTick(debouncedMeasure)
    }
  })

  useEventListener(window, 'resize', debouncedMeasure)

  if (typeof document !== 'undefined' && 'fonts' in document) {
    document.fonts.ready.then(() => debouncedMeasure()).catch(() => {})
  }

  onBeforeUnmount(() => observer?.disconnect())
}
