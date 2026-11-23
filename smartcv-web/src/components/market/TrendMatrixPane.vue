<script setup lang="ts">
/** 技术趋势的结构化五块：领域分布 / 高频技术鱼骨 / 技术生态 / 趋势与问题 / 应用与场景。 */
import { computed, ref, watch } from 'vue'
import IconGlyph from '@/components/IconGlyph.vue'
import type { EvidenceLink, PanelRow } from '@/types/market'
import {
  SCENARIO_TREND_LABEL,
  TREND_TYPE_LABEL,
  readCategoryDistribution,
  readFrameworkEcosystem,
  readTechnologyApplications,
  readTechnologyFrequency,
  readTechnologyTrends,
  trendBarWidth,
  trendMonthLabel,
  trendPercentText,
  trendSparkHeight,
} from '@/features/market/trend'
import SourceLinks from './SourceLinks.vue'
import SynthesisPane from './SynthesisPane.vue'

const props = defineProps<{
  moduleKey: string
  data?: Record<string, unknown>
  rows?: PanelRow[]
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()

const catData = computed(() => readCategoryDistribution(props.data))
const freqData = computed(() => readTechnologyFrequency(props.data))
const ecoData = computed(() => readFrameworkEcosystem(props.data))
const trendData = computed(() => readTechnologyTrends(props.data))
const appData = computed(() => readTechnologyApplications(props.data))
const synRows = computed(() => props.rows || [])

const trendMode = ref<'trends' | 'problems'>('trends')
const appMode = ref<'ranking' | 'trends'>('ranking')

watch(
  () => props.moduleKey,
  () => {
    trendMode.value = 'trends'
    appMode.value = 'ranking'
  },
)

const showTrendToggle = computed(
  () => Boolean(trendData.value?.trends.length) && Boolean(trendData.value?.problems.length),
)
const showAppToggle = computed(
  () =>
    Boolean(appData.value?.scenario_ranking.items.length) &&
    Boolean(appData.value?.scenario_trends.items.length),
)

/** 只有一侧有数据时自动落到有内容的一侧，避免切到空面板。 */
const activeTrendMode = computed<'trends' | 'problems'>(() => {
  if (trendMode.value === 'trends' && !trendData.value?.trends.length) return 'problems'
  if (trendMode.value === 'problems' && !trendData.value?.problems.length) return 'trends'
  return trendMode.value
})

const activeAppMode = computed<'ranking' | 'trends'>(() => {
  if (appMode.value === 'ranking' && !appData.value?.scenario_ranking.items.length) return 'trends'
  if (appMode.value === 'trends' && !appData.value?.scenario_trends.items.length) return 'ranking'
  return appMode.value
})

const fishMax = computed(() => {
  let max = 1
  for (const branch of freqData.value?.fishbone.branches || []) {
    for (const tech of branch.technologies) {
      for (const count of tech.monthly_counts) max = Math.max(max, count)
    }
  }
  return max
})

const isEmpty = computed(() => {
  switch (props.moduleKey) {
    case 'category':
      return !catData.value?.items.length
    case 'frequency':
      return !freqData.value?.fishbone.branches.some((branch) => branch.technologies.length)
    case 'framework':
      return !ecoData.value?.items.length
    case 'trends':
      return !trendData.value?.trends.length && !trendData.value?.problems.length
    case 'applications':
      return (
        !appData.value?.scenario_ranking.items.length &&
        !appData.value?.scenario_trends.items.length
      )
    case 'syn':
      return !synRows.value.length
    default:
      return true
  }
})

function links(item: { evidence_ids?: string[] }): EvidenceLink[] {
  return props.linksOf({ evidence: item.evidence_ids || [] })
}

function more(item: { evidence_ids?: string[] }): number {
  return props.moreLinks({ evidence: item.evidence_ids || [] })
}

function sparkMax(counts: number[]): number {
  return Math.max(1, ...counts)
}
</script>

<template>
  <Transition name="mod-swap" mode="out-in">
    <div :key="moduleKey" class="trend-matrix pane-module glass-surface">
      <div v-if="isEmpty" class="pane-empty">该模块暂无内容，切换上方卡片查看其他结论。</div>

      <template v-else-if="moduleKey === 'category' && catData">
        <p v-if="catData.summary" class="tm-lead">{{ catData.summary }}</p>
        <section class="tm-section">
          <div v-for="item in catData.items" :key="item.name" class="tm-stat">
            <div class="tm-stat-top">
              <span class="tm-stat-name">{{ item.name }}</span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <div class="tm-meter">
              <span class="tm-track"><i :style="{ width: trendBarWidth(item.percentage) }"></i></span>
              <span class="tm-num">{{ trendPercentText(item.percentage) }}</span>
            </div>
            <div class="tm-meta-line">
              <span>{{ item.technology_count }} 项技术</span>
              <span>{{ item.mention_count }} 次提及</span>
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="moduleKey === 'frequency' && freqData">
        <p v-if="freqData.summary" class="tm-lead">{{ freqData.summary }}</p>

        <div class="tm-fish">
          <div class="tm-fish-head">
            <span class="tm-fish-icon"><IconGlyph name="shapes" :size="14" /></span>
            <span class="tm-fish-center">{{ freqData.fishbone.center }}</span>
            <span v-if="freqData.time_range" class="tm-fish-range">{{ freqData.time_range }}</span>
          </div>

          <div v-if="freqData.months.length" class="tm-axis">
            <span>{{ trendMonthLabel(freqData.months[0]) }}</span>
            <span>月度提及 · 共 {{ freqData.months.length }} 个月</span>
            <span>{{ trendMonthLabel(freqData.months[freqData.months.length - 1]) }}</span>
          </div>

          <div class="tm-branches">
            <section
              v-for="branch in freqData.fishbone.branches"
              :key="branch.category"
              class="tm-branch"
            >
              <header class="tm-branch-head">
                <span class="tm-branch-dot"></span>
                <span class="tm-branch-name">{{ branch.category }}</span>
                <span class="tm-branch-meta">{{ branch.technologies.length }} 项</span>
              </header>

              <div
                v-for="tech in branch.technologies"
                :key="tech.name"
                class="tm-tech glass-item"
              >
                <div class="tm-tech-top">
                  <span class="tm-tech-name">{{ tech.name }}</span>
                  <span class="tm-tech-num">{{ tech.total_count }} 次</span>
                  <SourceLinks :links="links(tech)" :more="more(tech)" />
                </div>
                <div class="tm-meter">
                  <span class="tm-track">
                    <i :style="{ width: trendBarWidth(tech.percentage) }"></i>
                  </span>
                  <span class="tm-num">{{ trendPercentText(tech.percentage) }}</span>
                </div>
                <div v-if="tech.monthly_counts.length" class="tm-spark">
                  <span
                    v-for="(count, index) in tech.monthly_counts"
                    :key="index"
                    class="tm-bar"
                    :title="`${freqData.months[index] || '对应月份'}：${count} 次提及`"
                  >
                    <i :style="{ height: trendSparkHeight(count, fishMax) }"></i>
                  </span>
                </div>
                <p v-if="tech.evidence" class="tm-note">{{ tech.evidence }}</p>
              </div>
            </section>
          </div>
        </div>
      </template>

      <template v-else-if="moduleKey === 'framework' && ecoData">
        <p v-if="ecoData.summary" class="tm-lead">{{ ecoData.summary }}</p>
        <section class="tm-section">
          <article v-for="item in ecoData.items" :key="item.name" class="tm-card glass-item">
            <div class="tm-card-top">
              <span class="tm-card-name">{{ item.name }}</span>
              <span v-if="item.type" class="tm-badge">{{ item.type }}</span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <div v-if="item.category" class="tm-meta-line">
              <span>{{ item.category }}</span>
            </div>
            <p v-if="item.description" class="tm-desc">{{ item.description }}</p>
            <div v-if="item.related_technologies.length" class="tm-chips">
              <span v-for="tech in item.related_technologies" :key="tech" class="tm-chip">
                {{ tech }}
              </span>
            </div>
            <p v-if="item.evidence" class="tm-note">{{ item.evidence }}</p>
          </article>
        </section>
      </template>

      <template v-else-if="moduleKey === 'trends' && trendData">
        <div v-if="showTrendToggle" class="tm-toolbar">
          <div class="tm-toggle" role="group" aria-label="趋势与问题切换">
            <button
              type="button"
              class="tm-toggle-btn"
              :class="{ active: activeTrendMode === 'trends' }"
              :aria-pressed="activeTrendMode === 'trends'"
              @click="trendMode = 'trends'"
            >
              <IconGlyph name="git-branch" :size="13" />
              <span>趋势</span>
            </button>
            <button
              type="button"
              class="tm-toggle-btn"
              :class="{ active: activeTrendMode === 'problems' }"
              :aria-pressed="activeTrendMode === 'problems'"
              @click="trendMode = 'problems'"
            >
              <IconGlyph name="shield-check" :size="13" />
              <span>问题</span>
            </button>
          </div>
        </div>

        <p v-if="trendData.summary" class="tm-lead">{{ trendData.summary }}</p>

        <section v-if="activeTrendMode === 'trends' && trendData.trends.length" class="tm-section">
          <article
            v-for="item in trendData.trends"
            :key="item.name"
            class="tm-card glass-item"
          >
            <div class="tm-card-top">
              <span class="tm-card-name">{{ item.name }}</span>
              <span class="tm-badge" :class="`trend-${item.trend_type}`">
                {{ TREND_TYPE_LABEL[item.trend_type] || item.trend_type }}
              </span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <div v-if="item.category || item.time_range" class="tm-meta-line">
              <span v-if="item.category">{{ item.category }}</span>
              <span v-if="item.time_range">{{ item.time_range }}</span>
            </div>
            <p v-if="item.description" class="tm-desc">{{ item.description }}</p>
            <ul v-if="item.change_points.length" class="point-list">
              <li v-for="point in item.change_points" :key="point">
                <span class="point-mark"></span>
                <span class="point-body point-text">{{ point }}</span>
              </li>
            </ul>
            <p v-if="item.evidence" class="tm-note">{{ item.evidence }}</p>
          </article>
        </section>

        <section
          v-else-if="activeTrendMode === 'problems' && trendData.problems.length"
          class="tm-section"
        >
          <article
            v-for="item in trendData.problems"
            :key="item.name"
            class="tm-card glass-item"
          >
            <div class="tm-card-top">
              <span class="tm-card-name">{{ item.name }}</span>
              <span v-if="item.category" class="tm-badge">{{ item.category }}</span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <p v-if="item.description" class="tm-desc">{{ item.description }}</p>
            <p v-if="item.impact" class="tm-impact">
              <span class="tm-impact-label">影响</span>
              <span>{{ item.impact }}</span>
            </p>
            <div v-if="item.related_technologies.length" class="tm-chips">
              <span v-for="tech in item.related_technologies" :key="tech" class="tm-chip">
                {{ tech }}
              </span>
            </div>
            <p v-if="item.evidence" class="tm-note">{{ item.evidence }}</p>
          </article>
        </section>
      </template>

      <template v-else-if="moduleKey === 'applications' && appData">
        <div v-if="showAppToggle" class="tm-toolbar">
          <div class="tm-toggle" role="group" aria-label="场景排行与场景变化切换">
            <button
              type="button"
              class="tm-toggle-btn"
              :class="{ active: activeAppMode === 'ranking' }"
              :aria-pressed="activeAppMode === 'ranking'"
              @click="appMode = 'ranking'"
            >
              <IconGlyph name="layout-list" :size="13" />
              <span>场景排行</span>
            </button>
            <button
              type="button"
              class="tm-toggle-btn"
              :class="{ active: activeAppMode === 'trends' }"
              :aria-pressed="activeAppMode === 'trends'"
              @click="appMode = 'trends'"
            >
              <IconGlyph name="arrow-up-down" :size="13" />
              <span>场景变化</span>
            </button>
          </div>
        </div>

        <template v-if="activeAppMode === 'ranking' && appData.scenario_ranking.items.length">
          <p v-if="appData.scenario_ranking.summary" class="tm-lead">
            {{ appData.scenario_ranking.summary }}
          </p>
          <section class="tm-section">
            <div
              v-for="item in appData.scenario_ranking.items"
              :key="item.name"
              class="tm-stat"
            >
              <div class="tm-stat-top">
                <span class="tm-stat-name">{{ item.name }}</span>
                <SourceLinks :links="links(item)" :more="more(item)" />
              </div>
              <div class="tm-meter">
                <span class="tm-track">
                  <i :style="{ width: trendBarWidth(item.percentage) }"></i>
                </span>
                <span class="tm-num">{{ trendPercentText(item.percentage) }}</span>
              </div>
              <div class="tm-meta-line">
                <span>{{ item.count }} 个页面提及</span>
                <span v-if="appData.total_mentions">全部场景共 {{ appData.total_mentions }} 次提及</span>
              </div>
              <div v-if="item.related_technologies.length" class="tm-chips">
                <span v-for="tech in item.related_technologies" :key="tech" class="tm-chip">
                  {{ tech }}
                </span>
              </div>
              <p v-if="item.evidence" class="tm-note">{{ item.evidence }}</p>
            </div>
          </section>
        </template>

        <template v-else-if="activeAppMode === 'trends' && appData.scenario_trends.items.length">
          <p v-if="appData.scenario_trends.summary" class="tm-lead">
            {{ appData.scenario_trends.summary }}
          </p>
          <div v-if="appData.scenario_trends.months.length" class="tm-axis">
            <span>{{ trendMonthLabel(appData.scenario_trends.months[0]) }}</span>
            <span>月度提及 · 共 {{ appData.scenario_trends.months.length }} 个月</span>
            <span>
              {{
                trendMonthLabel(
                  appData.scenario_trends.months[appData.scenario_trends.months.length - 1],
                )
              }}
            </span>
          </div>
          <section class="tm-section">
            <article
              v-for="item in appData.scenario_trends.items"
              :key="item.name"
              class="tm-card glass-item"
            >
              <div class="tm-card-top">
                <span class="tm-card-name">{{ item.name }}</span>
                <span class="tm-badge" :class="`trend-${item.trend}`">
                  {{ SCENARIO_TREND_LABEL[item.trend] || item.trend }}
                </span>
                <SourceLinks :links="links(item)" :more="more(item)" />
              </div>
              <div class="tm-scenario-chart">
                <div
                  v-for="(count, index) in item.monthly_counts"
                  :key="index"
                  class="tm-scenario-bar"
                  :title="`${appData.scenario_trends.months[index] || '对应月份'}：${count} 次提及`"
                >
                  <span class="tm-scenario-count">{{ count }}</span>
                  <span class="tm-scenario-track">
                    <i :style="{ height: trendSparkHeight(count, sparkMax(item.monthly_counts)) }"></i>
                  </span>
                  <span class="tm-scenario-month">
                    {{ trendMonthLabel(appData.scenario_trends.months[index] || '') }}
                  </span>
                </div>
              </div>
              <p v-if="item.evidence" class="tm-note">{{ item.evidence }}</p>
            </article>
          </section>
        </template>
      </template>

      <SynthesisPane
        v-else-if="moduleKey === 'syn'"
        :rows="synRows"
        :links-of="linksOf"
        :more-links="moreLinks"
      />
    </div>
  </Transition>
</template>

<style scoped src="./pane-shared.css"></style>
<style scoped src="./trend.css"></style>
