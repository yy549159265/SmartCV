<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { AskQuestion, ChatAnswer } from '@/api/chat'
import type { QuestionItem } from '@/stores/review'

const props = defineProps<{ item: QuestionItem }>()

const emit = defineEmits<{
  submit: [questionId: string, answers: ChatAnswer[]]
}>()

const selected = reactive<Record<string, string[]>>({})
const customOn = reactive<Record<string, boolean>>({})
const customText = reactive<Record<string, string>>({})
const skipped = reactive(new Set<string>())

for (const q of props.item.questions) {
  selected[q.id] = []
  customOn[q.id] = false
  customText[q.id] = ''
}

const current = ref(0)
const currentQ = computed(() => props.item.questions[current.value] as AskQuestion)

const submitting = computed(() => props.item.status === 'submitting')

const fallbackExpiresAt = Date.now() + (props.item.timeoutSeconds || 300) * 1000
const expiresAt = computed(() => props.item.expiresAt || fallbackExpiresAt)
const now = ref(Date.now())
const remaining = computed(() => Math.max(0, Math.ceil((expiresAt.value - now.value) / 1000)))
const timeUp = computed(() => remaining.value <= 0)
const remainingText = computed(() => {
  const m = Math.floor(remaining.value / 60)
  const s = remaining.value % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

let timer: ReturnType<typeof setInterval> | undefined

function stopTimer() {
  if (timer !== undefined) {
    clearInterval(timer)
    timer = undefined
  }
}

function startTimer() {
  if (timer !== undefined) return
  timer = setInterval(() => {
    now.value = Date.now()
    if (remaining.value <= 0) stopTimer()
  }, 1000)
}

if (props.item.status === 'pending' || props.item.status === 'submitting') startTimer()

watch(
  () => props.item.status,
  (status) => {
    if (status === 'answered' || status === 'expired') stopTimer()
  },
)

onBeforeUnmount(stopTimer)

function answered(q: AskQuestion): boolean {
  return (
    (selected[q.id]?.length ?? 0) > 0 ||
    (customOn[q.id] && (customText[q.id] ?? '').trim().length > 0)
  )
}

function resolved(q: AskQuestion): boolean {
  return answered(q) || skipped.has(q.id)
}

const allResolved = computed(() => props.item.questions.every(resolved))
const isLast = computed(() => current.value >= props.item.questions.length - 1)

function goPrev() {
  if (current.value > 0) current.value -= 1
}

function goNext() {
  if (!isLast.value) current.value += 1
}

function skipCurrent() {
  const q = currentQ.value
  if (submitting.value) return
  selected[q.id] = []
  customOn[q.id] = false
  customText[q.id] = ''
  skipped.add(q.id)
  goNext()
}

function pick(q: AskQuestion, label: string) {
  if (submitting.value) return
  selected[q.id] = [label]
  customOn[q.id] = false
  skipped.delete(q.id)
}

function pickCustom(q: AskQuestion) {
  if (submitting.value) return
  selected[q.id] = []
  customOn[q.id] = true
  skipped.delete(q.id)
}

function toggle(q: AskQuestion, label: string) {
  if (submitting.value) return
  const list = selected[q.id] ?? (selected[q.id] = [])
  const i = list.indexOf(label)
  if (i >= 0) list.splice(i, 1)
  else list.push(label)
  skipped.delete(q.id)
}

function toggleCustom(q: AskQuestion) {
  if (submitting.value) return
  customOn[q.id] = !customOn[q.id]
  skipped.delete(q.id)
}

function isChecked(q: AskQuestion, label: string): boolean {
  return (selected[q.id] ?? []).includes(label)
}

function onCustomInput(q: AskQuestion) {
  skipped.delete(q.id)
}

function buildAnswers(): ChatAnswer[] {
  return props.item.questions.map((q) => ({
    id: q.id,
    selected: [...(selected[q.id] ?? [])],
    custom: customOn[q.id] ? (customText[q.id] ?? '').trim() : '',
  }))
}

function onSubmit() {
  if (!allResolved.value || submitting.value || timeUp.value) return
  emit('submit', props.item.questionId, buildAnswers())
}

function onSkipAll() {
  if (submitting.value) return
  emit('submit', props.item.questionId, [])
}

function answerText(q: AskQuestion): string {
  const answers = props.item.answers ?? []
  if (answers.length === 0) return '已跳过'
  const a = answers.find((x) => x.id === q.id)
  if (!a) return '未作答'
  const parts = [...(a.selected ?? [])]
  if (a.custom) parts.push(a.custom)
  return parts.length ? parts.join('、') : '未作答'
}
</script>

<template>
  <div class="ask-card" :class="item.status">
    <div class="ask-head">
      <span class="ask-icon" aria-hidden="true">?</span>
      <span class="ask-title">{{ item.title || '需要确认几个信息' }}</span>
      <span
        v-if="item.status === 'pending' && !timeUp"
        class="ask-timer"
        :class="{ urgent: remaining <= 30 }"
        :title="`后端最长等待 ${item.timeoutSeconds} 秒`"
      >
        ⏱ {{ remainingText }}
      </span>
      <span class="ask-badge">
        {{
          item.status === 'answered'
            ? '已回答'
            : item.status === 'expired' || (item.status === 'pending' && timeUp)
              ? '已失效'
              : item.status === 'submitting'
                ? '提交中…'
                : '等待回答'
        }}
      </span>
    </div>

    <div v-if="item.status === 'answered'" class="ask-summary">
      <div v-for="q in item.questions" :key="q.id" class="sum-row">
        <span class="sum-q">{{ q.header || q.question }}</span>
        <span class="sum-a">{{ answerText(q) }}</span>
      </div>
    </div>

    <div
      v-else-if="item.status === 'expired' || (item.status === 'pending' && timeUp)"
      class="ask-expired"
    >
      该问题已失效（等待超时或对话已结束），本次诊断将按现有信息继续。
    </div>

    <div v-else class="ask-form">
      <div class="ask-progress">
        <span class="ask-progress-text">
          第 {{ current + 1 }} / {{ item.questions.length }} 题
        </span>
        <span class="ask-dots">
          <i
            v-for="(q, i) in item.questions"
            :key="q.id"
            :class="{ active: i === current, done: resolved(q) }"
          />
        </span>
      </div>

      <div class="ask-q">
        <div class="ask-q-head">
          <span class="ask-q-index">{{ current + 1 }}</span>
          <span class="ask-q-header">{{ currentQ.header }}</span>
          <span class="ask-q-mode">{{ currentQ.multiSelect ? '可多选' : '单选' }}</span>
          <span v-if="skipped.has(currentQ.id)" class="ask-q-skipped">已跳过</span>
        </div>
        <div class="ask-q-text">{{ currentQ.question }}</div>

        <div class="ask-options">
          <label
            v-for="opt in currentQ.options"
            :key="opt.label"
            class="ask-opt"
            :class="{ checked: isChecked(currentQ, opt.label) }"
          >
            <input
              v-if="!currentQ.multiSelect"
              type="radio"
              :name="currentQ.id"
              :checked="isChecked(currentQ, opt.label)"
              @change="pick(currentQ, opt.label)"
            />
            <input
              v-else
              type="checkbox"
              :checked="isChecked(currentQ, opt.label)"
              @change="toggle(currentQ, opt.label)"
            />
            <span class="opt-main">
              <span class="opt-label">{{ opt.label }}</span>
              <span v-if="opt.description" class="opt-desc">{{ opt.description }}</span>
            </span>
          </label>

          <label class="ask-opt custom" :class="{ checked: customOn[currentQ.id] }">
            <input
              v-if="!currentQ.multiSelect"
              type="radio"
              :name="currentQ.id"
              :checked="customOn[currentQ.id]"
              @change="pickCustom(currentQ)"
            />
            <input
              v-else
              type="checkbox"
              :checked="customOn[currentQ.id]"
              @change="toggleCustom(currentQ)"
            />
            <span class="opt-main">
              <span class="opt-label">其他（自定义输入）</span>
            </span>
          </label>

          <n-input
            v-if="customOn[currentQ.id]"
            v-model:value="customText[currentQ.id]"
            size="small"
            class="custom-input"
            placeholder="直接输入你的答案"
            :disabled="submitting"
            @update:value="onCustomInput(currentQ)"
            @keydown.enter.stop
          />
        </div>
      </div>

      <div class="ask-actions">
        <span class="ask-tip">回答后 AI 会继续诊断；可逐题跳过，未答的题按未提供处理。</span>
        <n-button size="small" quaternary :disabled="current === 0 || submitting" @click="goPrev">
          上一个
        </n-button>
        <n-button size="small" quaternary :disabled="submitting" @click="skipCurrent">
          {{ skipped.has(currentQ.id) ? '已跳过' : '跳过本题' }}
        </n-button>
        <n-button
          v-if="!isLast"
          size="small"
          type="primary"
          :disabled="submitting"
          @click="goNext"
        >
          下一个
        </n-button>
        <n-button
          v-else
          size="small"
          type="primary"
          :disabled="!allResolved || submitting || timeUp"
          :loading="submitting"
          @click="onSubmit"
        >
          提交回答
        </n-button>
      </div>

      <div class="ask-foot">
        <button type="button" class="ask-skip-all" :disabled="submitting" @click="onSkipAll">
          全部跳过
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ask-card {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 10px 12px;
  background: var(--panel-bg);
  border: 1px solid var(--primary-soft);
  border-left: 3px solid var(--primary);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-raised);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ask-card.answered {
  border-left-color: var(--primary);
  opacity: 0.92;
}
.ask-card.expired {
  border-left-color: var(--border-strong);
  opacity: 0.8;
}

.ask-head {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}
.ask-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}
.ask-title {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  overflow-wrap: anywhere;
}
.ask-timer {
  flex: none;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.ask-timer.urgent {
  color: var(--danger, #d03050);
}
.ask-badge {
  flex: none;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-hover);
  font-size: 10.5px;
  font-weight: 600;
}

.ask-progress {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ask-progress-text {
  font-size: 10.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ask-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ask-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border);
  transition: background 0.14s var(--ease), transform 0.14s var(--ease);
}
.ask-dots i.done {
  background: var(--primary-soft);
}
.ask-dots i.active {
  background: var(--primary);
  transform: scale(1.25);
}

.ask-q {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px 0;
}
.ask-q-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ask-q-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border-radius: 4px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 10px;
  font-weight: 600;
}
.ask-q-header {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
}
.ask-q-mode {
  font-size: 10px;
  color: var(--text-tertiary);
}
.ask-q-skipped {
  font-size: 10px;
  color: var(--text-tertiary);
  font-style: italic;
}
.ask-q-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  overflow-wrap: anywhere;
}

.ask-options {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ask-opt {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-soft);
  cursor: pointer;
  transition: border-color 0.14s var(--ease), background 0.14s var(--ease);
}
.ask-opt:hover {
  border-color: var(--primary);
}
.ask-opt.checked {
  border-color: var(--primary);
  background: var(--primary-faint);
}
.ask-opt input {
  flex: none;
  margin: 2px 0 0;
  accent-color: var(--primary);
  cursor: pointer;
}
.opt-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.opt-label {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text);
  overflow-wrap: anywhere;
}
.opt-desc {
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--text-tertiary);
  overflow-wrap: anywhere;
}
.custom-input {
  margin-top: 2px;
}

.ask-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 2px;
}
.ask-tip {
  flex: 1;
  min-width: 140px;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--text-tertiary);
}

.ask-foot {
  display: flex;
  justify-content: flex-end;
}
.ask-skip-all {
  padding: 0;
  border: 0;
  background: none;
  font-size: 10.5px;
  color: var(--text-tertiary);
  cursor: pointer;
}
.ask-skip-all:hover:not(:disabled) {
  color: var(--primary);
  text-decoration: underline;
}
.ask-skip-all:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.ask-expired {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}

.ask-summary {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.sum-row {
  display: flex;
  gap: 8px;
  font-size: 11.5px;
  line-height: 1.6;
}
.sum-q {
  flex: none;
  color: var(--text-tertiary);
}
.sum-a {
  min-width: 0;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
</style>
