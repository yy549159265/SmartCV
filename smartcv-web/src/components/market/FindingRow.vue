<script setup lang="ts">
import type { EvidenceLink, PanelRow } from '@/types/market'
import SourceLinks from './SourceLinks.vue'

withDefaults(
  defineProps<{
    row: PanelRow
    index: number
    highlight?: boolean
    links?: EvidenceLink[]
    more?: number
  }>(),
  {
    highlight: false,
    links: () => [],
    more: 0,
  },
)
</script>

<template>
  <div
    class="row glass-item"
    :class="[
      `row-${row.kind}`,
      {
        qrow: row.kind === 'q',
        fact: row.kind === 'fact',
        brow: row.kind === 'bar',
        irow: row.kind === 'step',
        prow: row.kind === 'pair',
        drow: row.kind === 'divider',
        top: row.kind === 'bar' && row.top,
        syn: row.synthesis,
        hl: highlight,
      },
    ]"
  >
    <template v-if="row.kind === 'divider'">
      <span class="divider-label">{{ row.label }}</span>
      <span v-if="row.text" class="divider-note">{{ row.text }}</span>
    </template>

    <template v-else-if="row.kind === 'q'">
      <span class="idx">{{ row.idx }}</span>
      <span class="q">{{ row.q }}</span>
      <span class="site">{{ row.site }}</span>
    </template>

    <template v-else-if="row.kind === 'bar'">
      <div class="bar-main">
        <div class="bar-top">
          <span v-if="row.name" class="name">{{ row.name }}</span>
          <span v-if="row.years" class="years">{{ row.years }}</span>
          <span v-if="row.must" class="must">硬</span>
          <span v-if="row.text" class="bar-note">{{ row.text }}</span>
          <span class="num">{{ row.count }}/{{ row.total }}</span>
          <span v-if="row.trend === 'up' || row.trend === 'down'" class="trend" :class="row.trend">
            {{ row.trend === 'up' ? '↑' : '↓' }}
          </span>
          <SourceLinks :links="links" :more="more" />
        </div>
        <div class="track"><i :style="{ width: `${row.pct || 0}%` }"></i></div>
      </div>
    </template>

    <template v-else-if="row.kind === 'step'">
      <span
        class="step-rank"
        :class="`rank-${Math.min(index + 1, 4)}`"
        :title="`优先级 ${index + 1}`"
      >{{ index + 1 }}</span>
      <span v-if="row.desc" class="desc">{{ row.desc }}</span>
      <SourceLinks :links="links" :more="more" />
    </template>

    <template v-else-if="row.kind === 'pair'">
      <span :class="row.tag === 'hit' ? 'tag-hit' : row.tag === 'transfer' ? 'tag-transfer' : 'tag-gap'">
        {{ row.label }}
      </span>
      <span v-if="row.text" class="txt">{{ row.text }}</span>
      <SourceLinks :links="links" :more="more" />
    </template>

    <template v-else>
      <div class="fact-body">
        <div
          v-if="row.label || row.value || row.chips?.length || links.length"
          class="fact-top"
        >
          <span v-if="row.label" class="flabel" :class="`tone-${row.tone || 'default'}`">{{ row.label }}</span>
          <span v-if="row.value" class="fvalue" :class="row.trend">{{ row.value }}</span>
          <span v-for="(chip, chipIndex) in row.chips" :key="chipIndex" class="chip">{{ chip }}</span>
          <SourceLinks :links="links" :more="more" />
        </div>
        <div v-if="row.text" class="ftext">{{ row.text }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-2);
  transition:
    background 0.9s var(--ease),
    opacity 0.22s var(--ease);
  animation: row-in 0.3s var(--ease);
}
@keyframes row-in {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.row + .row {
  margin-top: 4px;
}
.row.hl {
  border-color: rgba(71, 83, 199, 0.24);
  background: rgba(236, 239, 251, 0.72);
}
.row .num {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  flex: none;
}
.brow {
  display: block;
}
.bar-main {
  min-width: 0;
}
.bar-top {
  display: flex;
  align-items: center;
  gap: 6px;
}
.brow .name {
  flex: none;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
}
.brow .years {
  flex: none;
  font-size: 11.5px;
  color: var(--text-3);
  white-space: nowrap;
}
.brow .must {
  flex: none;
  padding: 0 4px;
  border-radius: 3px;
  font-size: 11px;
  background: var(--warn-soft);
  color: var(--warn);
}
.brow .bar-note {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
  color: var(--text-3);
}
.brow .track {
  display: block;
  height: 4px;
  margin-top: 6px;
  border-radius: 2px;
  background: var(--surface);
  overflow: hidden;
}
.brow .track i {
  display: block;
  height: 100%;
  width: 0;
  border-radius: 2px;
  background: #8b93d8;
  transition: width 0.35s var(--ease);
}
.brow.top .track i {
  background: var(--primary);
}
.brow .trend {
  flex: none;
  font-size: 11.5px;
  color: var(--text-3);
  width: 12px;
  text-align: center;
}
.brow .trend.up {
  color: var(--success);
}
.brow .trend.down {
  color: var(--warn);
}
/* 优先行动：序号做成卡片左上角标，优先级越高角标越重，不再写「优先级 N」文字。 */
.irow {
  align-items: flex-start;
  padding-left: 30px;
}
.step-rank {
  position: absolute;
  top: 0;
  left: 0;
  box-sizing: border-box;
  min-width: 22px;
  height: 20px;
  padding: 0 5px;
  display: grid;
  place-items: center;
  border-top-left-radius: 8px;
  border-bottom-right-radius: 8px;
  background: var(--surface);
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.step-rank.rank-1 {
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}
.step-rank.rank-2 {
  background: var(--primary-soft);
  color: var(--primary);
}
.step-rank.rank-3 {
  background: var(--primary-faint);
  color: var(--primary);
}
.step-rank.rank-4 {
  background: transparent;
  border: 1px solid var(--border);
}
.irow .desc {
  flex: 1;
  min-width: 0;
  line-height: 1.6;
}
/* 对照行：来源小标和首行文字同一水平线，不跟着长文本垂直居中。 */
.prow {
  align-items: flex-start;
}
.prow .tag-hit,
.prow .tag-gap,
.prow .tag-transfer {
  flex: none;
  margin-top: 1px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11.5px;
}
.prow .tag-hit {
  background: var(--success-soft);
  color: var(--success);
}
.prow .tag-gap {
  background: var(--warn-soft);
  color: var(--warn);
}
.prow .tag-transfer {
  background: var(--primary-soft);
  color: var(--primary);
}
.prow .txt {
  flex: 1;
  min-width: 0;
  line-height: 1.6;
}
/* 分点事实：和简历画像的分点列表同一套圆点排版，不再逐条包一层玻璃卡片。 */
.fact {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 3px 2px;
  border-color: transparent;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
}
.row.fact:hover {
  border-color: transparent;
  background: transparent;
  box-shadow: none;
}
.fact::before {
  content: '';
  flex: none;
  width: 5px;
  height: 5px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--primary);
}
.row + .row.fact {
  margin-top: 5px;
}
.fact-body {
  flex: 1;
  min-width: 0;
}
.fact-body > .ftext:only-child {
  margin-top: 0;
}
.fact-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.flabel {
  flex: none;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 11.5px;
  line-height: 1.6;
  background: var(--surface);
  color: var(--text-2);
  white-space: nowrap;
}
.flabel.tone-role,
.flabel.tone-company,
.flabel.tone-skill {
  background: var(--primary-soft);
  color: var(--primary);
}
.flabel.tone-salary {
  background: var(--success-soft);
  color: var(--success);
}
.flabel.tone-requirement {
  background: var(--warn-soft);
  color: var(--warn);
}
.fvalue {
  flex: none;
  color: var(--text-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.fvalue.up {
  color: var(--success);
}
.fvalue.down {
  color: var(--warn);
}
.fvalue.flat {
  color: var(--text-3);
}
.ftext {
  margin-top: 3px;
  overflow-wrap: anywhere;
}
.chip {
  flex: none;
  max-width: 132px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 11.5px;
  background: var(--surface);
  color: var(--text-2);
}
.drow {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 10px;
  padding: 8px 6px 4px;
  border-top: 1px dashed var(--border);
}
.drow .divider-label {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-2);
}
.drow .divider-note {
  font-size: 11px;
  color: var(--text-3);
}
/* 旧动态维度里的检索行：和规划页签保持同一套小号排版。 */
.qrow {
  align-items: baseline;
  padding: 5px 8px;
  font-size: 12.5px;
}
.qrow .idx {
  flex: none;
  width: 16px;
  font-size: 11.5px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.qrow .q {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qrow .site {
  flex: none;
  font-size: 11.5px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-3);
}
</style>

<style scoped src="./pane-shared.css"></style>
