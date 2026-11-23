<script setup lang="ts">
/** 跨源分析：招聘信息、动态方面、技术趋势共用同一套卡片排版。 */
import type { EvidenceLink, PanelRow } from '@/types/market'
import SourceLinks from './SourceLinks.vue'

defineProps<{
  rows: PanelRow[]
  highlightKey?: string
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()
</script>

<template>
  <div class="syn-block">
    <p class="syn-lead">与其它调研维度交叉验证得出的结论</p>
    <div class="syn-list">
      <article
        v-for="row in rows"
        :key="row.key"
        class="syn-card glass-item"
        :class="{ hl: highlightKey === row.key }"
      >
        <div class="syn-card-top">
          <span class="syn-card-name">{{ row.label || row.name || '跨源结论' }}</span>
          <span v-if="row.value" class="syn-badge">{{ row.value }}</span>
          <SourceLinks :links="linksOf(row)" :more="moreLinks(row)" />
        </div>
        <p v-if="row.text" class="syn-text">{{ row.text }}</p>
        <div v-if="row.chips?.length" class="syn-chips">
          <span v-for="(chip, index) in row.chips" :key="index" class="syn-chip">{{ chip }}</span>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped src="./pane-shared.css"></style>
