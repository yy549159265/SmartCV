<script setup lang="ts">
/** 单轮作答反馈：露馅信号与改进建议。 */

import { computed } from 'vue'

import type { Evaluation } from '@/api/interview'
import IconGlyph from '@/components/IconGlyph.vue'

const props = withDefaults(
  defineProps<{
    evaluation: Evaluation
    question?: string
    /** 正在生成 AI 示例回答。 */
    samplePending?: boolean
    /** 本轮 SSE 还没结束，先不允许触发后端生成。 */
    sampleDisabled?: boolean
  }>(),
  { samplePending: false, sampleDisabled: false },
)

const emit = defineEmits<{
  sample: []
  /** 回到这一题重新作答；带上示例回答时，直接把示例填进作答框。 */
  reanswer: [sample?: string]
}>()

const sampleLocked = computed(() => props.samplePending || props.sampleDisabled)

const sourceLabel = computed(() => {
  const source = props.evaluation.source
  if (source === 'followup') return '追问作答'
  if (source === 'reanswer') return '重答'
  return '主问题作答'
})

// 没有建议也没有遗漏点时，没有可示范的改进内容。
const canSample = computed(() =>
  Boolean(props.evaluation.feedback || props.evaluation.leaks.length),
)
</script>

<template>
  <article class="eval-card">
    <header class="eval-head">
      <span class="eval-source">
        {{ sourceLabel }}<template v-if="evaluation.level"> · {{ evaluation.level }}</template>
      </span>
      <span v-if="evaluation.offTopic" class="offtopic">
        <IconGlyph name="info" :size="13" />
        本轮回答偏离问题
      </span>
    </header>

    <p v-if="question" class="eval-question">{{ question }}</p>

    <div v-if="evaluation.leaks.length" class="leak-block">
      <h4 class="block-label">没讲到的关键点</h4>
      <ul class="leak-list">
        <li v-for="(leak, index) in evaluation.leaks" :key="index">{{ leak }}</li>
      </ul>
    </div>

    <div v-if="evaluation.feedback" class="feedback-block">
      <h4 class="block-label">改进建议</h4>
      <p class="feedback-text">{{ evaluation.feedback }}</p>
    </div>

    <div v-if="evaluation.sampleAnswer" class="sample-block">
      <div class="sample-head">
        <h4 class="block-label sample-label">
          <IconGlyph name="sparkles" :size="13" />
          AI 示例回答
        </h4>
        <button
          class="sample-retry"
          type="button"
          :disabled="sampleLocked"
          @click="emit('sample')"
        >
          {{ samplePending ? '生成中…' : '重新生成' }}
        </button>
      </div>
      <p class="sample-text">{{ evaluation.sampleAnswer }}</p>
    </div>
    <div v-else-if="canSample" class="sample-actions">
      <button
        class="btn ghost sample-btn"
        type="button"
        :disabled="sampleLocked"
        @click="emit('sample')"
      >
        <IconGlyph v-if="!samplePending" name="sparkles" :size="14" />
        {{ samplePending ? '正在生成示例回答…' : '生成 AI 示例回答' }}
      </button>
    </div>

    <div class="reanswer-actions">
      <button
        class="btn ghost reanswer-btn"
        type="button"
        :disabled="sampleDisabled"
        @click="emit('reanswer')"
      >
        <IconGlyph name="refresh-cw" :size="14" />
        重答本题
      </button>
      <button
        v-if="evaluation.sampleAnswer"
        class="btn primary reanswer-btn"
        type="button"
        :disabled="sampleDisabled"
        @click="emit('reanswer', evaluation.sampleAnswer)"
      >
        <IconGlyph name="sparkles" :size="14" />
        用示例回答重答
      </button>
    </div>
  </article>
</template>

<style scoped>
.eval-card {
  padding: 18px 20px 20px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--primary);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
}

.eval-head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.eval-source {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12.5px;
  font-weight: 600;
}
.offtopic {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  padding: 3px 9px;
  border: 1px solid #eadcc8;
  border-radius: 999px;
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 12.5px;
}

.eval-question {
  margin: 12px 0 0;
  padding: 8px 11px;
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  word-break: break-word;
}

.leak-block,
.feedback-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}
.block-label {
  margin: 0 0 6px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}
.leak-list {
  margin: 0;
  padding-left: 1.3em;
}
.leak-list li {
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text-secondary);
  word-break: break-word;
}
.feedback-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
}

.sample-actions {
  margin-top: 14px;
}
.reanswer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}
.reanswer-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.sample-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.sample-block {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--primary-faint);
}
.sample-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.sample-label {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 0;
  color: var(--primary);
}
.sample-retry {
  flex: none;
  padding: 0;
  border: none;
  background: none;
  color: var(--primary);
  font-size: 12px;
  cursor: pointer;
}
.sample-retry:disabled {
  color: var(--text-tertiary);
  cursor: default;
}
.sample-text {
  margin: 6px 0 0;
  font-size: 14px;
  line-height: 1.75;
  color: var(--text);
  word-break: break-word;
  white-space: pre-wrap;
}

@media (max-width: 620px) {
  .offtopic {
    margin-left: 0;
  }
}
</style>
