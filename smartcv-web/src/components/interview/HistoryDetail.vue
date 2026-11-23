<script setup lang="ts">
/** 最近面试回看：对话展示完整问答与讲解，清单展示历史题包快照。 */

import { computed } from 'vue'

import type {
  AnswerRecord,
  InterviewSummary,
  ResumeProfile,
  TeachingEvent,
} from '@/api/interview'
import type { SessionRecord } from '@/utils/interviewDb'
import type { ReviewRound } from '@/utils/interviewReview'
import { formatDateTime } from '@/utils/interview'
import {
  attemptLabel,
  groupReviewRounds,
  outcomeLabel,
  roundKind,
} from '@/utils/interviewReview'
import { exportInterviewHtml } from '@/utils/interviewExport'
import IconGlyph from '@/components/IconGlyph.vue'
import PackList from '@/components/interview/PackList.vue'

const props = withDefaults(
  defineProps<{
    session: SessionRecord
    profile: ResumeProfile | null
    /** 独立浏览时显示「关闭」；当前面试复盘时显示「返回当前进度」。 */
    dismissLabel?: string
  }>(),
  { dismissLabel: '返回当前进度' },
)

const emit = defineEmits<{
  close: []
  seen: [cardId: string]
}>()

const isChecklist = computed(() => props.session.useMode === 'checklist')
const teaching = computed<TeachingEvent[]>(() => props.session.teaching ?? [])
const timeLabel = computed(() =>
  formatDateTime(props.session.endedAt || props.session.startedAt),
)
const summary = computed<InterviewSummary>(() => {
  if (props.session.summary) return props.session.summary
  const records = props.session.records
  const answered = records.filter((record) => !record.skipped)
  return {
    records,
    dynamicCount: 0,
    teachingCount: teaching.value.length,
    answeredCount: answered.length,
    skippedCount: records.length - answered.length,
    finishedReason: '',
  }
})

const rounds = computed<ReviewRound[]>(() =>
  groupReviewRounds(summary.value.records, teaching.value),
)

function answerText(value: string): string {
  return value || '（未作答）'
}

function hasAssessment(record: AnswerRecord): boolean {
  return Boolean(
    record.offTopic ||
      record.leaks.length ||
      record.feedback ||
      record.sampleAnswer,
  )
}

function onExport(): void {
  exportInterviewHtml(props.session, props.profile)
}
</script>

<template>
  <PackList
    v-if="isChecklist && session.checklistCards"
    :cards="session.checklistCards"
    :warnings="session.checklistWarnings"
    :scene="session.scene"
    :focus="session.focus"
    :profile="profile"
    :seen-card-ids="session.checklistSeenCardIds ?? []"
    mode="checklist"
    review
    exportable
    :back-label="dismissLabel"
    :startable="false"
    @back="emit('close')"
    @seen="emit('seen', $event)"
    @export="onExport"
  />

  <div v-else-if="isChecklist" class="empty-card">
    <p>这条清单记录缺少题卡快照，无法回看。</p>
  </div>

  <section v-else class="review">
    <header class="review-head">
      <div class="head-copy">
        <h2 class="review-title">项目面试</h2>
        <p class="review-sub">
          {{ timeLabel }} · {{ summary.records.length }} 条作答记录 ·
          {{ teaching.length }} 次讲解
        </p>
      </div>
    </header>

    <div class="summary-strip">
      <span class="summary-stat"><b>{{ summary.answeredCount }}</b> 已答</span>
      <span class="summary-stat"><b>{{ summary.skippedCount }}</b> 跳过</span>
      <span class="summary-stat"><b>{{ summary.dynamicCount }}</b> 动态追问</span>
      <span class="summary-stat"><b>{{ teaching.length }}</b> 次讲解</span>
    </div>

    <section class="review-section">
      <h3 class="section-title">问题回看</h3>

      <div v-if="rounds.length" class="round-list">
        <details
          v-for="(round, index) in rounds"
          :key="round.key"
          class="round"
          :open="index === 0"
        >
          <summary class="round-head">
            <span class="round-main">
              <span class="round-meta">
                <span class="turn-kind">{{ roundKind(round) }}</span>
                <span v-if="round.records.length > 1" class="round-note">
                  {{ round.records.length }} 次作答
                </span>
                <span v-if="round.teachings.length" class="round-note">
                  {{ round.teachings.length }} 次讲解
                </span>
              </span>
              <span class="round-question">{{ round.question }}</span>
            </span>
            <span class="round-side">
              <span v-if="!round.records.length" class="round-note">无作答</span>
              <IconGlyph name="chevron-down" :size="15" class="round-chevron" />
            </span>
          </summary>

          <div class="round-body">
            <div class="sub-block">
              <h4 class="sub-title">对话内容</h4>
              <div v-if="round.records.length" class="answer-list">
                <article
                  v-for="(record, recordIndex) in round.records"
                  :key="`${record.cardId}-${recordIndex}`"
                  class="answer-block"
                >
                  <div class="answer-head">
                    <span class="turn-kind">
                      {{ attemptLabel(round, record) }}
                    </span>
                    <span v-if="record.skipped" class="turn-skip">跳过</span>
                  </div>

                  <div class="turn-line reply">
                    <span class="speaker">你的回答</span>
                    <p>{{ answerText(record.answer) }}</p>
                  </div>

                  <section
                    v-if="!record.skipped && hasAssessment(record)"
                    class="assessment"
                  >
                    <h5 class="assessment-title">回答评估</h5>

                    <p v-if="record.offTopic" class="off-topic">这条回答偏离问题</p>

                    <div v-if="record.leaks.length" class="assessment-block">
                      <h6 class="assessment-label">没讲到的关键点</h6>
                      <ul class="leaks">
                        <li v-for="(leak, leakIndex) in record.leaks" :key="leakIndex">
                          {{ leak }}
                        </li>
                      </ul>
                    </div>

                    <div v-if="record.feedback" class="assessment-block">
                      <h6 class="assessment-label">改进建议</h6>
                      <p class="feedback">{{ record.feedback }}</p>
                    </div>

                    <div
                      v-if="record.sampleAnswer"
                      class="assessment-block assessment-sample"
                    >
                      <h6 class="assessment-label">
                        <IconGlyph name="sparkles" :size="12" />
                        AI 示例回答
                      </h6>
                      <p class="sample-text">{{ record.sampleAnswer }}</p>
                    </div>
                  </section>
                </article>
              </div>
              <p v-else class="round-empty">这个问题没有留下作答记录。</p>
            </div>

            <div v-if="round.teachings.length" class="sub-block">
              <h4 class="sub-title">讲解内容</h4>
              <div class="teach-list">
                <article
                  v-for="(event, eventIndex) in round.teachings"
                  :key="`${event.cardId}-${eventIndex}`"
                  class="teach-event"
                >
                  <header class="teach-head">
                    <span class="turn-kind">讲解</span>
                    <span v-if="outcomeLabel(event.outcome)" class="teach-outcome">
                      {{ outcomeLabel(event.outcome) }}
                    </span>
                  </header>
                  <div class="teach-turns">
                    <div
                      v-for="(turn, turnIndex) in event.turns"
                      :key="turnIndex"
                      class="teach-turn"
                      :data-role="turn.role"
                    >
                      <span class="speaker">
                        {{ turn.role === 'teacher' ? 'AI 导师' : '你' }}
                      </span>
                      <p>{{ turn.content }}</p>
                    </div>
                  </div>
                </article>
              </div>
            </div>
          </div>
        </details>
      </div>

      <p v-else class="empty-text">这场面试没有留下作答或讲解记录。</p>
    </section>

    <footer class="review-foot">
      <div class="foot-actions">
        <button
          class="btn ghost"
          type="button"
          disabled
          title="面试报告生成即将上线"
        >
          <IconGlyph name="file-text" :size="14" />
          面试报告
        </button>
        <button class="btn" type="button" @click="onExport">
          <IconGlyph name="download" :size="14" />
          导出
        </button>
        <button class="btn" type="button" @click="emit('close')">
          <IconGlyph name="chevron-left" :size="15" />
          {{ dismissLabel }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.review {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.review-head {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  flex-wrap: wrap;
}
.head-copy {
  min-width: 0;
}
.review-title {
  margin: 0;
  font-size: 23px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text);
  word-break: break-word;
}
.review-sub {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.summary-strip {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  box-shadow: var(--shadow-paper);
}
.summary-stat {
  font-size: 12.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.summary-stat b {
  display: block;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.review-section {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.section-title {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}
.round-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.round {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
}
.round[open] {
  box-shadow: var(--shadow-paper);
}
.round-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 13px 16px;
  list-style: none;
  cursor: pointer;
  transition: background 0.16s var(--ease);
}
.round-head::-webkit-details-marker {
  display: none;
}
.round-head:hover {
  background: var(--surface-soft);
}
.round-head:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}
.round[open] .round-head {
  border-bottom: 1px solid var(--border);
}
.round-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.round-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.round-note {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.round-question {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
}
.round-side {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 1px;
}
.round-chevron {
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease);
}
.round[open] .round-chevron {
  transform: rotate(180deg);
}
.round-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px 16px 16px;
}
.sub-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sub-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}
.answer-list,
.teach-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.answer-block {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
}
.answer-head {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.round-empty {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-tertiary);
}
.turn-kind {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11.5px;
  line-height: 18px;
  white-space: nowrap;
}
.turn-skip {
  font-size: 12px;
  color: var(--text-tertiary);
}

.turn-line {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 11px;
}
.speaker {
  flex: none;
  min-width: 56px;
  padding-top: 1px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.turn-line p {
  min-width: 0;
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
  white-space: pre-wrap;
}
.turn-line.reply {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.turn-line.reply .speaker {
  color: var(--primary);
}
.turn-line.reply p {
  color: var(--text-secondary);
}

.assessment {
  display: flex;
  flex-direction: column;
  gap: 11px;
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.assessment-title {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-secondary);
}
.assessment-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.assessment-label {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.assessment-sample {
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: var(--primary-faint);
}
.assessment-sample .assessment-label {
  color: var(--primary);
}
.leaks {
  margin: 0;
  padding-left: 1.3em;
}
.leaks li {
  font-size: 13px;
  line-height: 1.65;
  color: var(--warning);
  word-break: break-word;
}
.feedback {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
  white-space: pre-wrap;
}
.sample-text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
  white-space: pre-wrap;
}
.off-topic {
  margin: 0;
  font-size: 12.5px;
  color: var(--warning);
}

.teach-event {
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
}
.teach-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.teach-outcome {
  flex: none;
  font-size: 12px;
  color: var(--text-tertiary);
}
.teach-turns {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 11px;
}
.teach-turn {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
}
.teach-turn[data-role='teacher'] {
  background: var(--primary-faint);
}
.teach-turn p {
  min-width: 0;
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  word-break: break-word;
  white-space: pre-wrap;
}
.teach-turn[data-role='teacher'] .speaker {
  color: var(--primary);
}

.review-foot {
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
  gap: 8px;
  flex-wrap: wrap;
}
.empty-text {
  margin: 0;
  padding: 24px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  text-align: center;
  font-size: 13.5px;
  color: var(--text-tertiary);
  background: var(--panel-bg);
}
.empty-card {
  padding: 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  text-align: center;
  font-size: 13.5px;
  color: var(--text-tertiary);
}
.empty-card p {
  margin: 0;
}

@media (max-width: 680px) {
  .foot-actions {
    width: 100%;
    justify-content: flex-end;
  }
  .round-head {
    gap: 8px;
    padding: 12px 13px;
  }
  .round-body {
    padding: 12px 13px 14px;
  }
  .round-side {
    gap: 5px;
  }
  .assessment {
    padding: 10px 12px;
  }
}
</style>
