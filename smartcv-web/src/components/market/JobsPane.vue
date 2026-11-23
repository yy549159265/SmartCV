<script setup lang="ts">
/** 招聘矩阵的结构化四块：岗位分布 / 技术需求 / 能力需求 / 任职要求。 */
import { computed } from 'vue'
import type { EvidenceLink } from '@/types/market'
import {
  IMPORTANCE_LABEL,
  REQUIREMENT_LABEL,
  barWidth,
  countText,
  distributionHasData,
  qualificationGroups,
  readAbilityMatrix,
  readJobDistribution,
  readQualificationMatrix,
  readTechnicalMatrix,
  salaryMetaText,
  salaryRangeText,
} from '@/features/market/jobs'
import SourceLinks from './SourceLinks.vue'

const props = defineProps<{
  moduleKey: string
  data?: Record<string, unknown>
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()

const distribution = computed(() => readJobDistribution(props.data))
const technical = computed(() => readTechnicalMatrix(props.data))
const ability = computed(() => readAbilityMatrix(props.data))
const qualification = computed(() => readQualificationMatrix(props.data))
const groups = computed(() => qualificationGroups(qualification.value))
const salary = computed(() => distribution.value?.salary_matrix || null)

const isEmpty = computed(() => {
  switch (props.moduleKey) {
    case 'distribution':
      return !distributionHasData(distribution.value)
    case 'technical':
      return !technical.value?.technologies.length
    case 'ability':
      return !ability.value?.abilities.length
    case 'qualification':
      return !groups.value.length
    default:
      return true
  }
})

/** 统计项只带 evidence 编号，转成面板统一的行形状再取来源链接。 */
function links(item: { evidence_ids?: string[] }): EvidenceLink[] {
  return props.linksOf({ evidence: item.evidence_ids || [] })
}

function more(item: { evidence_ids?: string[] }): number {
  return props.moreLinks({ evidence: item.evidence_ids || [] })
}
</script>

<template>
  <Transition name="mod-swap" mode="out-in">
    <div :key="moduleKey" class="jobs-matrix pane-module glass-surface">
      <div v-if="isEmpty" class="pane-empty">该模块暂无内容，切换上方卡片查看其他结论。</div>

      <template v-else-if="moduleKey === 'distribution' && distribution">
        <p v-if="distribution.summary" class="jm-lead">{{ distribution.summary }}</p>

        <section v-if="distribution.job_types.length" class="jm-section">
          <header class="jm-head">
            <span class="jm-head-title">岗位方向</span>
            <span class="jm-head-meta">{{ distribution.job_types.length }} 项</span>
          </header>
          <div
            v-for="item in distribution.job_types"
            :key="`type-${item.name}`"
            class="jm-stat"
          >
            <div class="jm-stat-top">
              <span class="jm-stat-name">{{ item.name }}</span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <div class="jm-meter">
              <span class="jm-track"><i :style="{ width: barWidth(item) }"></i></span>
              <span class="jm-num">{{ countText(item) }}</span>
            </div>
          </div>
        </section>

        <section v-if="distribution.company_distribution.length" class="jm-section">
          <header class="jm-head">
            <span class="jm-head-title">招聘企业</span>
            <span class="jm-head-meta">{{ distribution.company_distribution.length }} 家</span>
          </header>
          <div
            v-for="item in distribution.company_distribution"
            :key="`company-${item.name}`"
            class="jm-stat"
          >
            <div class="jm-stat-top">
              <span class="jm-stat-name">{{ item.name }}</span>
              <span class="jm-num">{{ item.count }} 个页面</span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
          </div>
        </section>

        <section v-if="salary" class="jm-section">
          <header class="jm-head">
            <span class="jm-head-title">薪资情况</span>
            <SourceLinks :links="links(salary)" :more="more(salary)" />
          </header>
          <div v-if="salary.available_count || salary.unavailable_count" class="jm-meta-line">
            <span v-if="salary.available_count">{{ salary.available_count }} 个页面写明薪资</span>
            <span v-if="salary.unavailable_count">{{ salary.unavailable_count }} 个页面未写明</span>
          </div>
          <div v-if="salary.salary_ranges.length" class="jm-salary-list">
            <div
              v-for="(range, rangeIndex) in salary.salary_ranges"
              :key="`salary-${rangeIndex}`"
              class="jm-salary-item"
            >
              <div class="jm-salary-top">
                <span class="jm-salary-value">{{ salaryRangeText(range) }}</span>
                <SourceLinks :links="links(range)" :more="more(range)" />
              </div>
              <span v-if="salaryMetaText(range)" class="jm-meta-text">
                {{ salaryMetaText(range) }}
              </span>
            </div>
          </div>
          <p v-if="salary.evidence" class="jm-note">{{ salary.evidence }}</p>
          <p v-if="salary.summary" class="jm-note">{{ salary.summary }}</p>
        </section>
      </template>

      <template v-else-if="moduleKey === 'technical' && technical">
        <p v-if="technical.summary" class="jm-lead">{{ technical.summary }}</p>
        <section class="jm-section">
          <div
            v-for="item in technical.technologies"
            :key="`tech-${item.name}`"
            class="jm-stat"
          >
            <div class="jm-stat-top">
              <span class="jm-stat-name">{{ item.name }}</span>
              <span class="jm-badge" :class="`req-${item.requirement_level}`">
                {{ REQUIREMENT_LABEL[item.requirement_level] }}
              </span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <div class="jm-meter">
              <span class="jm-track"><i :style="{ width: barWidth(item) }"></i></span>
              <span class="jm-num">{{ countText(item) }}</span>
            </div>
            <p v-if="item.evidence" class="jm-note">{{ item.evidence }}</p>
          </div>
        </section>
      </template>

      <template v-else-if="moduleKey === 'ability' && ability">
        <p v-if="ability.ability_summary" class="jm-lead">{{ ability.ability_summary }}</p>
        <section class="jm-section">
          <div
            v-for="item in ability.abilities"
            :key="`ability-${item.name}`"
            class="jm-stat"
          >
            <div class="jm-stat-top">
              <span class="jm-stat-name">{{ item.name }}</span>
              <span class="jm-badge" :class="`imp-${item.importance}`">
                重要程度 {{ IMPORTANCE_LABEL[item.importance] }}
              </span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <p v-if="item.description" class="jm-desc">{{ item.description }}</p>
            <div class="jm-meter">
              <span class="jm-track"><i :style="{ width: barWidth(item) }"></i></span>
              <span class="jm-num">{{ countText(item) }}</span>
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="moduleKey === 'qualification' && qualification">
        <p v-if="qualification.summary" class="jm-lead">{{ qualification.summary }}</p>
        <section v-for="group in groups" :key="group.key" class="jm-section">
          <header class="jm-head">
            <span class="jm-head-title">{{ group.label }}</span>
            <span class="jm-head-meta">{{ group.items.length }} 项</span>
          </header>
          <div
            v-for="item in group.items"
            :key="`${group.key}-${item.name}`"
            class="jm-stat"
          >
            <div class="jm-stat-top">
              <span class="jm-stat-name">{{ item.name }}</span>
              <span class="jm-num">{{ countText(item) }}</span>
              <SourceLinks :links="links(item)" :more="more(item)" />
            </div>
            <div class="jm-meter">
              <span class="jm-track"><i :style="{ width: barWidth(item) }"></i></span>
            </div>
          </div>
        </section>
      </template>
    </div>
  </Transition>
</template>

<style scoped src="./pane-shared.css"></style>
<style scoped src="./jobs.css"></style>
