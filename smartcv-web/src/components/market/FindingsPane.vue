<script setup lang="ts">
import type { EvidenceLink, PaneModule, PanelRow, RowGroup } from '@/types/market'
import FindingRow from './FindingRow.vue'
import SourceLinks from './SourceLinks.vue'
import SynthesisPane from './SynthesisPane.vue'

defineProps<{
  tabKey: string
  hasRows: boolean
  activeModule: PaneModule | null
  moduleRows: PanelRow[]
  rowGroups: RowGroup[]
  jobSkillRows: PanelRow[]
  jobMustHaveCount: number
  highlightKey: string
  emptyText: string
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()
</script>

<template>
  <div v-if="!hasRows" class="pane-empty">{{ emptyText }}</div>
  <template v-else>
    <Transition name="mod-swap" mode="out-in">
      <div :key="activeModule?.key || 'empty'" class="rows pane-module glass-surface">
        <template v-if="activeModule?.key === 'syn'">
          <SynthesisPane
            :rows="moduleRows"
            :highlight-key="highlightKey"
            :links-of="linksOf"
            :more-links="moreLinks"
          />
        </template>
        <template v-else>
          <div
            v-if="tabKey === 'jobs' && activeModule?.key === 'overview'"
            class="job-overview"
          >
            <div
              v-for="row in moduleRows"
              :key="row.key"
              class="job-fact"
              :class="`tone-${row.tone || 'default'}`"
            >
              <div class="job-fact-head">
                <span class="job-fact-label">{{ row.label }}</span>
                <SourceLinks :links="linksOf(row)" :more="moreLinks(row)" />
              </div>
              <div v-if="row.value || row.text" class="job-fact-line">
                <span v-if="row.value" class="job-fact-value">{{ row.value }}</span>
                <span v-if="row.text" class="job-fact-note">{{ row.text }}</span>
              </div>
              <div v-if="row.chips?.length" class="job-fact-chips">
                <span v-for="(chip, chipIndex) in row.chips" :key="chipIndex" class="job-chip">{{ chip }}</span>
              </div>
            </div>
          </div>
          <div
            v-else-if="tabKey === 'jobs' && activeModule?.key === 'skills'"
            class="job-skills"
          >
            <div class="job-skills-head">
              <span>{{ jobSkillRows.length }} 项技能</span>
              <span v-if="jobMustHaveCount" class="job-skills-must">硬性 {{ jobMustHaveCount }} 项</span>
            </div>
            <div
              v-for="row in jobSkillRows"
              :key="row.key"
              class="job-skill"
              :class="{
                top: row.top,
                hl: highlightKey === row.key,
              }"
            >
              <div class="job-skill-top">
                <span class="job-skill-name" :title="row.name || row.label">{{ row.name || row.label }}</span>
                <span v-if="row.must" class="job-skill-must">硬性</span>
                <span v-if="row.years" class="job-skill-years">{{ row.years }}</span>
                <SourceLinks :links="linksOf(row)" :more="moreLinks(row)" />
              </div>
              <div class="job-skill-meter">
                <span class="job-skill-track"><i :style="{ width: `${row.pct || 0}%` }"></i></span>
                <span class="job-skill-num">{{ row.count }}/{{ row.total }}</span>
              </div>
              <div v-if="row.text" class="job-skill-note">{{ row.text }}</div>
            </div>
          </div>
          <template v-else>
            <template v-for="group in rowGroups" :key="group.key">
              <div :class="{ 'extra-block': group.block }">
                <FindingRow
                  v-for="(row, rowIndex) in group.rows"
                  :key="row.key"
                  :row="row"
                  :index="rowIndex"
                  :highlight="highlightKey === row.key"
                  :links="linksOf(row)"
                  :more="moreLinks(row)"
                />
              </div>
            </template>
            <div v-if="!moduleRows.length" class="pane-empty">
              该模块暂无内容，切换上方卡片查看其他结论。
            </div>
          </template>
        </template>
      </div>
    </Transition>
  </template>
</template>

<style scoped src="./findings.css"></style>
<style scoped src="./pane-shared.css"></style>
