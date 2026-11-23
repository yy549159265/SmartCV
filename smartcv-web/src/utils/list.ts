import type { ListItem } from '@/types'

/**
 * 有序列表编号：同级连续递增；向右缩进一级后，子层级从 1 另起编号；
 * 回到上层时，上层编号接着之前的序号继续。
 */
export function orderedMarkers(items: ListItem[]): number[] {
  const counters: number[] = []
  return items.map((item) => {
    const level = Math.max(item.indent ?? 0, 0)
    counters.length = level + 1
    counters[level] = (counters[level] ?? 0) + 1
    return counters[level]
  })
}
