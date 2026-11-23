<script setup lang="ts">
/**
 * 第 3 步：确认题目。直接用问题卡展示整份题包，每张卡可折叠，只展开主问题与追问链，
 * 不展示参考答案与 AI 补答案入口。面试方式放到下一步选。
 */

import { computed } from 'vue'

import type {
  FollowLevel,
  PackFocus,
  QuestionCard,
  ResumeProfile,
} from '@/api/interview'
import { LEVEL_HINT, LEVEL_LABEL, focusLabel } from '@/utils/interview'
import IconGlyph from '@/components/IconGlyph.vue'
import QuestionCardView from './QuestionCard.vue'

const props = defineProps<{
  /** 完整题包就是这一组问题卡，不再额外包一层题包对象。 */
  cards: QuestionCard[]
  /** 项目面试的考察方向；综合面试为空。 */
  focus?: PackFocus
  /** 生成阶段的非阻断提示，例如某个分组没有返回可用题目。 */
  warnings?: string[]
  profile: ResumeProfile | null
  /** 按用户思路改写一条追问；追问层级保持不变。 */
  rewriteFollowUp?: (
    cardId: string,
    followUpId: string,
    instruction: string,
  ) => Promise<string | null>
  /** 按方向新增一条追问；层级由服务端判断。 */
  addFollowUp?: (cardId: string, instruction: string) => Promise<string | null>
  /** 删除一条追问。 */
  deleteFollowUp?: (cardId: string, followUpId: string) => Promise<boolean>
}>()

const emit = defineEmits<{
  back: []
  next: []
}>()

const levelLegend = (['L1', 'L2', 'L3'] as FollowLevel[]).map((level) => ({
  level,
  label: LEVEL_LABEL[level],
  hint: LEVEL_HINT[level],
}))

const projectNames = computed(() => {
  const map = new Map<string, string>()
  for (const project of props.profile?.projects ?? []) map.set(project.id, project.name)
  return map
})

function projectName(projectId: string): string {
  return projectNames.value.get(projectId) ?? '通用'
}
</script>

<template>
  <section class="review-panel">
    <header class="review-head">
      <div class="head-copy">
        <span class="eyebrow">
          <IconGlyph name="sparkles" :size="14" />
          问题包已生成
          <span
            class="level-help"
            tabindex="0"
            aria-label="查看追问层级说明"
          >
            <IconGlyph name="info" :size="13" />
            <span class="level-help-panel" role="tooltip">
              <span v-for="item in levelLegend" :key="item.level" class="level-help-row">
                <b>{{ item.label }}</b>{{ item.hint }}
              </span>
            </span>
          </span>
        </span>
        <h2 class="review-title">确认题目</h2>
      </div>
      <div class="head-stats">
        <span v-if="focusLabel(focus)" class="stat-pill muted">
          {{ focusLabel(focus) }}
        </span>
        <span class="stat-pill">{{ cards.length }} 道主问题</span>
      </div>
    </header>

    <div v-if="warnings?.length" class="warn-block">
      <IconGlyph name="info" :size="15" />
      <div>
        <p v-for="(warning, index) in warnings" :key="index">{{ warning }}</p>
      </div>
    </div>

    <div class="card-list">
      <QuestionCardView
        v-for="(card, index) in cards"
        :key="card.id"
        :card="card"
        :index="index + 1"
        :project-name="projectName(card.projectId)"
        :show-reference="false"
        :rewrite-follow-up="rewriteFollowUp"
        :add-follow-up="addFollowUp"
        :delete-follow-up="deleteFollowUp"
      />
    </div>

    <footer class="review-foot">
      <button class="btn ghost" type="button" @click="emit('back')">
        <IconGlyph name="chevron-left" :size="15" />
        返回调整场景
      </button>
      <button class="btn primary" type="button" @click="emit('next')">
        下一步：选择面试方式
        <IconGlyph name="arrow-right" :size="15" />
      </button>
    </footer>
  </section>
</template>

<style scoped>
.review-panel {
  padding: 26px 30px 30px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-paper);
}
.review-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}
.head-copy {
  min-width: 0;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--primary);
}
.review-title {
  margin: 10px 0 0;
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.head-stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.stat-pill {
  padding: 3px 9px;
  border: 1px solid #d9ddf5;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12.5px;
  white-space: nowrap;
}
.stat-pill.muted {
  border-color: var(--border);
  background: var(--surface-soft);
  color: var(--text-secondary);
}
.level-help {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--text-tertiary);
  cursor: help;
}
.level-help:hover,
.level-help:focus {
  color: var(--primary);
  background: var(--primary-soft);
  outline: none;
}
.level-help-panel {
  position: absolute;
  top: calc(100% + 8px);
  left: -8px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: min(340px, calc(100vw - 56px));
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  box-shadow: var(--shadow-paper);
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition:
    opacity 0.16s var(--ease),
    transform 0.16s var(--ease),
    visibility 0.16s;
  pointer-events: none;
}
.level-help:hover .level-help-panel,
.level-help:focus .level-help-panel {
  opacity: 1;
  visibility: visible;
  transform: none;
}
.level-help-row b {
  margin-right: 5px;
  font-weight: 600;
  color: var(--text);
}
.warn-block {
  display: flex;
  gap: 10px;
  margin-top: 18px;
  padding: 11px 14px;
  border: 1px solid #eadcc8;
  border-radius: var(--radius-md);
  background: var(--warning-soft);
  color: var(--warning);
}
.warn-block p {
  margin: 0 0 4px;
  font-size: 13.5px;
  line-height: 1.6;
}
.warn-block p:last-child {
  margin-bottom: 0;
}

.card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
}

.review-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 26px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
@media (max-width: 760px) {
  .review-panel {
    padding: 20px 18px 24px;
  }
  .review-foot {
    flex-direction: column-reverse;
    align-items: stretch;
  }
  .btn {
    justify-content: center;
  }
}
</style>
