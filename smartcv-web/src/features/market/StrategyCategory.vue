<script setup lang="ts">
import StrategyPane from '@/components/market/StrategyPane.vue'
import type { EvidenceLink, PaneModule, PanelRow } from '@/types/market'
import CategoryPanel from './CategoryPanel.vue'
import type { CategoryCard, CategoryModule } from './types'

defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
  activeModule: PaneModule | null
  moduleRows: PanelRow[]
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
      <StrategyPane
        :has-rows="hasRows"
        :empty-text="emptyText"
        :active-module="activeModule"
        :module-rows="moduleRows"
        :highlight-key="highlightKey"
        :links-of="linksOf"
        :more-links="moreLinks"
      />
    </template>
  </CategoryPanel>
</template>
