/** 规划检索：检索清单按维度分块，汇总卡直接展示规划步骤。 */

import { computed, ref, type Ref } from 'vue'
import type { DimInfo, PlanGroup } from '@/types/market'
import { dimShort } from './labels'
import {
  emptySummary,
  type CategoryCard,
  type CategoryModule,
  type CategoryRunSnapshot,
} from './types'

export interface PlanQuerySource {
  q: string
  kind: string
  label: string
  source: string
}

export interface PlanCategoryOptions {
  planDoc: Ref<{ key: string; text: string }[]>
  planQueries: Ref<PlanQuerySource[]>
  planRunning: Ref<boolean>
  dims: Ref<DimInfo[]>
  title: Ref<string>
}

/** 步骤展示顺序：先说明是否走简历分支，再给报告汇总口径。 */
const PLAN_STEP_ORDER = ['采集', '抽取', '分支', '汇总']

function planStepRank(key: string): number {
  const index = PLAN_STEP_ORDER.indexOf(key)
  return index < 0 ? PLAN_STEP_ORDER.length : index
}

export function usePlanCategory(options: PlanCategoryOptions) {
  const { planDoc, planQueries, planRunning, dims, title } = options

  const moduleKey = ref('')

  /** 按 kind 汇总成组，清单就按维度分块展示；顺序沿用后端下发顺序。 */
  const groups = computed<PlanGroup[]>(() => {
    const order: string[] = []
    const map = new Map<string, PlanGroup>()
    planQueries.value.forEach((query, index) => {
      const kind = query.kind || 'other'
      let group = map.get(kind)
      if (!group) {
        const label = dimShort(
          kind,
          query.label || dims.value.find((item) => item.id === kind)?.label || '',
        )
        group = { kind, label, source: query.source, queries: [] }
        map.set(kind, group)
        order.push(kind)
      }
      group.queries.push({ q: query.q, index: index + 1 })
    })
    return order.map((kind) => map.get(kind)!)
  })

  /** 当前选中的检索维度；规划还没出结果时为空。 */
  const shownGroup = computed(
    () => groups.value.find((group) => group.kind === moduleKey.value) || groups.value[0] || null,
  )

  const modules = computed<CategoryModule[]>(() =>
    groups.value.map((group) => ({
      key: group.kind,
      label: group.label,
      tabLabel: group.label,
      meta: '',
      rows: [],
    })),
  )

  const activeModuleKey = computed(() => shownGroup.value?.kind || '')

  /** 计划卡：把四个步骤按展示顺序放进卡片，卡片本身就是计划摘要。 */
  const summary = computed(() => {
    const view = emptySummary('steps')
    view.steps = planDoc.value.length
      ? [...planDoc.value]
          .sort((a, b) => planStepRank(a.key) - planStepRank(b.key))
          .map((step) => ({ key: step.key, text: step.text }))
      : [{ key: '等待', text: '规划 agent 完成后，这里会显示采集 / 抽取 / 分支 / 汇总四个步骤。' }]
    return view
  })

  const card = computed<CategoryCard>(() => ({
    key: 'plan',
    icon: 'route',
    title: '规划检索',
    subtitle: title.value,
    status: `${planDoc.value.length || 4} 个步骤`,
    note: '',
    summary: summary.value,
  }))

  function setModuleKey(key: string) {
    moduleKey.value = key
  }

  function reset() {
    moduleKey.value = ''
  }

  function snapshot() {
    return { planView: moduleKey.value }
  }

  function restore(run: CategoryRunSnapshot) {
    const saved = typeof run.planView === 'string' ? run.planView : run.paneModuleState?.plan
    moduleKey.value = typeof saved === 'string' ? saved : ''
  }

  return {
    moduleKey,
    groups,
    shownGroup,
    modules,
    activeModuleKey,
    planRunning,
    setModuleKey,
    card,
    reset,
    snapshot,
    restore,
  }
}
