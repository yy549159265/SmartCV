<script setup lang="ts">
/** 清单自测：把问题包按项目 / 优先级 / 层级筛出来看，展开即视为已读。 */

import { computed, ref } from 'vue'

import type {
  FollowLevel,
  PackFocus,
  Priority,
  QuestionCard,
  ResumeProfile,
  Scene,
  UseMode,
} from '@/api/interview'
import { LEVEL_LABEL, PRIORITY_LABEL, focusLabel } from '@/utils/interview'
import IconGlyph from '@/components/IconGlyph.vue'
import QuestionCardView from './QuestionCard.vue'

const props = withDefaults(
  defineProps<{
    cards: QuestionCard[]
    warnings?: string[]
    scene: Scene
    focus?: PackFocus
    profile: ResumeProfile | null
    seenCardIds: string[]
    mode: UseMode
    startable?: boolean
    starting?: boolean
    /** 正在生成主问题答案的卡片 id；进入清单后会并发多张。 */
    generatingCardIds?: string[]
    /** 正在生成追问答案的卡片 id。 */
    generatingFollowUpsCardIds?: string[]
    /** 按用户思路改写一条追问；由页面传入，回看态不生效。 */
    rewriteFollowUp?: (
      cardId: string,
      followUpId: string,
      instruction: string,
    ) => Promise<string | null>
    /** 按方向新增一条追问；由页面传入，回看态不生效。 */
    addFollowUp?: (cardId: string, instruction: string) => Promise<string | null>
    /** 删除一条追问；由页面传入，回看态不生效。 */
    deleteFollowUp?: (cardId: string, followUpId: string) => Promise<boolean>
    /** 历史回看：隐藏 AI 补答案入口，底部只保留返回与报告占位。 */
    review?: boolean
    /** 回看态底部的返回文案；独立浏览历史时用「关闭」。 */
    backLabel?: string
    /** 回看态额外显示「导出」；具体导出什么由父组件决定。 */
    exportable?: boolean
  }>(),
  {
    warnings: () => [],
    generatingCardIds: () => [],
    generatingFollowUpsCardIds: () => [],
    backLabel: '返回当前进度',
  },
)

const emit = defineEmits<{
  seen: [cardId: string]
  generateAnswer: [cardId: string]
  generateFollowUps: [cardId: string]
  back: []
  start: []
  export: []
}>()

const title = computed(() => (props.mode === 'checklist' ? '清单自测' : '问题包回看'))
const sceneLabel = computed(() => {
  const base = props.scene === 'comprehensive' ? '综合面试' : '项目面试'
  const focus = focusLabel(props.focus)
  return focus ? `${base} · ${focus}` : base
})
const startLabel = computed(() => '用这份题包重新开始面试')

const projectFilter = ref('all')
const priorityFilter = ref<'all' | Priority>('all')
const levelFilter = ref<'all' | FollowLevel>('all')
const keyword = ref('')

const projectNames = computed(() => {
  const map = new Map<string, string>()
  for (const project of props.profile?.projects ?? []) map.set(project.id, project.name)
  return map
})

function projectName(card: QuestionCard): string {
  return projectNames.value.get(card.projectId) ?? '通用'
}

const projects = computed(() => {
  const ids = [...new Set(props.cards.map((card) => card.projectId))].filter(Boolean)
  return ids.map((id) => ({ id, name: projectNames.value.get(id) ?? '未命名项目' }))
})

const filtered = computed(() => {
  const word = keyword.value.trim().toLowerCase()
  return props.cards.filter((card) => {
    if (projectFilter.value !== 'all' && card.projectId !== projectFilter.value) return false
    if (priorityFilter.value !== 'all' && card.priority !== priorityFilter.value) return false
    if (
      levelFilter.value !== 'all' &&
      !card.followUps.some((followUp) => followUp.level === levelFilter.value)
    ) {
      return false
    }
    if (!word) return true
    const haystack = [
      card.mainQuestion,
      card.intent,
      card.evidenceQuote,
      ...card.followUps.map((item) => item.question),
      ...card.leakSignals,
      ...card.coverage,
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(word)
  })
})

function isSeen(cardId: string): boolean {
  return props.seenCardIds.includes(cardId)
}
</script>

<template>
  <section class="pack-panel">
    <header class="pack-head">
      <div class="head-main">
        <h2 class="pack-title">{{ title }}</h2>
        <p class="pack-sub">{{ cards.length }} 道主问题 · {{ sceneLabel }}</p>
      </div>
      <div class="head-stats">
        <span class="stat-pill muted">已读 {{ seenCardIds.length }} / {{ cards.length }}</span>
      </div>
    </header>

    <div v-if="warnings.length" class="warn-block">
      <IconGlyph name="info" :size="15" />
      <div>
        <p v-for="(warning, index) in warnings" :key="index">{{ warning }}</p>
      </div>
    </div>

    <div class="filters">
      <input v-model="keyword" class="filter-input" type="search" placeholder="搜索问题或关键点" />
      <select v-model="projectFilter" class="filter-select" aria-label="按项目筛选">
        <option value="all">全部项目</option>
        <option v-for="project in projects" :key="project.id" :value="project.id">
          {{ project.name }}
        </option>
      </select>
      <select v-model="priorityFilter" class="filter-select" aria-label="按优先级筛选">
        <option value="all">全部优先级</option>
        <option value="high">{{ PRIORITY_LABEL.high }}</option>
        <option value="medium">{{ PRIORITY_LABEL.medium }}</option>
        <option value="low">{{ PRIORITY_LABEL.low }}</option>
      </select>
      <select v-model="levelFilter" class="filter-select" aria-label="按追问层级筛选">
        <option value="all">全部层级</option>
        <option value="L1">{{ LEVEL_LABEL.L1 }}</option>
        <option value="L2">{{ LEVEL_LABEL.L2 }}</option>
        <option value="L3">{{ LEVEL_LABEL.L3 }}</option>
      </select>
    </div>

    <p v-if="!filtered.length" class="empty">没有符合筛选条件的问题。</p>

    <div v-else class="card-list">
      <QuestionCardView
        v-for="card in filtered"
        :key="card.id"
        :card="card"
        :index="cards.indexOf(card) + 1"
        :project-name="projectName(card)"
        :seen="isSeen(card.id)"
        :review="review"
        :generating-answer="generatingCardIds.includes(card.id)"
        :generating-follow-ups="generatingFollowUpsCardIds.includes(card.id)"
        :rewrite-follow-up="rewriteFollowUp"
        :add-follow-up="addFollowUp"
        :delete-follow-up="deleteFollowUp"
        @seen="emit('seen', card.id)"
        @generate-answer="emit('generateAnswer', card.id)"
        @generate-follow-ups="emit('generateFollowUps', card.id)"
      />
    </div>

    <footer class="pack-foot">
      <div class="foot-actions">
        <button
          v-if="review"
          class="btn ghost"
          type="button"
          disabled
          title="面试报告生成即将上线"
        >
          <IconGlyph name="file-text" :size="14" />
          面试报告
        </button>
        <button
          v-if="review && exportable"
          class="btn"
          type="button"
          @click="emit('export')"
        >
          <IconGlyph name="download" :size="14" />
          导出
        </button>
        <button class="btn" type="button" :disabled="starting" @click="emit('back')">
          <IconGlyph :name="review ? 'chevron-left' : 'refresh-cw'" :size="14" />
          {{ review ? backLabel : '重新选题生成' }}
        </button>
        <button
          v-if="startable && mode === 'dialog'"
          class="btn primary"
          type="button"
          :disabled="starting"
          @click="emit('start')"
        >
          <span v-if="starting" class="spinner" aria-hidden="true"></span>
          {{ starting ? '正在创建面试…' : startLabel }}
          <IconGlyph v-if="!starting" name="arrow-right" :size="15" />
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.pack-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.pack-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}
.pack-title {
  margin: 0;
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.pack-sub {
  margin: 5px 0 0;
  font-size: 13.5px;
  color: var(--text-secondary);
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
  background: var(--panel-bg);
  color: var(--text-tertiary);
}

.warn-block {
  display: flex;
  gap: 10px;
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

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-input {
  flex: 1;
  min-width: 180px;
  height: 34px;
  padding: 0 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  color: var(--text);
  font-size: 13.5px;
}
.filter-select {
  height: 34px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  color: var(--text-secondary);
  font-size: 13.5px;
}
.filter-input:focus,
.filter-select:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--focus-ring);
}

.empty {
  margin: 0;
  padding: 34px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  text-align: center;
  font-size: 13.5px;
  color: var(--text-tertiary);
  background: var(--panel-bg);
}

.card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pack-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
  flex-wrap: wrap;
  padding-top: 4px;
}
.foot-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 680px) {
  .filters {
    flex-direction: column;
  }
  .filter-input,
  .filter-select {
    width: 100%;
  }
  .pack-foot {
    flex-direction: column;
    align-items: stretch;
  }
  .foot-actions {
    flex-direction: column;
    align-items: stretch;
  }
  .btn {
    justify-content: center;
  }
}
</style>
