<script setup lang="ts">
/**
 * 单张问题卡：主问题、追问链、AI 示范答案、露馅信号与覆盖要点。
 *
 * 第 3 步确认题包与第 5 步清单自测共用，默认折叠，展开即视为已读；
 * 第 3 步只确认题目，通过 `showReference=false` 隐藏参考答案。进入清单后
 * 答案不自动生成，由用户在「追问链」「参考答案」标题旁点击「AI生成答案」触发。
 * 每条追问可像证据锚点一样点「AI 改写」按自己的思路重写，层级由服务端锁定。
 */

import { computed, nextTick, ref } from 'vue'

import type { FollowUp, QuestionCard } from '@/api/interview'
import {
  LEVEL_LABEL,
  PRIORITY_LABEL,
  dimensionLabel,
  levelHint,
} from '@/utils/interview'
import { dialog, message } from '@/utils/feedback'
import IconGlyph from '@/components/IconGlyph.vue'
import ReferenceAnswerPanel from './ReferenceAnswerPanel.vue'

const props = withDefaults(
  defineProps<{
    card: QuestionCard
    /** 在整份题包里的序号，筛选后仍显示原始序号。 */
    index: number
    projectName: string
    seen?: boolean
    /** 回看态：隐藏 AI 补答案入口。 */
    review?: boolean
    /** 是否展示参考答案与追问示范答案；第 3 步确认题目时关闭。 */
    showReference?: boolean
    generatingAnswer?: boolean
    generatingFollowUps?: boolean
    /** 按用户思路改写一条追问；不传时不显示「AI 改写」入口。返回 null 表示未处理。 */
    rewriteFollowUp?: (
      cardId: string,
      followUpId: string,
      instruction: string,
    ) => Promise<string | null>
    /** 按方向新增一条追问；层级由服务端判断。返回 null 表示未处理。 */
    addFollowUp?: (cardId: string, instruction: string) => Promise<string | null>
    /** 删除一条追问；不传时不显示「删除」入口。 */
    deleteFollowUp?: (cardId: string, followUpId: string) => Promise<boolean>
  }>(),
  { review: false, showReference: true },
)

const emit = defineEmits<{
  seen: []
  generateAnswer: []
  generateFollowUps: []
}>()

const answersBusy = computed(
  () => Boolean(props.generatingAnswer || props.generatingFollowUps),
)

const hasMainAnswer = computed(() => Boolean(props.card.referenceAnswer?.answer))

const missingFollowUpCount = computed(
  () =>
    props.card.followUps.filter(
      (followUp) => followUp.id && !followUp.referenceAnswer?.answer,
    ).length,
)

const canGenerateMain = computed(
  () => props.showReference && !props.review && !hasMainAnswer.value,
)

const canGenerateFollowUps = computed(
  () => props.showReference && !props.review && missingFollowUpCount.value > 0,
)

const canRewriteFollowUps = computed(
  () => !props.review && Boolean(props.rewriteFollowUp),
)

const canAddFollowUps = computed(
  () => !props.review && Boolean(props.addFollowUp),
)

const canDeleteFollowUps = computed(
  () => !props.review && Boolean(props.deleteFollowUp),
)

const editingFollowUpId = ref('')
const followUpInstruction = ref('')
const followUpSaving = ref(false)
const followUpInput = ref<HTMLTextAreaElement | null>(null)

const addingFollowUp = ref(false)
const followUpDirection = ref('')
const followUpAddSaving = ref(false)
const followUpAddInput = ref<HTMLTextAreaElement | null>(null)

function followUpInputRef(id: string) {
  return (el: unknown): void => {
    if (el instanceof HTMLTextAreaElement && id === editingFollowUpId.value) {
      followUpInput.value = el
    }
  }
}

async function startFollowUpEdit(followUp: FollowUp): Promise<void> {
  if (followUpSaving.value || followUpAddSaving.value || !followUp.id) return
  cancelFollowUpAdd()
  editingFollowUpId.value = followUp.id
  followUpInstruction.value = ''
  await nextTick()
  followUpInput.value?.focus()
}

function cancelFollowUpEdit(): void {
  editingFollowUpId.value = ''
  followUpInstruction.value = ''
}

async function submitFollowUpEdit(followUp: FollowUp): Promise<void> {
  const instruction = followUpInstruction.value.trim()
  if (!instruction) {
    message.warning('先写一下想怎么改')
    return
  }
  const rewrite = props.rewriteFollowUp
  if (followUpSaving.value || followUpAddSaving.value || !rewrite || !followUp.id) return
  followUpSaving.value = true
  try {
    const summary = await rewrite(props.card.id, followUp.id, instruction)
    if (summary === null) return
    cancelFollowUpEdit()
    message.success(summary || '已按你的思路修改')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '改写失败')
  } finally {
    followUpSaving.value = false
  }
}

async function startFollowUpAdd(): Promise<void> {
  if (followUpSaving.value || followUpAddSaving.value) return
  cancelFollowUpEdit()
  addingFollowUp.value = true
  followUpDirection.value = ''
  await nextTick()
  followUpAddInput.value?.focus()
}

function cancelFollowUpAdd(): void {
  addingFollowUp.value = false
  followUpDirection.value = ''
}

async function submitFollowUpAdd(): Promise<void> {
  const instruction = followUpDirection.value.trim()
  if (!instruction) {
    message.warning('先写一下想追问的方向')
    return
  }
  const add = props.addFollowUp
  if (!add || followUpAddSaving.value || followUpSaving.value) return
  followUpAddSaving.value = true
  try {
    const summary = await add(props.card.id, instruction)
    if (summary === null) return
    cancelFollowUpAdd()
    message.success(summary || '已添加追问')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '新增追问失败')
  } finally {
    followUpAddSaving.value = false
  }
}

function confirmDeleteFollowUp(followUp: FollowUp): void {
  const remove = props.deleteFollowUp
  if (!remove || followUpSaving.value || followUpAddSaving.value) return
  dialog.warning({
    title: '删除这条追问？',
    content: '删除后，这道追问和它的 AI 示范答案都会移除；需要时可以再让 AI 添加。',
    positiveText: '删除',
    negativeText: '保留',
    onPositiveClick: async () => {
      try {
        const deleted = await remove(props.card.id, followUp.id)
        if (!deleted) return false
        if (editingFollowUpId.value === followUp.id) cancelFollowUpEdit()
        message.success('已删除追问')
      } catch (error) {
        message.error(error instanceof Error ? error.message : '删除追问失败')
        return false
      }
    },
  })
}

function onToggle(event: Event) {
  const element = event.target as HTMLDetailsElement
  if (element.open && !props.seen) emit('seen')
}
</script>

<template>
  <details class="card" @toggle="onToggle">
    <summary class="card-head">
      <span class="card-index">{{ index }}</span>
      <span class="card-main">
        <span class="card-tags">
          <span class="tag" :data-priority="card.priority">
            {{ PRIORITY_LABEL[card.priority] }}
          </span>
          <span class="tag muted">{{ dimensionLabel(card.dimension) }}</span>
          <span class="tag muted">{{ projectName }}</span>
          <span v-if="seen" class="tag seen">已读</span>
        </span>
        <span class="card-question">{{ card.mainQuestion }}</span>
      </span>
      <span class="card-open" aria-hidden="true">
        <IconGlyph name="chevron-down" :size="16" />
      </span>
    </summary>

    <div class="card-body">
      <p class="intent">{{ card.intent }}</p>
      <p v-if="card.evidenceQuote" class="evidence">
        <IconGlyph name="file-text" :size="13" />
        <span>简历原文：{{ card.evidenceQuote }}</span>
      </p>

      <section v-if="card.followUps.length || canAddFollowUps" class="section">
        <div class="section-head">
          <h4 class="section-title">追问链</h4>
          <div class="section-actions">
            <button
              v-if="canAddFollowUps"
              class="mini-ai-btn"
              type="button"
              :disabled="answersBusy || followUpAddSaving || followUpSaving"
              @click="startFollowUpAdd"
            >
              <IconGlyph name="plus" :size="12" />
              AI 添加追问
            </button>
            <button
              v-if="canGenerateFollowUps"
              class="mini-ai-btn"
              type="button"
              :disabled="answersBusy || followUpAddSaving"
              @click="emit('generateFollowUps')"
            >
              <span v-if="generatingFollowUps" class="spinner dark" aria-hidden="true"></span>
              <IconGlyph v-else name="sparkles" :size="12" />
              {{ generatingFollowUps ? 'AI 生成中…' : 'AI生成答案' }}
            </button>
          </div>
        </div>

        <p v-if="!card.followUps.length" class="follow-empty">还没有追问。</p>

        <ol v-if="card.followUps.length" class="follow-list">
          <li v-for="followUp in card.followUps" :key="followUp.id" class="follow-item">
            <span
              class="level-chip"
              :data-level="followUp.level"
              :title="levelHint(followUp.level)"
            >
              {{ LEVEL_LABEL[followUp.level] }}
            </span>
            <div class="follow-body">
              <p class="follow-question">
                {{ followUp.question }}
                <button
                  v-if="canRewriteFollowUps && followUp.id"
                  class="anchor-mark"
                  type="button"
                  :disabled="followUpSaving || followUpAddSaving"
                  title="让 AI 按你的思路改写这道追问"
                  @click="startFollowUpEdit(followUp)"
                >
                  AI 改写
                </button>
                <button
                  v-if="canDeleteFollowUps && followUp.id"
                  class="anchor-mark danger"
                  type="button"
                  :disabled="followUpSaving || followUpAddSaving"
                  title="删除这道追问"
                  @click="confirmDeleteFollowUp(followUp)"
                >
                  删除
                </button>
              </p>
              <p v-if="followUp.intent" class="follow-intent">{{ followUp.intent }}</p>

              <div v-if="editingFollowUpId === followUp.id" class="anchor-editor">
                <textarea
                  :ref="followUpInputRef(followUp.id)"
                  v-model="followUpInstruction"
                  class="anchor-input"
                  rows="3"
                  :aria-label="`描述想怎么修改这道${LEVEL_LABEL[followUp.level]}`"
                  :placeholder="`描述你想怎么改问法，例如：换成候选人真实的排查过程；改写后仍是 ${LEVEL_LABEL[followUp.level]} 追问`"
                  :disabled="followUpSaving"
                  @keydown.enter.meta.prevent="submitFollowUpEdit(followUp)"
                  @keydown.enter.ctrl.prevent="submitFollowUpEdit(followUp)"
                  @keydown.esc.prevent="cancelFollowUpEdit"
                ></textarea>
                <div class="anchor-editor-actions">
                  <button
                    class="btn ghost sm"
                    type="button"
                    :disabled="followUpSaving"
                    @click="cancelFollowUpEdit"
                  >
                    取消
                  </button>
                  <button
                    class="btn primary sm"
                    type="button"
                    :disabled="followUpSaving"
                    @click="submitFollowUpEdit(followUp)"
                  >
                    {{ followUpSaving ? '改写中…' : '按这个思路改写' }}
                  </button>
                </div>
              </div>

              <ReferenceAnswerPanel
                v-if="showReference && followUp.referenceAnswer?.answer"
                :answer="followUp.referenceAnswer"
                compact
              />
            </div>
          </li>
        </ol>

        <div v-if="addingFollowUp" class="anchor-editor follow-up-add">
          <textarea
            ref="followUpAddInput"
            v-model="followUpDirection"
            class="anchor-input"
            rows="3"
            aria-label="描述想新增的追问方向"
            placeholder="想追问什么方向，例如：追问缓存与数据库的一致性"
            :disabled="followUpAddSaving"
            @keydown.enter.meta.prevent="submitFollowUpAdd"
            @keydown.enter.ctrl.prevent="submitFollowUpAdd"
            @keydown.esc.prevent="cancelFollowUpAdd"
          ></textarea>
          <div class="anchor-editor-actions">
            <button
              class="btn ghost sm"
              type="button"
              :disabled="followUpAddSaving"
              @click="cancelFollowUpAdd"
            >
              取消
            </button>
            <button
              class="btn primary sm"
              type="button"
              :disabled="followUpAddSaving || !followUpDirection.trim()"
              @click="submitFollowUpAdd"
            >
              {{ followUpAddSaving ? '添加中…' : '添加追问' }}
            </button>
          </div>
        </div>
      </section>

      <section v-if="showReference" class="section">
        <div class="section-head">
          <h4 class="section-title">参考答案</h4>
          <button
            v-if="canGenerateMain"
            class="mini-ai-btn"
            type="button"
            :disabled="answersBusy"
            @click="emit('generateAnswer')"
          >
            <span v-if="generatingAnswer" class="spinner dark" aria-hidden="true"></span>
            <IconGlyph v-else name="sparkles" :size="12" />
            {{ generatingAnswer ? 'AI 生成中…' : 'AI生成答案' }}
          </button>
        </div>

        <div v-if="!hasMainAnswer" class="pending">
          <p v-if="generatingAnswer" class="pending-text">
            <span class="spinner dark" aria-hidden="true"></span>
            正在生成参考答案…
          </p>
          <p v-else class="pending-text">参考答案尚未生成。</p>
        </div>
        <ReferenceAnswerPanel v-else :answer="card.referenceAnswer" />
      </section>

      <section v-if="card.leakSignals.length" class="section">
        <h4 class="section-title">容易露馅的地方</h4>
        <ul class="leak-list">
          <li v-for="(leak, leakIndex) in card.leakSignals" :key="leakIndex">{{ leak }}</li>
        </ul>
      </section>

      <section v-if="card.coverage.length" class="section">
        <h4 class="section-title">覆盖要点</h4>
        <div class="coverage">
          <span v-for="(item, itemIndex) in card.coverage" :key="itemIndex" class="coverage-chip">
            {{ item }}
          </span>
        </div>
      </section>
    </div>
  </details>
</template>

<style scoped>
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  overflow: hidden;
}
.card[open] {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-raised);
}
.card-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  cursor: pointer;
  list-style: none;
}
.card-head::-webkit-details-marker {
  display: none;
}
.card-index {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin-top: 1px;
  border-radius: 6px;
  background: var(--surface-soft);
  font-size: 12px;
  color: var(--text-tertiary);
}
.card-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.card-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.tag {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 11.5px;
  line-height: 18px;
  white-space: nowrap;
}
.tag.muted {
  background: var(--surface-soft);
}
.tag[data-priority='high'] {
  background: var(--danger-soft);
  color: var(--danger);
}
.tag[data-priority='medium'] {
  background: var(--primary-soft);
  color: var(--primary);
}
.tag[data-priority='low'] {
  background: var(--surface-soft);
  color: var(--text-tertiary);
}
.tag.seen {
  background: var(--success-soft);
  color: var(--success);
}
.card-question {
  font-size: 15px;
  line-height: 1.6;
  font-weight: 600;
  color: var(--text);
  word-break: break-word;
}
.card-open {
  flex: none;
  margin-top: 2px;
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease);
}
.card[open] .card-open {
  transform: rotate(180deg);
}

.card-body {
  padding: 4px 18px 20px 50px;
  border-top: 1px dashed var(--border);
}
.intent {
  margin: 12px 0 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text-secondary);
  word-break: break-word;
}
.evidence {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 10px 0 0;
  padding: 8px 11px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-secondary);
  word-break: break-word;
}
.section {
  margin-top: 18px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.section-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.section-title {
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}
.section-head .section-title {
  margin: 0;
}
.mini-ai-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border: 0;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 600;
  line-height: 18px;
  white-space: nowrap;
  cursor: pointer;
  transition: filter 0.16s var(--ease);
}
.mini-ai-btn:hover:not(:disabled) {
  filter: brightness(0.96);
}
.mini-ai-btn:disabled {
  opacity: 0.65;
  cursor: default;
}
.mini-ai-btn .spinner {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
}
.follow-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.follow-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}
.level-chip {
  flex: none;
  margin-top: 1px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 11.5px;
  line-height: 18px;
  white-space: nowrap;
}
.level-chip[data-level='L3'] {
  background: var(--primary-soft);
  color: var(--primary);
}
.follow-body {
  min-width: 0;
  flex: 1;
}
.follow-question {
  margin: 0;
  font-size: 14px;
  line-height: 1.65;
  color: var(--text);
  word-break: break-word;
}
.follow-intent {
  margin: 3px 0 8px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
  word-break: break-word;
}
.follow-empty {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-tertiary);
}
.follow-up-add {
  margin-top: 12px;
}
/* 追问的改写入口与锚点一致：正文末尾的上标，点开才出现输入框。 */
.anchor-mark {
  display: inline;
  margin-left: 4px;
  padding: 0;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
  vertical-align: super;
  color: var(--text-tertiary);
  cursor: pointer;
  text-decoration-line: underline;
  text-decoration-style: dotted;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 2px;
  transition: color var(--dur-2) var(--ease);
}
.anchor-mark:hover {
  color: var(--primary);
  text-decoration-style: solid;
  text-decoration-color: currentColor;
}
.anchor-mark.danger {
  margin-left: 5px;
}
.anchor-mark.danger::before {
  content: '·';
  margin-right: 5px;
  color: var(--border-strong);
}
.anchor-mark.danger:hover {
  color: var(--danger);
}
.anchor-mark:disabled {
  opacity: 0.45;
  cursor: default;
  text-decoration: none;
}
.anchor-editor {
  margin: 9px 0;
  padding-top: 9px;
  border-top: 1px dashed var(--border);
}
.anchor-input {
  display: block;
  width: 100%;
  min-height: 68px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text);
  resize: vertical;
}
.anchor-input::placeholder {
  color: var(--text-tertiary);
}
.anchor-input:focus {
  outline: none;
  border-color: var(--primary);
  background: var(--panel-bg);
  box-shadow: 0 0 0 3px var(--focus-ring);
}
.anchor-input:disabled {
  opacity: 0.7;
}
.anchor-editor-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 9px;
}
.pending {
  padding: 12px 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.pending-text {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.leak-list {
  margin: 0;
  padding-left: 1.3em;
}
.leak-list li {
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--warning);
  word-break: break-word;
}
.coverage {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.coverage-chip {
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: var(--text-secondary);
  word-break: break-word;
}
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.spinner.dark {
  border-color: var(--primary-soft);
  border-top-color: var(--primary);
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 680px) {
  .card-body {
    padding-left: 16px;
  }
}
</style>
