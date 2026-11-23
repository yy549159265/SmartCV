<script setup lang="ts">
import FindingsPane from '@/components/market/FindingsPane.vue'
import JobsPane from '@/components/market/JobsPane.vue'
import type { EvidenceLink, PaneModule, PanelRow, RowGroup } from '@/types/market'
import CategoryPanel from './CategoryPanel.vue'
import type { CategoryCard, CategoryModule } from './types'

defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
  activeModule: PaneModule | null
  moduleRows: PanelRow[]
  rowGroups: RowGroup[]
  jobSkillRows: PanelRow[]
  jobMustHaveCount: number
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
      <JobsPane
        v-if="hasRows && activeModule?.data"
        :module-key="activeModule.key"
        :data="activeModule.data"
        :links-of="linksOf"
        :more-links="moreLinks"
      />
      <FindingsPane
        v-else
        tab-key="jobs"
        :has-rows="hasRows"
        :active-module="activeModule"
        :module-rows="moduleRows"
        :row-groups="rowGroups"
        :job-skill-rows="jobSkillRows"
        :job-must-have-count="jobMustHaveCount"
        :highlight-key="highlightKey"
        :empty-text="emptyText"
        :links-of="linksOf"
        :more-links="moreLinks"
      />
    </template>
  </CategoryPanel>
</template>
