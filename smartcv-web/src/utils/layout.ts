import type { LayoutWindow } from '@/types'

function cellCount(row: LayoutWindow): number {
  if (!Array.isArray(row.rows)) return 1
  if (row.layout === 'horizontal') return Math.max(row.rows.length, 1)
  return computeTableCols(row.rows)
}

export function computeTableCols(rows: LayoutWindow[]): number {
  let cols = 1
  for (const row of rows) {
    cols = Math.max(cols, cellCount(row))
  }
  return cols
}

export function spanForIndex(index: number, count: number, total: number): number {
  if (count <= 0) return 1
  const base = Math.floor(total / count)
  const extra = total % count
  return base + (index < extra ? 1 : 0)
}
