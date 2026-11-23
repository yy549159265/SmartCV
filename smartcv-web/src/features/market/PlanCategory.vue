<script setup lang="ts">
import PlanPane from '@/components/market/PlanPane.vue'
import type { PlanGroup } from '@/types/market'
import CategoryPanel from './CategoryPanel.vue'
import type { CategoryCard, CategoryModule } from './types'

defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
  group: PlanGroup | null
  running: boolean
  highlightKey: string
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
      <PlanPane :group="group" :running="running" :highlight-key="highlightKey" />
    </template>
  </CategoryPanel>
</template>
