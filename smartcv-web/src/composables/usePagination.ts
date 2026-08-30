/**
 * 分页测量组合式函数
 *
 * 原理（任务要求：分页计算逻辑与视图分离）：
 *   1. 右侧预览组件里有一个"隐藏测量层"，把全部章节连续渲染一遍
 *      （和 A4 内容区等宽，使用与预览完全相同的组件 → 高度天然一致）；
 *   2. 本函数测量测量层里每个章节的偏移，把它的标题、顶层行分别拍平成"可裁切单元"(PageUnit)；
 *   3. 交给 utils/pagination.ts 的纯函数 computePages 按"单元粒度"算出分页方案；
 *   4. 把分页方案 + 单元列表一并写入 store.pagePlan / store.pageUnits ——
 *      预览（分页渲染）与导出（预分页块）共用，页数才真正一致。
 *
 * 重新测量的时机：简历数据变化（含样式、内容编辑）、窗口尺寸变化、字体加载完成。
 */
import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'
import { useDebounceFn, useEventListener } from '@vueuse/core'
import { computePages, type PageUnit } from '@/utils/pagination'
import { CONTENT_HEIGHT } from '@/utils/constants'
import { useResumeStore } from '@/stores/resume'

export function usePagination(flowEl: Ref<HTMLElement | null>) {
  const store = useResumeStore()

  /** 测量 + 计算，最终把分页方案写进 store */
  const measure = () => {
    const el = flowEl.value
    if (!el) return
    const nodes = el.querySelectorAll<HTMLElement>('[data-section-id]')
    if (nodes.length === 0) {
      store.setPagination({ pages: [], pageStartOffsets: [], totalHeight: 0 }, [])
      return
    }

    // 以第一个章节的位置为 0 点，算出每个"截面"（标题 + 顶层行）的相对偏移和高度
    const base = nodes[0].offsetTop

    // 拍平成单元列表：标题是一个单元，每一个顶层行也是一个单元（按顺序排）
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

    // 单元粒度分页：长章节也能在"上一页剩下的空隙"里继续排，页数真实不虚高
    const plan = computePages(units, CONTENT_HEIGHT)
    store.setPagination(plan, units)
  }

  // 防抖 120ms：打字/拖拽时连续触发也只量一次，避免卡顿
  const debouncedMeasure = useDebounceFn(measure, 120)

  // 数据一变就重新量（deep：内容、样式、顺序任何变化都算）
  watch(
    () => store.resume,
    () => {
      // 等 Vue 渲染完再量，否则量到的是旧 DOM
      nextTick(debouncedMeasure)
    },
    { deep: true },
  )

  // 测量层元素挂载后、以及它自身尺寸变化时重新量
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

  // 窗口尺寸变化重新量（虽然内容宽度固定，但保险起见）
  useEventListener(window, 'resize', debouncedMeasure)

  // 字体文件加载完成后重新量（字体影响文字高度）
  if (typeof document !== 'undefined' && 'fonts' in document) {
    document.fonts.ready.then(() => debouncedMeasure()).catch(() => {})
  }

  onBeforeUnmount(() => observer?.disconnect())
}
