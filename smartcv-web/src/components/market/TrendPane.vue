<script setup lang="ts">
import type {
  EvidenceLink,
  PanelRow,
  RowGroup,
  TrendAnalysis,
  TrendBucket,
  TrendReleaseGroup,
} from '@/types/market'
import FindingRow from './FindingRow.vue'
import SourceLinks from './SourceLinks.vue'
import SynthesisPane from './SynthesisPane.vue'

defineProps<{
  view: string
  timeline: TrendBucket[]
  timelineDated: boolean
  analysis: TrendAnalysis
  extraGroups: RowGroup[]
  extraRows: PanelRow[]
  releaseGroups: TrendReleaseGroup[]
  releaseRows: PanelRow[]
  synthesisRows: PanelRow[]
  highlightKey: string
  hasRows: boolean
  emptyText: string
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()
</script>

<template>
  <div v-if="!hasRows" class="pane-empty">{{ emptyText }}</div>
  <div v-else class="trend-card">
    <Transition name="mod-swap" mode="out-in">
      <section v-if="view === 'fish'" key="fish" class="trend-panel fish-panel glass-surface">
        <div class="module-head">
          <span class="module-sub">{{ timeline.length }} 个时间点</span>
        </div>
        <div class="fishbone">
          <div
            v-for="bucket in timeline"
            :key="bucket.key"
            class="fish-step"
            :class="{ dated: bucket.dated }"
          >
            <div class="fish-time">
              <span class="fish-month">{{ bucket.label }}</span>
              <span class="fish-sub">{{ bucket.sub }}</span>
            </div>
            <div class="fish-skills">
              <span
                v-for="skill in bucket.skills.slice(0, 6)"
                :key="`${bucket.key}-${skill.key}`"
                class="fish-skill"
                :class="skill.direction"
                :title="`${skill.name} · ${bucket.label} · ${skill.count} 条证据`"
              >
                <span class="fish-name">{{ skill.name }}</span>
                <span class="fish-count">{{ skill.count }}</span>
              </span>
              <span v-if="bucket.skills.length > 6" class="fish-more">
                +{{ bucket.skills.length - 6 }}
              </span>
            </div>
          </div>
        </div>
        <p class="module-note">
          {{ timelineDated
            ? '计数 = 该技能在该月证据页中的出现次数；越靠下时间越新。'
            : '来源没有可解析的发布时间，暂按本轮样本聚合。' }}
        </p>
      </section>

      <section v-else-if="view === 'focus'" key="focus" class="trend-panel focus-panel glass-surface">
        <div class="module-head">
          <span class="module-sub">
            {{ analysis.dated ? '最近两个时间点高频' : '本轮样本高频' }} · {{ analysis.focus.length }} 项
          </span>
        </div>
        <ul class="point-list">
          <li v-for="skill in analysis.focus" :key="skill.key">
            <span class="point-mark" :class="skill.direction"></span>
            <div class="point-body">
              <div class="focus-top">
                <span class="focus-name">{{ skill.name }}</span>
                <span class="dir-badge" :class="skill.direction">{{ skill.directionLabel }}</span>
                <span class="focus-right">
                  <span class="focus-count">
                    {{ analysis.dated ? `后段 ${skill.recent} 次` : `${skill.evidence.length} 条证据` }}
                  </span>
                  <SourceLinks :links="linksOf(skill)" :more="moreLinks(skill)" />
                </span>
              </div>
              <p v-if="skill.note" class="focus-note">{{ skill.note }}</p>
            </div>
          </li>
        </ul>
      </section>

      <section v-else-if="view === 'changes'" key="changes" class="trend-panel changes-panel glass-surface">
        <div class="module-head">
          <span class="module-sub">{{ analysis.up }} 升 / {{ analysis.down }} 降</span>
          <span class="change-legend" title="箭头说明">
            <span class="up">↑ 上升</span>
            <span class="flat">→ 平稳</span>
            <span class="down">↓ 下降</span>
          </span>
        </div>
        <ul class="point-list">
          <li
            v-for="skill in analysis.changes"
            :key="`change-${skill.key}`"
            class="change-item"
          >
            <span class="change-dir" :class="skill.direction">
              {{ skill.direction === 'up' ? '↑' : skill.direction === 'down' ? '↓' : '→' }}
            </span>
            <div class="change-body">
              <div class="change-top">
                <span class="change-name">{{ skill.name }}</span>
                <span class="change-note">{{ skill.note || skill.directionLabel }}</span>
                <SourceLinks :links="linksOf(skill)" :more="moreLinks(skill)" />
              </div>
            </div>
          </li>
        </ul>
      </section>

      <section v-else-if="view === 'extra'" key="extra" class="trend-panel extra-panel glass-surface">
        <div class="module-head">
          <span class="module-sub">{{ extraRows.length }} 条结论</span>
        </div>
        <div v-for="group in extraGroups" :key="group.key" class="extra-block">
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
      </section>

      <section v-else-if="view === 'release'" key="release" class="trend-panel release-panel glass-surface">
        <div class="module-head">
          <span class="module-sub">{{ releaseGroups.length }} 项技术 · {{ releaseRows.length }} 条版本更新</span>
        </div>
        <div v-for="group in releaseGroups" :key="group.key" class="release-block">
          <div class="release-tech">{{ group.tech }}</div>
          <ul class="point-list">
            <li v-for="row in group.rows" :key="row.key">
              <span class="point-mark"></span>
              <div class="point-body release-body">
                <span class="point-text">{{ row.text }}</span>
                <SourceLinks :links="linksOf(row)" :more="moreLinks(row)" />
              </div>
            </li>
          </ul>
        </div>
      </section>

      <section v-else key="syn" class="trend-panel pane-module glass-surface">
        <SynthesisPane
          :rows="synthesisRows"
          :highlight-key="highlightKey"
          :links-of="linksOf"
          :more-links="moreLinks"
        />
      </section>
    </Transition>
  </div>
</template>

<style scoped src="./trend.css"></style>
<style scoped src="./pane-shared.css"></style>
