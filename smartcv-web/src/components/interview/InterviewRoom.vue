<script setup lang="ts">
/** 对话面试房间：当前问题、作答、反馈、讲解模式与结束复盘。 */

import { computed, h, nextTick, ref, watch } from 'vue'
import { NButton, NSpace } from 'naive-ui'

import type { InterviewSummary } from '@/api/interview'
import { asrClock } from '@/composables/useAsrSettings'
import { useSpeechDictation } from '@/composables/useSpeechDictation'
import { useInterviewStore } from '@/stores/interview'
import { dialog } from '@/utils/feedback'
import {
  FINISH_LABEL,
  LEVEL_LABEL,
  PRIORITY_LABEL,
  SCENE_LABEL,
  dimensionLabel,
  levelHint,
} from '@/utils/interview'
import EvaluationCard from '@/components/interview/EvaluationCard.vue'
import TeachingPanel from '@/components/interview/TeachingPanel.vue'
import MicButton from '@/components/interview/MicButton.vue'
import IconGlyph from '@/components/IconGlyph.vue'

const emit = defineEmits<{ restart: [] }>()

const store = useInterviewStore()
const answer = ref('')
const answerInput = ref<HTMLTextAreaElement | null>(null)
const {
  isSupported: micSupported,
  isListening: micListening,
  isTranscribing: micTranscribing,
  mode: micMode,
  waveform: micWaveform,
  elapsed: micElapsed,
  maxSeconds: micMaxSeconds,
  toggle: toggleMic,
  stop: stopMic,
  cancel: cancelMic,
} = useSpeechDictation(answer)

const question = computed(() => store.question)
const card = computed(() => store.currentCard)
const isFollowup = computed(
  () => Boolean(question.value && question.value.text !== question.value.mainQuestion),
)

const projectName = computed(() => {
  const projectId = question.value?.projectId
  if (!projectId) return ''
  return (
    store.profileRecord?.profile.projects.find((project) => project.id === projectId)?.name ?? ''
  )
})

const progressPercent = computed(() => {
  const q = question.value
  if (!q || !q.total) return 0
  return Math.min(100, Math.round(((q.index - 1) / q.total) * 100))
})

watch(
  () => question.value?.text,
  () => {
    cancelMic()
    answer.value = ''
  },
)

watch(
  () => store.streaming,
  (streaming) => {
    if (streaming) cancelMic()
  },
)

const summary = computed<InterviewSummary>(
  () =>
    store.summary ?? {
      records: [],
      dynamicCount: 0,
      teachingCount: 0,
      answeredCount: 0,
      skippedCount: 0,
      finishedReason: '',
    },
)

const finishLabel = computed(() => {
  const reason = summary.value.finishedReason
  return FINISH_LABEL[reason] ?? reason
})

function submit() {
  const text = answer.value.trim()
  if (!text || store.streaming) return
  stopMic()
  store.submitAnswer(text)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    submit()
  }
}

function askTeach() {
  cancelMic()
  store.teach()
}

/**
 * 回到上一题重新作答。带上示例回答时直接填进作答框，
 * 用户可以按 AI 的答法提交一遍，看看新的评价。
 */
async function onReanswer(sample?: string) {
  if (store.streaming) return
  cancelMic()
  await store.reanswer()
  answer.value = sample ?? ''
  await nextTick()
  answerInput.value?.focus()
}

function skipCard() {
  cancelMic()
  store.skip()
}

/**
 * 主问题只有「跳过整道题」一种；追问还多一个「跳过这条追问」，
 * 只放弃当前追问、保留已答的主问题。
 */
function confirmSkip() {
  if (store.streaming) return
  const current = question.value
  if (!current || !isFollowup.value) {
    dialog.warning({
      title: '跳过本题？',
      content: '跳过会记入复盘，且不能再回到这道题。',
      positiveText: '跳过',
      negativeText: '继续作答',
      onPositiveClick: skipCard,
    })
    return
  }

  const level = current.level ? ` ${current.level} ` : ''
  const d = dialog.warning({
    title: `跳过当前${level}追问？`,
    content:
      '跳过追问只放弃当前这条，继续本题下一条追问；跳过整道题会结束本题。两种都不能再回到这里。',
    action: () =>
      h(
        NSpace,
        { justify: 'end', size: 8 },
        {
          default: () => [
            h(
              NButton,
              { size: 'small', quaternary: true, onClick: () => d.destroy() },
              { default: () => '继续作答' },
            ),
            h(
              NButton,
              {
                size: 'small',
                onClick: () => {
                  d.destroy()
                  skipCard()
                },
              },
              { default: () => '跳过整道题' },
            ),
            h(
              NButton,
              {
                size: 'small',
                type: 'warning',
                onClick: () => {
                  d.destroy()
                  cancelMic()
                  store.skipFollowup()
                },
              },
              { default: () => '跳过这条追问' },
            ),
          ],
        },
      ),
  })
}

function confirmEnd() {
  if (store.streaming) return
  dialog.warning({
    title: '结束本场面试？',
    content: '结束后会生成本场复盘，未答的题目记为跳过。',
    positiveText: '结束面试',
    negativeText: '继续面试',
    onPositiveClick: () => {
      cancelMic()
      store.endInterview()
    },
  })
}

function answerText(value: string): string {
  return value || '（未作答）'
}
</script>

<template>
  <section class="room">
    <!-- ---------------------------------------------------------------- 复盘 -->
    <template v-if="store.phase === 'finished' && store.summary">
      <article class="summary">
        <header class="summary-hero">
          <div class="hero-meta">
            <h2 class="hero-title">本场面试复盘</h2>
            <p class="hero-sub">
              {{ finishLabel || '已结束' }} · 共 {{ summary.records.length }} 条作答记录
            </p>
          </div>
          <div class="hero-stats">
            <span class="stat"><b>{{ summary.answeredCount }}</b> 已答</span>
            <span class="stat"><b>{{ summary.skippedCount }}</b> 跳过</span>
            <span class="stat"><b>{{ summary.dynamicCount }}</b> 动态追问</span>
            <span class="stat"><b>{{ summary.teachingCount }}</b> 次讲解</span>
          </div>
        </header>

        <div class="record-list">
          <details
            v-for="(record, index) in summary.records"
            :key="`${record.cardId}-${index}`"
            class="record"
            :open="index === 0"
          >
            <summary class="record-head">
              <span class="record-index">{{ index + 1 }}</span>
              <span class="record-question">{{ record.question }}</span>
              <span v-if="record.skipped" class="record-skip">跳过</span>
              <span class="record-open" aria-hidden="true">
                <IconGlyph name="chevron-down" :size="15" />
              </span>
            </summary>
            <div class="record-body">
              <p class="record-answer">{{ answerText(record.answer) }}</p>
              <ul v-if="record.leaks.length" class="record-leaks">
                <li v-for="(leak, leakIndex) in record.leaks" :key="leakIndex">{{ leak }}</li>
              </ul>
              <p v-if="record.feedback" class="record-feedback">{{ record.feedback }}</p>
              <div v-if="record.sampleAnswer" class="record-sample">
                <span class="record-sample-label">
                  <IconGlyph name="sparkles" :size="12" />
                  AI 示例回答
                </span>
                <p>{{ record.sampleAnswer }}</p>
              </div>
              <p v-if="record.offTopic" class="record-flag">本轮回答偏离问题</p>
            </div>
          </details>
        </div>

        <footer class="summary-foot">
          <p class="summary-hint">复盘只保存在当前浏览器，刷新后仍可从这里打开。</p>
          <div class="summary-actions">
            <button
              class="btn ghost"
              type="button"
              disabled
              title="面试报告生成即将上线"
            >
              <IconGlyph name="file-text" :size="14" />
              面试报告
            </button>
            <button class="btn primary" type="button" @click="emit('restart')">
              再面一场
              <IconGlyph name="arrow-right" :size="15" />
            </button>
          </div>
        </footer>
      </article>
    </template>

    <!-- ---------------------------------------------------------------- 面试 -->
    <template v-else-if="question">
      <header class="room-head">
        <div class="room-meta">
          <span class="scene-chip">{{ SCENE_LABEL[store.serverState?.scene ?? 'project'] }}</span>
          <span v-if="store.serverState?.followDepth === 'deep'" class="scene-chip deep">
            深度追问
          </span>
          <span class="progress-text">
            第 {{ question.index }} / {{ question.total }} 题
          </span>
          <span class="dot">·</span>
          <span class="dim">{{ dimensionLabel(question.dimension) }}</span>
          <span v-if="projectName" class="dot">·</span>
          <span v-if="projectName" class="project">{{ projectName }}</span>
        </div>
        <button class="end-btn" type="button" :disabled="store.streaming" @click="confirmEnd">
          结束面试
        </button>
      </header>

      <div class="progress-track" aria-hidden="true">
        <span class="progress-fill" :style="{ width: `${progressPercent}%` }"></span>
      </div>

      <article class="question-card">
        <div class="q-tags">
          <span
            v-if="isFollowup"
            class="q-tag followup"
            :title="levelHint(question.level || 'L1')"
          >
            {{ LEVEL_LABEL[question.level || 'L1'] }} 追问
          </span>
          <span v-else class="q-tag">主问题</span>
          <span v-if="question.dynamic" class="q-tag dynamic">动态追问</span>
          <span class="q-tag muted">{{ PRIORITY_LABEL[card?.priority ?? 'medium'] }}</span>
        </div>
        <p v-if="isFollowup" class="q-main">{{ question.mainQuestion }}</p>
        <p class="q-text">{{ question.text }}</p>
        <p v-if="card?.evidenceQuote" class="q-evidence">
          <IconGlyph name="file-text" :size="13" />
          <span>简历原文：{{ card.evidenceQuote }}</span>
        </p>
        <p v-if="question.reanswer" class="q-resume-note">
          回到这道题重新作答，提交后会重新评价。
        </p>
        <p v-else-if="question.resumed" class="q-resume-note">讲解结束，回到这道题作答。</p>
      </article>

      <!-- 讲解模式 -->
      <TeachingPanel
        v-if="store.phase === 'teaching'"
        :card="card"
        :question="question.text"
        :level="question.level"
        :turns="store.teachingTurns"
        :stream="store.teachingStream"
        :streaming="store.streaming"
        @send="(text) => store.teachMessage(text)"
        @return="store.returnToInterview()"
        @skip="confirmSkip"
      />

      <!-- 作答模式 -->
      <template v-else>
        <div class="composer">
          <textarea
            ref="answerInput"
            v-model="answer"
            class="answer-input"
            rows="5"
            placeholder="按真实面试来答：先说结论，再讲做法、权衡和结果。"
            :disabled="store.streaming"
            @keydown="onKeydown"
            @beforeinput="stopMic"
          ></textarea>
          <div class="composer-foot">
            <div class="composer-tools">
              <MicButton
                :listening="micListening"
                :supported="micSupported"
                :disabled="store.streaming"
                :transcribing="micTranscribing"
                :waveform="micWaveform"
                :mode="micMode"
                :elapsed="micElapsed"
                :max-seconds="micMaxSeconds"
                @toggle="toggleMic"
              />
              <span class="composer-hint">
                {{
                  micListening
                    ? micMode === 'deepseek'
                      ? `录音中 ${asrClock(micElapsed)} / ${asrClock(micMaxSeconds)}，再点一次结束并识别`
                      : '正在听写，说完再点一次麦克风停止'
                    : micTranscribing
                      ? '正在上传录音并识别…'
                      : store.statusText || (store.streaming ? '正在处理…' : 'Ctrl / ⌘ + Enter 提交')
                }}
              </span>
            </div>
            <div class="composer-actions">
              <button class="btn ghost" type="button" :disabled="store.streaming" @click="confirmSkip">
                跳过本题
              </button>
              <button class="btn ghost" type="button" :disabled="store.streaming" @click="askTeach">
                <IconGlyph name="book-open" :size="14" />
                不会，请讲解
              </button>
              <button
                class="btn primary"
                type="button"
                :disabled="store.streaming || micTranscribing || !answer.trim()"
                @click="submit"
              >
                <span v-if="store.streaming" class="spinner" aria-hidden="true"></span>
                {{ store.streaming ? '评估中…' : '提交作答' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="store.evaluationPending" class="eval-skeleton">
          <span class="sk-line w40"></span>
          <span class="sk-line"></span>
          <span class="sk-line w70"></span>
        </div>
        <EvaluationCard
          v-else-if="store.evaluation"
          :evaluation="store.evaluation"
          :question="store.pendingQuestion"
          :sample-pending="store.samplePending"
          :sample-disabled="store.streaming"
          @sample="store.generateSample()"
          @reanswer="onReanswer"
        />
      </template>
    </template>

    <p v-else class="room-empty">当前没有待作答的问题。</p>
  </section>
</template>

<style scoped>
.room {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.room-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
.room-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--text-tertiary);
}
.scene-chip {
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel-bg);
  color: var(--text-secondary);
  font-size: 12px;
}
.scene-chip.deep {
  border-color: #eadcc8;
  background: var(--warning-soft);
  color: var(--warning);
}
.progress-text {
  color: var(--text-secondary);
  font-weight: 600;
}
.dot {
  color: var(--border-strong);
}
.dim,
.project {
  color: var(--text-secondary);
  word-break: break-word;
}
.end-btn {
  height: 28px;
  padding: 0 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  color: var(--text-tertiary);
  font-size: 12.5px;
  cursor: pointer;
  transition:
    color 0.16s var(--ease),
    border-color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.end-btn:hover:not(:disabled) {
  border-color: #e0c9c7;
  background: var(--danger-soft);
  color: var(--danger);
}
.end-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.progress-track {
  height: 3px;
  border-radius: 999px;
  background: var(--surface-sunken);
  overflow: hidden;
}
.progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--primary);
  transition: width 0.35s var(--ease);
}

.question-card {
  padding: 20px 22px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  box-shadow: var(--shadow-paper);
}
.q-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.q-tag {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  line-height: 19px;
  font-weight: 600;
}
.q-tag.followup {
  background: var(--warning-soft);
  color: var(--warning);
}
.q-tag.dynamic {
  background: var(--success-soft);
  color: var(--success);
}
.q-tag.muted {
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-weight: 500;
}
.q-main {
  margin: 12px 0 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text-tertiary);
  word-break: break-word;
}
.q-text {
  margin: 12px 0 0;
  font-size: 18px;
  line-height: 1.7;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text);
  word-break: break-word;
}
.q-main + .q-text {
  margin-top: 6px;
}
.q-evidence {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 14px 0 0;
  padding: 8px 11px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-secondary);
  word-break: break-word;
}
.q-resume-note {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--primary);
}

.composer {
  padding: 14px 16px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
}
.answer-input {
  width: 100%;
  min-height: 118px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  color: var(--text);
  font-size: 14.5px;
  line-height: 1.7;
  resize: vertical;
  field-sizing: content;
}
.answer-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--focus-ring);
}
.answer-input:disabled {
  background: var(--surface-soft);
  color: var(--text-secondary);
}
.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.composer-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.composer-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.composer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
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

.eval-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
}
.sk-line {
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--surface-soft), var(--surface-sunken), var(--surface-soft));
  background-size: 200% 100%;
  animation: shimmer 1.4s ease infinite;
}
.sk-line.w40 {
  width: 40%;
}
.sk-line.w70 {
  width: 70%;
}
@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}

/* ---------------------------------------------------------------- 复盘 */
.summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.summary-hero {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  box-shadow: var(--shadow-paper);
}
.hero-meta {
  min-width: 0;
}
.hero-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.hero-sub {
  margin: 4px 0 0;
  font-size: 13.5px;
  color: var(--text-secondary);
}
.hero-stats {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-left: auto;
}
.stat {
  font-size: 12.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.stat b {
  display: block;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.record {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  overflow: hidden;
}
.record-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 16px;
  cursor: pointer;
  list-style: none;
}
.record-head::-webkit-details-marker {
  display: none;
}
.record-index {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--surface-soft);
  font-size: 12px;
  color: var(--text-tertiary);
}
.record-question {
  min-width: 0;
  flex: 1;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
}
.record-skip {
  flex: none;
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.record-open {
  flex: none;
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease);
}
.record[open] .record-open {
  transform: rotate(180deg);
}
.record-body {
  padding: 4px 16px 16px 50px;
  border-top: 1px dashed var(--border);
}
.record-answer {
  margin: 12px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  word-break: break-word;
  white-space: pre-wrap;
}
.record-leaks {
  margin: 10px 0 0;
  padding-left: 1.3em;
}
.record-leaks li {
  font-size: 13px;
  line-height: 1.65;
  color: var(--warning);
  word-break: break-word;
}
.record-feedback {
  margin: 10px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
}
.record-sample {
  margin-top: 10px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: var(--primary-faint);
}
.record-sample-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
}
.record-sample p {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
  white-space: pre-wrap;
}
.record-flag {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--warning);
}

.summary-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-top: 4px;
}
.summary-hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.room-empty {
  margin: 0;
  padding: 40px;
  text-align: center;
  font-size: 14px;
  color: var(--text-tertiary);
}

@media (max-width: 720px) {
  .answer-input {
    min-height: 96px;
  }
  .composer-actions {
    width: 100%;
    justify-content: flex-end;
  }
  .summary-hero {
    gap: 14px;
  }
  .hero-stats {
    margin-left: 0;
    width: 100%;
  }
  .record-body {
    padding-left: 16px;
  }
}
</style>
