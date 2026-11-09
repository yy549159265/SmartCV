<script setup lang="ts">
import { computed } from 'vue'
import PreviewLayoutWindow from './PreviewLayoutWindow.vue'
import DiffActionButton from './DiffActionButton.vue'
import { effectiveSectionStyle } from '@/utils/style'
import { computeTableCols } from '@/utils/layout'
import { diffAttr as resolveDiffAttr, type DiffControls, type DiffMarks } from '@/utils/resumeDiff'
import type { Section } from '@/types'

const props = withDefaults(
  defineProps<{
    section: Section
    rowFrom?: number
    rowTo?: number
    showTitle?: boolean
    topPad?: boolean
    bottomPad?: boolean
    spaceBefore?: number
    marks?: DiffMarks
    controls?: DiffControls
    unitDiffs?: Record<string, Record<number, string>>
  }>(),
  {
    showTitle: true,
    topPad: true,
    bottomPad: true,
  },
)

const tableCols = computed(() => computeTableCols(props.section.rows))

const visibleRows = computed(() => {
  const all = props.section.rows
  if (props.rowFrom === undefined) return all
  const from = props.rowFrom
  const to = props.rowTo ?? all.length - 1
  return all.slice(from, to + 1)
})

const eff = computed(() => effectiveSectionStyle(props.section))

const titleStyle = computed(() => ({
  fontSize: `${eff.value.titleSize}px`,
  color: eff.value.color,
}))

const sectionStyle = computed(() => ({
  marginTop: `${props.spaceBefore !== undefined ? props.spaceBefore : eff.value.spaceBefore}px`,
}))

const padStyle = computed(() => ({
  paddingTop: props.topPad === false ? '0px' : '2px',
  paddingBottom: props.bottomPad === false ? '0px' : '10px',
}))

const sectionView = computed(() => props.controls?.sections[props.section.id])

const sectionAttr = computed(() =>
  resolveDiffAttr(props.marks?.sections[props.section.id], sectionView.value),
)
</script>

<template>
  <section class="preview-section" :style="[sectionStyle, padStyle]">
    <div
      v-if="showTitle !== false"
      class="preview-section-title"
      :class="{ 'has-underline': eff.titleUnderline }"
      :data-diff="sectionAttr"
      :data-diff-key="sectionView ? `section:${section.id}` : undefined"
      :style="titleStyle"
    >
      <span class="preview-title-row">
        <span v-if="section.icon" class="preview-title-icon" v-html="section.icon"></span>
        <span class="preview-title-text">{{ section.title }}</span>
        <DiffActionButton v-if="sectionView" :view="sectionView" />
      </span>
    </div>
    <div class="preview-rows">
      <PreviewLayoutWindow
        v-for="row in visibleRows"
        :key="row.id"
        :section="section"
        :row="row"
        :table-cols="tableCols"
        :marks="marks"
        :controls="controls"
        :unit-diffs="unitDiffs"
      />
    </div>
  </section>
</template>

<style scoped>
.preview-section {
}

.preview-section-title {
  margin: 0 0 6px;
  font-weight: 600;
}
.preview-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.preview-title-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1em;
  height: 1em;
  line-height: 1;
}
.preview-title-icon :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}
.preview-title-text {
  flex: 0 1 auto;
  min-width: 0;
  overflow-wrap: anywhere;
}
.preview-section-title.has-underline {
  padding-bottom: 2px;
  border-bottom: 2px solid currentColor;
}

.preview-rows {
  display: flex;
  flex-direction: column;
  gap: 0;
}
</style>
