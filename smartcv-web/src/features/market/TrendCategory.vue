<script setup lang="ts">
import TrendMatrixPane from '@/components/market/TrendMatrixPane.vue'
import TrendPane from '@/components/market/TrendPane.vue'
import type {
  EvidenceLink,
  PaneModule,
  PanelRow,
  RowGroup,
  TrendAnalysis,
  TrendBucket,
  TrendReleaseGroup,
} from '@/types/market'
import CategoryPanel from './CategoryPanel.vue'
import type { CategoryCard, CategoryModule } from './types'

defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
  activeModule: PaneModule | null
  view: string
  timeline: TrendBucket[]
  timelineDated: boolean
  analysis: TrendAnalysis
  extraGroups: RowGroup[]
  extraRows: PanelRow[]
  releaseGroups: TrendReleaseGroup[]
  releaseRows: PanelRow[]
  synthesisRows: PanelRow[]
  hasRows: boolean
  emptyText: string
  highlightKey: string
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
}>()
</script>

<template>
  <CategoryPanel
    :card="card"
    :modules="modules"
    :active-module-key="activeModuleKey"
    @select="emit('select', $event)"
  >
    <template #pane>
      <TrendMatrixPane
        v-if="hasRows && activeModule && (activeModule.data || activeModule.key === 'syn')"
        :module-key="activeModule.key"
        :data="activeModule.data"
        :rows="activeModule.rows"
        :links-of="linksOf"
        :more-links="moreLinks"
      />
      <TrendPane
        v-else
        :view="view"
        :timeline="timeline"
        :timeline-dated="timelineDated"
        :analysis="analysis"
        :extra-groups="extraGroups"
        :extra-rows="extraRows"
        :release-groups="releaseGroups"
        :release-rows="releaseRows"
        :synthesis-rows="synthesisRows"
        :highlight-key="highlightKey"
        :has-rows="hasRows"
        :empty-text="emptyText"
        :links-of="linksOf"
        :more-links="moreLinks"
      />
    </template>
  </CategoryPanel>
</template>
