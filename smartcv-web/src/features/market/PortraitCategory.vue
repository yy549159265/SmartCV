<script setup lang="ts">
import PortraitPane from '@/components/market/PortraitPane.vue'
import type { PortraitSection } from '@/types/market'
import CategoryPanel from './CategoryPanel.vue'
import type { CategoryCard, CategoryModule, GapView, ProjectView, SkillView } from './types'

defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
  sections: PortraitSection[]
  hasRows: boolean
  emptyText: string
  skillView: SkillView
  projectView: ProjectView
  gapView: GapView
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'skill-view', value: SkillView): void
  (e: 'project-view', value: ProjectView): void
  (e: 'gap-view', value: GapView): void
}>()
</script>

<template>
  <CategoryPanel
    :card="card"
    :modules="modules"
    :active-module-key="activeModuleKey"
    @select="emit('select', $event)"
  >
    <template #summary>
      <p class="summary-portrait-text">
        <span class="summary-portrait-label">个人简介：</span>{{ card.summary.text }}
      </p>
    </template>

    <template #pane>
      <PortraitPane
        :sections="sections"
        :has-rows="hasRows"
        :empty-text="emptyText"
        :skill-view="skillView"
        :project-view="projectView"
        :gap-view="gapView"
        @skill-view="emit('skill-view', $event)"
        @project-view="emit('project-view', $event)"
        @gap-view="emit('gap-view', $event)"
      />
    </template>
  </CategoryPanel>
</template>

<style scoped>
/* 画像是唯一使用自述形态的类别，样式跟汇总卡一起放在这里维护。 */
.summary-portrait-text {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
}
.summary-portrait-label {
  margin-right: 2px;
  font-weight: 600;
  color: var(--text-3);
}
</style>
