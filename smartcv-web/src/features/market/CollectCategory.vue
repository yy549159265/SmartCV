<script setup lang="ts">
import CollectPane from '@/components/market/CollectPane.vue'
import type { CollectDistribution, CollectGroup, EvidenceLink, PanelRow } from '@/types/market'
import CategoryPanel from './CategoryPanel.vue'
import type { CategoryCard, CategoryModule } from './types'

defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
  groups: CollectGroup[]
  distribution: CollectDistribution | null
  distKey: string
  distView: 'site' | 'dim'
  open: Record<string, boolean>
  highlightKey: string
  hasRows: boolean
  emptyText: string
  sourcesOf: (row: PanelRow) => EvidenceLink[]
  sourceCountOf: (row: PanelRow) => number
  numTitle: (row: PanelRow) => string
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'toggle', key: string): void
  (e: 'update:distView', value: 'site' | 'dim'): void
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
      <CollectPane
        :groups="groups"
        :distribution="distribution"
        :view="activeModuleKey"
        :dist-key="distKey"
        :dist-view="distView"
        :open="open"
        :highlight-key="highlightKey"
        :has-rows="hasRows"
        :empty-text="emptyText"
        :sources-of="sourcesOf"
        :source-count-of="sourceCountOf"
        :num-title="numTitle"
        @toggle="emit('toggle', $event)"
        @update:dist-view="emit('update:distView', $event)"
      />
    </template>
  </CategoryPanel>
</template>
