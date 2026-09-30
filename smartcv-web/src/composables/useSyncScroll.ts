/**
 * 双栏同步滚动 —— 「优化简历」对比弹窗专用。
 *
 * 左右两栏装的是同一份简历的改前 / 改后版本，行数、高度都不一样
 * （AI 改了字，块就变高了），所以【按比例】同步而不是按像素：
 *
 *   ratio = 本栏 scrollTop / 本栏可滚动高度
 *   另一栏.scrollTop = ratio × 另一栏可滚动高度
 *
 * 按像素映射的话，两边高度差多少就错位多少，滚到一半左侧还在第一章、
 * 右侧已经到第三章了；按比例则"开头对齐、结尾对齐、中间大致对应"，
 * 这正是对比阅读想要的。
 *
 * 防回环：给 A 栏写 scrollTop 会同步触发 A 栏的 scroll 事件，
 * 回调里又会去写 B 栏…… 所以用 syncing 标志挡住回程，
 * 并在 requestAnimationFrame 里复位（滚动事件在同一帧内派发）。
 */
import { onBeforeUnmount, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

/**
 * 把 two 的滚动位置对齐到 one 的相同比例
 * @param one 用户正在滚动的栏
 * @param two 要跟着滚的栏
 */
function syncRatio(one: HTMLElement, two: HTMLElement): void {
  // 可滚动高度为 0（内容没超出、或元素还没挂载）时不要除，直接留 0
  const oneMax = one.scrollHeight - one.clientHeight
  const twoMax = two.scrollHeight - two.clientHeight

  const ratio = oneMax > 0 ? one.scrollTop / oneMax : 0
  if (twoMax > 0) two.scrollTop = ratio * twoMax

  // 横向同理：两边都出现横向滚动条时才有意义（窄屏下 A4 可能被裁）
  const oneMaxX = one.scrollWidth - one.clientWidth
  const twoMaxX = two.scrollWidth - two.clientWidth
  if (oneMaxX > 0 && twoMaxX > 0) {
    two.scrollLeft = (one.scrollLeft / oneMaxX) * twoMaxX
  }
}

/**
 * 让两个滚动容器按比例同步滚动。
 *
 * @param left  左栏滚动容器（原始简历）
 * @param right 右栏滚动容器（修改后简历）
 * @param enabled 什么时候才同步；弹窗关着、或 DOM 已卸载时返回 false。
 *                不传 = 一直同步（监听本身绑在元素上，元素没了自动失效）。
 */
export function useSyncScroll(
  left: Ref<HTMLElement | null>,
  right: Ref<HTMLElement | null>,
  enabled?: () => boolean,
): void {
  /** 正在由本模块写入另一栏：此刻收到的 scroll 事件是自己的回程，直接忽略 */
  let syncing = false

  const onScroll = (from: Ref<HTMLElement | null>, to: Ref<HTMLElement | null>) => () => {
    if (syncing) return
    if (enabled && !enabled()) return
    const one = from.value
    const two = to.value
    if (!one || !two) return

    syncing = true
    syncRatio(one, two)
    // 下一帧复位：写 scrollTop 触发的 scroll 事件在本帧内派发完毕，
    // 用 rAF 而不是同步复位，才能挡住回程
    requestAnimationFrame(() => {
      syncing = false
    })
  }

  useEventListener(left, 'scroll', onScroll(left, right))
  useEventListener(right, 'scroll', onScroll(right, left))

  // 兜底：组件卸载时若正好卡在 syncing 中间，把标志清掉，
  // 避免下次挂载（弹窗重开）后第一下滚动被吃掉
  onBeforeUnmount(() => {
    syncing = false
  })
}
