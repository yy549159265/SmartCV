/** 招聘信息与动态维度共用的行拆分逻辑。 */

import type { PaneModule, PanelRow, RowGroup } from '@/types/market'
import type { CategoryModule } from './types'

/** 岗位概览固定四条事实：岗位名称 / 薪资 / 经验 / 代表公司。 */
export const JOB_OVERVIEW_KEYS = new Set(['jobs:roles', 'jobs:salary', 'jobs:years', 'jobs:companies'])

/** 其它结论按 kind 分成 fact / bar / step / pair 四块，只留白分隔，不写类型标题。 */
const EXTRA_KIND_ORDER = ['fact', 'bar', 'step', 'pair']

/** 招聘信息按「概览 / 技能 / 其它结论 / 跨源」拆分。 */
export function buildJobModules(rows: PanelRow[]): PaneModule[] {
  const clean = rows.filter((row) => row.kind !== 'divider')
  const own = clean.filter((row) => !row.synthesis && row.kind !== 'bar')
  const overview = own.filter((row) => JOB_OVERVIEW_KEYS.has(row.key))
  const extra = own.filter((row) => !JOB_OVERVIEW_KEYS.has(row.key))
  const skills = clean.filter((row) => !row.synthesis && row.kind === 'bar')
  const syn = clean.filter((row) => row.synthesis)
  const list: PaneModule[] = []
  if (overview.length) list.push({ key: 'overview', label: '岗位概览', meta: '', rows: overview })
  if (skills.length) list.push({ key: 'skills', label: '技能要求', meta: '', rows: skills })
  if (extra.length) list.push({ key: 'extra', label: '其它结论', meta: '', rows: extra })
  if (syn.length) list.push({ key: 'syn', label: '跨源分析', meta: `${syn.length} 条`, rows: syn })
  return list
}

/** 动态维度按「本维度分析 + 跨源分析」拆分。 */
export function buildDynamicModules(rows: PanelRow[], label: string): PaneModule[] {
  const clean = rows.filter((row) => row.kind !== 'divider')
  const main = clean.filter((row) => !row.synthesis)
  const syn = clean.filter((row) => row.synthesis)
  const list: PaneModule[] = []
  if (main.length) list.push({ key: 'main', label: `${label}分析`, meta: '', rows: main })
  if (syn.length) list.push({ key: 'syn', label: '跨源分析', meta: `${syn.length} 条`, rows: syn })
  return list
}

/**
 * 招聘信息的「其它结论」和动态方面的「本维度分析」都按行 kind 分块；
 * 其它模块保持原样，整块一起渲染。
 */
export function splitRowGroups(
  rows: PanelRow[],
  tabKey: string,
  moduleKey: string,
  dynamic: boolean,
): RowGroup[] {
  const grouped = (tabKey === 'jobs' && moduleKey === 'extra') || (dynamic && moduleKey === 'main')
  if (!grouped) return [{ key: `${tabKey}:all`, rows, block: false }]
  const known = new Set<string>(EXTRA_KIND_ORDER)
  const groups: RowGroup[] = EXTRA_KIND_ORDER.map((kind) => ({
    key: `extra:${tabKey}:${kind}`,
    rows: rows.filter((row) => row.kind === kind),
    block: true,
  })).filter((group) => group.rows.length)
  const rest = rows.filter((row) => !known.has(row.kind))
  if (rest.length) groups.push({ key: `extra:${tabKey}:other`, rows: rest, block: true })
  return groups
}

/** PaneModule → 汇总卡下方的横向标签。 */
export function toCategoryModules(modules: PaneModule[]): CategoryModule[] {
  return modules.map((mod) => ({
    key: mod.key,
    label: mod.label,
    tabLabel: mod.label,
    meta: mod.meta,
    rows: mod.rows,
  }))
}
