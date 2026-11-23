/** 产出总线的固定文案：类别名与维度简称。 */

export const TAB_LABEL: Record<string, string> = {
  plan: '规划检索',
  collect: '采集页面',
  portrait: '简历画像',
  synthesis: '跨源分析',
  strategy: '策略总结',
  report: '汇总报告',
}

/** 固定维度统一成四字名，总线和流程图里对齐；动态方面的名字一律来自后端下发的 label。 */
export const DIM_META: Record<string, { short: string; node: string; section: string }> = {
  jobs: { short: '招聘矩阵', node: '招聘矩阵', section: 'overview' },
  trend: { short: '技术趋势', node: '技术趋势', section: 'skills' },
}

export function dimShort(dim: string, label = ''): string {
  return DIM_META[dim]?.short || label || dim
}

export function dimNodeText(dim: string, label = ''): string {
  return DIM_META[dim]?.node || label || dim
}
