/**
 * 布局工具：计算"表格列数"与跨列宽度（span）
 *
 * 一个纵向堆叠的窗口列表（章节的 rows 或竖向容器的 rows）可以看作一张表格：
 *  - 横向容器 = 表格的一行，它的子窗口是这一行的若干列；
 *  - 竖向容器 = 递归地再看它内部的最大列数；
 *  - 叶子窗口（contents）= 占满整行，不抬高列数。
 *
 * 为了让多行之间的格子对齐（比如「布局4 横跨 2 列、布局5 正好对齐到第 3 列下方」），
 * 需要先算出全局列数，再把每一行子窗口的数量均分到这列数上（前面的格子多分一列）。
 */
import type { LayoutWindow } from '@/types'

/** 一个窗口占多少列（用于求"全局最大列数"） */
function cellCount(row: LayoutWindow): number {
  // 叶子窗口：整行（不抬高列数，渲染时占满整行）
  if (!Array.isArray(row.rows)) return 1
  // 横向容器：列数 = 子窗口数量
  if (row.layout === 'horizontal') return Math.max(row.rows.length, 1)
  // 竖向容器：递归取它内部的最大列数
  return computeTableCols(row.rows)
}

/** 求一个纵向堆叠列表的"表格列数"（各行对齐用的全局列数，至少 1） */
export function computeTableCols(rows: LayoutWindow[]): number {
  let cols = 1
  for (const row of rows) {
    cols = Math.max(cols, cellCount(row))
  }
  return cols
}

/**
 * 把 total 列均分给 count 个格子，返回第 index 个格子占几列。
 * 均分策略：商 + 前面的格子多分一列（如 3 列分给 2 格 → [2, 1]）。
 * 当 total === count 时，全部为 1 列（和普通等分行一致，旧布局不产生变化）。
 */
export function spanForIndex(index: number, count: number, total: number): number {
  if (count <= 0) return 1
  const base = Math.floor(total / count)
  const extra = total % count
  return base + (index < extra ? 1 : 0)
}
