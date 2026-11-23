/** 采集页面：按维度分组的站点进度 + 来源分布。 */

import { computed, reactive, ref, watch, type Ref } from 'vue'
import type {
  CollectDistribution,
  CollectGroup,
  DimInfo,
  DistRow,
  EvidenceLink,
  PanelRow,
} from '@/types/market'
import { dimShort } from './labels'
import { emptySummary, type CategoryCard, type CategoryModule, type CategoryRunSnapshot } from './types'

/** 采集页签的切换卡：来源分布固定第一页，后面每个调研维度一页。 */
export const DIST_MODULE_KEY = '__sources__'

/** 来源分布内部的两种口径：按站点（默认）或按维度，用右上角图标切换。 */
export type DistView = 'site' | 'dim'

export interface CollectCategoryOptions {
  /** 采集行（paneRows.collect）。 */
  rows: () => PanelRow[]
  dims: Ref<DimInfo[]>
  /** 证据编号索引，用于来源分布与站点展开。 */
  evidenceLinks: Record<string, EvidenceLink>
  /** 证据 → 维度；证据编号没带 kind 时由页面回查。 */
  linkKind: (link: EvidenceLink) => string
  /** 规划出的维度数：没有检索清单时退回本次维度数。 */
  planGroupCount: () => number
  pages: Ref<number>
  published: Ref<number>
  /** 本轮时间窗口文案，显示在卡片副标题里。 */
  windowText: Ref<string>
}

export function useCollectCategory(options: CollectCategoryOptions) {
  const { rows, dims, evidenceLinks, linkKind, planGroupCount, pages, published, windowText } =
    options

  const view = ref(DIST_MODULE_KEY)
  const distView = ref<DistView>('site')
  /** 采集条目展开状态，按行 key 记录。 */
  const open = reactive<Record<string, boolean>>({})

  /** 采集行按维度聚合：并行采集时行会交错到达，分组展示才不会串在一起。 */
  const groups = computed<CollectGroup[]>(() => {
    const order = dims.value.map((dim) => dim.id)
    const map = new Map<string, CollectGroup>()
    for (const row of rows()) {
      if (row.kind !== 'collect') continue
      const id = row.group || 'other'
      let group = map.get(id)
      if (!group) {
        group = {
          id,
          label: dimShort(id, row.groupLabel || dims.value.find((dim) => dim.id === id)?.label || ''),
          rows: [],
          planned: 0,
          got: 0,
        }
        map.set(id, group)
      }
      group.rows.push(row)
      group.planned += row.total || 0
      group.got += row.got || 0
    }
    return [...map.values()].sort((a, b) => {
      const ai = order.indexOf(a.id)
      const bi = order.indexOf(b.id)
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi)
    })
  })

  const modules = computed<CategoryModule[]>(() => [
    { key: DIST_MODULE_KEY, label: '来源分布', tabLabel: '来源分布', meta: '', rows: [] },
    ...groups.value.map((group) => ({
      key: group.id,
      label: group.label,
      tabLabel: group.label,
      meta: '',
      rows: [],
    })),
  ])

  const shownGroups = computed(() => groups.value.filter((group) => group.id === view.value))

  // 新一轮调研会重建分组：选中的维度不在了就退回第一个模块（来源分布）。
  watch(modules, (list) => {
    if (!list.some((module) => module.key === view.value)) {
      view.value = list[0]?.key || ''
    }
  })

  /**
   * 采集窗口顶部的来源分布：按 sources.index 的实际页面统计。
   * 站点超过 6 个时折叠成「其余 N 个站点」；维度只统计页数，不再区分来源构成。
   */
  const distribution = computed<CollectDistribution | null>(() => {
    const links = Object.values(evidenceLinks)
    if (!links.length) return null
    const total = links.length
    const dimCount = new Map<string, number>()
    const siteCount = new Map<string, number>()
    for (const link of links) {
      const dim = linkKind(link) || 'other'
      dimCount.set(dim, (dimCount.get(dim) || 0) + 1)
      const site = link.site || '未知站点'
      siteCount.set(site, (siteCount.get(site) || 0) + 1)
    }
    const toRow = (key: string, label: string, count: number): DistRow => ({
      key,
      label,
      count,
      pct: Math.round((count / total) * 100),
    })
    const dimRows = [...dimCount.entries()]
      .map(([id, count]) =>
        toRow(id, dimShort(id, dims.value.find((dim) => dim.id === id)?.label || '') || id, count),
      )
      .sort((a, b) => b.count - a.count)
    const sites = [...siteCount.entries()]
      .map(([name, count]) => toRow(name, name, count))
      .sort((a, b) => b.count - a.count)
    const rest = sites.slice(6)
    return {
      total,
      sites: sites.length,
      dims: dimRows,
      siteRows: sites.slice(0, 6),
      rest: rest.length
        ? toRow('rest', `其余 ${rest.length} 个站点`, rest.reduce((sum, row) => sum + row.count, 0))
        : null,
    }
  })

  const siteCount = computed(() =>
    groups.value.reduce((sum, group) => sum + group.rows.length, 0),
  )

  /** 采集卡：维度 / 站点 / 已采页数 / 带发布时间，全部来自采集事件。 */
  const summary = computed(() => {
    const view = emptySummary('metrics')
    const got = groups.value.reduce((sum, group) => sum + group.got, 0)
    const planned = groups.value.reduce((sum, group) => sum + group.planned, 0)
    view.meter = planned ? Math.round((got / Math.max(1, planned)) * 100) : null
    view.stats = [
      { label: '维度', value: `${planGroupCount() || dims.value.length} 个` },
      { label: '站点', value: `${siteCount.value} 个` },
      { label: '已采页数', value: `${got}/${planned || got}` },
      { label: '带时间', value: `${published.value} 个` },
    ]
    return view
  })

  const card = computed<CategoryCard>(() => ({
    key: 'collect',
    icon: 'layers',
    title: '采集页面',
    subtitle: `${windowText.value || '本轮时间窗口'} · ${siteCount.value} 个站点`,
    status: `${pages.value} 页`,
    note: '',
    summary: summary.value,
  }))

  const hasRows = computed(() => rows().length > 0)
  const emptyText = '等待采集页面 · 这里会按站点显示抓取进度'

  /**
   * 一条采集记录对应的页面：同维度同站点优先。
   * 真实站点一页都没采到时不拿别的站点顶替，避免「0 页已采」下面却列着一堆来源。
   * 只有内置来源这类维度级记录才退回该维度全部来源。
   */
  function pagesOf(row: PanelRow): EvidenceLink[] {
    const dim = row.group || ''
    const inDim = Object.values(evidenceLinks).filter((link) => linkKind(link) === dim)
    if (!row.rawSite) return inDim
    const sameSite = inDim.filter((link) => link.site === row.rawSite)
    if (sameSite.length) return sameSite
    return row.rawSite === '内置来源' ? inDim : []
  }

  function sourcesOf(row: PanelRow): EvidenceLink[] {
    return pagesOf(row).slice(0, 12)
  }

  function sourceCountOf(row: PanelRow): number {
    return pagesOf(row).length
  }

  /** 采集页数提示：解释「计划采集」里为什么有页没采到，并说明不是分页。 */
  function numTitle(row: PanelRow): string {
    const base = `${row.got || 0}/${row.total || 0} 页：该站点已采集页数 / 计划采集页数，不是分页`
    if (!row.skipped) return base
    const reasons = (row.skipReasons || []).join('、')
    return `${base}；${row.skipped} 页未采到${reasons ? `（${reasons}）` : ''}，这些页既抓不到正文也没有可用的搜索摘要`
  }

  function toggle(key: string) {
    open[key] = !open[key]
  }

  function setModuleKey(key: string) {
    view.value = key
  }

  function setDistView(value: DistView) {
    distView.value = value
  }

  function reset() {
    view.value = DIST_MODULE_KEY
    distView.value = 'site'
    Object.keys(open).forEach((key) => delete open[key])
  }

  function snapshot() {
    return {
      collectView: view.value,
      distView: distView.value,
      collectOpen: { ...open },
    }
  }

  function restore(run: CategoryRunSnapshot) {
    view.value = (typeof run.collectView === 'string' && run.collectView) || DIST_MODULE_KEY
    distView.value = run.distView === 'dim' ? 'dim' : 'site'
    Object.keys(open).forEach((key) => delete open[key])
    const savedOpen = run.collectOpen
    if (savedOpen && typeof savedOpen === 'object') {
      for (const [key, value] of Object.entries(savedOpen as Record<string, unknown>)) {
        if (typeof value === 'boolean') open[key] = value
      }
    }
  }

  return {
    view,
    groups,
    modules,
    shownGroups,
    distribution,
    distView,
    open,
    card,
    hasRows,
    emptyText,
    sourcesOf,
    sourceCountOf,
    numTitle,
    toggle,
    setModuleKey,
    setDistView,
    activeModuleKey: view,
    reset,
    snapshot,
    restore,
  }
}
