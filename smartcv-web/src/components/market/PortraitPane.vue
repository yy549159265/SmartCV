<script setup lang="ts">
import { computed } from 'vue'
import CareerFishbone from './CareerFishbone.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import type { GapView, ProjectView, SkillView } from '@/features/market/types'
import type {
  CareerStage,
  PanelRow,
  PortraitBlock,
  PortraitSection,
  ResumeEvidence,
} from '@/types/market'

const props = defineProps<{
  sections: PortraitSection[]
  hasRows: boolean
  emptyText: string
  skillView: SkillView
  projectView: ProjectView
  gapView: GapView
}>()

const emit = defineEmits<{
  (e: 'skill-view', value: SkillView): void
  (e: 'project-view', value: ProjectView): void
  (e: 'gap-view', value: GapView): void
}>()

/** 职业画像章节的 rows 平铺后按「标题：正文」的自述形态展示。 */
function rowsOf(section: PortraitSection): PanelRow[] {
  return section.blocks.flatMap((block) => block.rows)
}

/** 优先用后端给的结构化阶段；旧快照从 chips 的「阶段 · 角色 · 重点」回退解析。 */
function stagesOf(row: PanelRow): CareerStage[] {
  if (row.stages?.length) return row.stages
  return (row.chips || []).map((chip) => {
    const [stage = '', role = '', ...rest] = chip.split(' · ')
    return { stage, role, focus: rest.join(' · ') }
  })
}

/** 熟练度 → 徽标配色；未命中的等级按“提及”处理。 */
const LEVEL_CLASS: Record<string, string> = {
  精通: 'expert',
  熟练: 'proficient',
  熟悉: 'familiar',
  了解: 'familiar',
  提及: 'mentioned',
}

function levelClass(level: string): string {
  return LEVEL_CLASS[level] || 'mentioned'
}

/** 缺口严重程度 → 徽标配色；未知程度按「轻微」处理。 */
function severityClass(level: string): string {
  if (level === '严重') return 'high'
  if (level === '中等') return 'medium'
  return 'low'
}

/** 与汇总卡同一套熟练度顺序：精通 → 熟练 → 熟悉 → 了解 → 提及。 */
const LEVEL_ORDER: Record<string, number> = { 精通: 0, 熟练: 1, 熟悉: 2, 了解: 3, 提及: 4 }

const techSection = computed(
  () => props.sections.find((section) => section.key === 'profile:section:technical') || null,
)

/** 技能图谱按等级排序，同级保持后端顺序。 */
const techSkills = computed(() => {
  const rows = techSection.value ? rowsOf(techSection.value) : []
  return rows
    .filter((row) => row.tone === 'skill')
    .sort((a, b) => (LEVEL_ORDER[a.value || ''] ?? 4) - (LEVEL_ORDER[b.value || ''] ?? 4))
})

const techSummary = computed(() => {
  const rows = techSection.value ? rowsOf(techSection.value) : []
  return rows.find((row) => row.key === 'profile:tech:summary') || null
})

/** 项目画像的两个子视图共用项目章节，只把章节标题换成图标切换条。 */
function isProjectSection(section: PortraitSection): boolean {
  return section.key === 'profile:section:project' || section.key === 'profile:section:advantage'
}

/** 缺口画像一个页签、两个子视图：能力缺口块 / 简历缺口块。 */
function isGapSection(section: PortraitSection): boolean {
  return section.key === 'profile:section:gaps'
}

const gapTitle = computed(() => (props.gapView === 'capability' ? '能力缺口' : '简历缺口'))

const projectSection = computed(
  () => props.sections.find((section) => isProjectSection(section)) || null,
)

const projectSummary = computed(() => {
  const section = projectSection.value
  if (!section) return null
  const rows = rowsOf(section)
  return (
    rows.find((row) => row.key === 'profile:project:summary') ||
    rows.find((row) => row.key === 'profile:advantage:summary') ||
    null
  )
})

/** 按子视图选择要展示的块；缺口画像只在能力缺口 / 简历缺口之间切换。 */
function displayBlocks(section: PortraitSection): PortraitBlock[] {
  if (isGapSection(section)) {
    const suffix = props.gapView === 'capability' ? 'capability' : 'resume'
    return section.blocks.filter(
      (block) => block.key.endsWith(`:${suffix}`) && block.rows.length > 0,
    )
  }
  if (!isProjectSection(section)) return section.blocks
  return section.blocks
    .map((block) => ({
      ...block,
      rows: block.rows.filter((row) => !row.key.endsWith(':summary')),
    }))
    .filter((block) => block.rows.length > 0)
}

/** 只展示后端校验过的坐标，避免把模型臆测的章节行号显示给用户。 */
function verifiedEvidence(row: PanelRow): ResumeEvidence[] {
  return (row.resume_evidence || []).filter((ev) => ev.verified)
}

/** 坐标优先显示章节 + 行号；旧快照没有 section 时退回 location。 */
function evidenceLabel(ev: ResumeEvidence): string {
  const place = ev.location || ev.section
  return place ? `${place} · 第 ${ev.line} 行` : `第 ${ev.line} 行`
}
</script>

<template>
  <div v-if="!hasRows" class="pane-empty">{{ emptyText }}</div>
  <div v-else-if="!sections.length" class="pane-empty">画像已生成，暂无明细模块</div>
  <div v-else class="portrait">
    <section
      v-for="section in sections"
      :key="section.key"
      class="pcard portrait-section glass-surface"
    >
      <template v-if="section.key === 'profile:section:career'">
        <div class="career-body">
          <template v-for="row in rowsOf(section)" :key="row.key">
            <div v-if="row.key === 'profile:career:tags'" class="career-line career-tags">
              <span class="career-label">{{ row.label }}：</span>
              <span class="career-tag-list">
                <span v-for="tag in row.chips || []" :key="tag" class="career-tag">{{ tag }}</span>
              </span>
            </div>
            <div v-else-if="row.key === 'profile:career:path'" class="career-path">
              <p class="career-line">
                <span class="career-label">{{ row.label }}：</span>
              </p>
              <CareerFishbone :stages="stagesOf(row)" />
            </div>
            <p v-else class="career-line">
              <span class="career-label">{{ row.label }}：</span>
              <span class="career-value">{{ row.text || row.value }}</span>
            </p>
          </template>
        </div>
      </template>
      <template v-else-if="section.key === 'profile:section:technical'">
        <div class="skill-head">
          <span class="skill-title">{{ skillView === 'summary' ? '技能总结' : '技能图谱' }}</span>
          <div class="skill-tools" role="group" aria-label="技能画像视图">
            <button
              type="button"
              class="skill-tool"
              :class="{ active: skillView === 'summary' }"
              title="技能总结"
              aria-label="技能总结"
              :aria-pressed="skillView === 'summary'"
              @click="emit('skill-view', 'summary')"
            >
              <IconGlyph name="book-open" :size="14" />
            </button>
            <button
              type="button"
              class="skill-tool"
              :class="{ active: skillView === 'map' }"
              title="技能图谱"
              aria-label="技能图谱"
              :aria-pressed="skillView === 'map'"
              @click="emit('skill-view', 'map')"
            >
              <IconGlyph name="layers" :size="14" />
            </button>
          </div>
        </div>

        <div v-if="skillView === 'summary'" class="skill-summary">
          <p v-if="techSummary?.text" class="skill-summary-text">{{ techSummary.text }}</p>
          <p v-else class="skill-summary-empty">暂无技能总结</p>
        </div>

        <div v-else-if="techSkills.length" class="skill-grid">
          <div v-for="row in techSkills" :key="row.key" class="skill-card">
            <div class="skill-card-head">
              <span class="skill-name" :title="row.label">{{ row.label }}</span>
              <span v-if="row.value" class="level-badge" :class="levelClass(row.value)">
                {{ row.value }}
              </span>
            </div>
            <div v-if="verifiedEvidence(row).length" class="skill-evidence">
              <span
                v-for="ev in verifiedEvidence(row)"
                :key="ev.coordinate || ev.location"
                class="skill-ev"
                :title="[ev.quote, ev.coordinate].filter(Boolean).join(' · ')"
              >{{ evidenceLabel(ev) }}</span>
            </div>
          </div>
        </div>

        <p v-else class="skill-empty">暂无技能项</p>
      </template>
      <template v-else>
        <div v-if="isGapSection(section)" class="skill-head">
          <span class="skill-title">{{ gapTitle }}</span>
          <div class="skill-tools" role="group" aria-label="缺口画像视图">
            <button
              type="button"
              class="skill-tool"
              :class="{ active: gapView === 'capability' }"
              title="能力缺口"
              aria-label="能力缺口"
              :aria-pressed="gapView === 'capability'"
              @click="emit('gap-view', 'capability')"
            >
              <IconGlyph name="target" :size="14" />
            </button>
            <button
              type="button"
              class="skill-tool"
              :class="{ active: gapView === 'resume' }"
              title="简历缺口"
              aria-label="简历缺口"
              :aria-pressed="gapView === 'resume'"
              @click="emit('gap-view', 'resume')"
            >
              <IconGlyph name="file-text" :size="14" />
            </button>
          </div>
        </div>
        <div v-else-if="isProjectSection(section)" class="skill-head">
          <span class="skill-title">{{ projectView === 'summary' ? '项目总结' : '项目价值' }}</span>
          <div class="skill-tools" role="group" aria-label="项目画像视图">
            <button
              type="button"
              class="skill-tool"
              :class="{ active: projectView === 'summary' }"
              title="项目总结"
              aria-label="项目总结"
              :aria-pressed="projectView === 'summary'"
              @click="emit('project-view', 'summary')"
            >
              <IconGlyph name="book-open" :size="14" />
            </button>
            <button
              type="button"
              class="skill-tool"
              :class="{ active: projectView === 'value' }"
              title="项目价值"
              aria-label="项目价值"
              :aria-pressed="projectView === 'value'"
              @click="emit('project-view', 'value')"
            >
              <IconGlyph name="briefcase" :size="14" />
            </button>
          </div>
        </div>
        <div v-else-if="section.label" class="pcard-head">
          <span class="pcard-title">{{ section.label }}</span>
          <span class="pcard-sub">{{ section.count }} 项</span>
        </div>
        <div v-if="isProjectSection(section) && projectView === 'summary'" class="skill-summary">
          <p v-if="projectSummary?.text" class="skill-summary-text">{{ projectSummary.text }}</p>
          <p v-else class="skill-summary-empty">暂无项目总结</p>
        </div>
        <template v-else>
          <p
            v-if="isGapSection(section) && !displayBlocks(section).length"
            class="skill-empty"
          >{{ gapView === 'capability' ? '暂无能力缺口' : '暂无简历缺口' }}</p>
          <p
            v-else-if="isProjectSection(section) && !displayBlocks(section).length"
            class="skill-empty"
          >暂无项目</p>
          <div
            v-for="block in displayBlocks(section)"
            :key="block.key"
            class="portrait-block"
          >
            <div v-if="block.label" class="portrait-group-title">{{ block.label }}</div>
          <div class="portrait-rows">
            <div
              v-for="row in block.rows"
              :key="row.key"
              class="portrait-row"
              :class="[row.tone ? `tone-${row.tone}` : '', row.kind, row.tag || '']"
            >
              <div class="portrait-row-head">
                <span
                  v-if="row.kind === 'pair'"
                  class="portrait-dot"
                  :class="row.tag || 'hit'"
                ></span>
                <span class="portrait-row-label">{{ row.label }}</span>
                <span
                  v-if="row.type_label && row.type_label !== row.label"
                  class="portrait-type"
                >{{ row.type_label }}</span>
                <span
                  v-if="row.severity_label"
                  class="portrait-severity"
                  :class="severityClass(row.severity_label)"
                >{{ row.severity_label }}</span>
                <span
                  v-if="row.value"
                  :class="row.tone === 'skill' ? ['level-badge', levelClass(row.value)] : 'portrait-row-value'"
                >{{ row.value }}</span>
              </div>
              <p v-if="row.text" class="portrait-row-text">{{ row.text }}</p>
              <div
                v-if="row.chips?.length && row.tone !== 'skill'"
                class="portrait-row-chips"
              >
                <span v-for="chip in row.chips" :key="chip" class="portrait-chip">{{ chip }}</span>
              </div>
              <div v-if="row.groups?.length" class="portrait-row-groups">
                <div v-for="group in row.groups" :key="group.label" class="portrait-group">
                  <span class="portrait-group-label">{{ group.label }}</span>
                  <span class="portrait-group-items">
                    <span
                      v-for="(item, index) in group.items"
                      :key="`${group.label}-${index}`"
                      class="portrait-chip"
                    >{{ item }}</span>
                  </span>
                </div>
              </div>
              <div v-if="verifiedEvidence(row).length" class="portrait-row-evidence">
                <span
                  v-for="ev in verifiedEvidence(row)"
                  :key="ev.coordinate || ev.location"
                  class="portrait-evidence"
                  :title="[ev.quote, ev.coordinate].filter(Boolean).join(' · ')"
                >{{ evidenceLabel(ev) }}</span>
              </div>
            </div>
          </div>
          </div>
        </template>
      </template>
    </section>
  </div>
</template>

<style scoped src="./portrait.css"></style>
<style scoped src="./pane-shared.css"></style>
