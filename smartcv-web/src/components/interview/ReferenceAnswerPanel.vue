<script setup lang="ts">
/**
 * AI 示范答案：按「回答思路 / 回答内容 / 回答关键点 / 缺少证据 / 补充假设」分区，
 * 整体可折叠。主问题与追问共用同一套展示。
 */

import { computed } from 'vue'

import type { ReferenceAnswer } from '@/api/interview'
import IconGlyph from '@/components/IconGlyph.vue'

const props = withDefaults(
  defineProps<{
    answer: ReferenceAnswer
    /** 追问答案嵌套在追问链里，使用更紧凑的间距。 */
    compact?: boolean
    defaultOpen?: boolean
  }>(),
  { compact: false, defaultOpen: true },
)

/** 连续空行折叠成一个段落间隔，行首尾空白一并去掉。 */
function toParagraphs(text: string): string[] {
  return text
    .split(/\n\s*\n+/)
    .map((paragraph) =>
      paragraph
        .split('\n')
        .map((line) => line.trimEnd())
        .join('\n')
        .trim(),
    )
    .filter(Boolean)
}

const thinkingParagraphs = computed(() => toParagraphs(props.answer.thinking))
const answerParagraphs = computed(() => toParagraphs(props.answer.answer))
</script>

<template>
  <details class="ref-answer" :class="{ compact: props.compact }" :open="props.defaultOpen">
    <summary class="ref-head">
      <span class="ref-badge">AI 示范答案</span>
      <span class="ref-toggle" aria-hidden="true">
        <IconGlyph name="chevron-down" :size="14" />
      </span>
    </summary>

    <div class="ref-body">
      <section v-if="thinkingParagraphs.length" class="ref-block">
        <h5 class="ref-title">回答思路</h5>
        <div class="ref-text">
          <p v-for="(paragraph, index) in thinkingParagraphs" :key="index">{{ paragraph }}</p>
        </div>
      </section>

      <section class="ref-block">
        <h5 class="ref-title">回答内容</h5>
        <div class="ref-text">
          <p v-for="(paragraph, index) in answerParagraphs" :key="index">{{ paragraph }}</p>
        </div>
      </section>

      <section v-if="props.answer.keyPoints.length" class="ref-block">
        <h5 class="ref-title">回答关键点</h5>
        <ul class="ref-list">
          <li v-for="(point, index) in props.answer.keyPoints" :key="index">
            {{ point }}
          </li>
        </ul>
      </section>

      <section v-if="props.answer.missingInfo.length" class="ref-block warn">
        <h5 class="ref-title">缺少证据</h5>
        <ul class="ref-list">
          <li v-for="(item, index) in props.answer.missingInfo" :key="index">
            {{ item }}
          </li>
        </ul>
      </section>

      <section v-if="props.answer.assumptions?.length" class="ref-block">
        <h5 class="ref-title">补充假设</h5>
        <ul class="ref-list">
          <li v-for="(item, index) in props.answer.assumptions" :key="index">
            {{ item }}
          </li>
        </ul>
      </section>
    </div>
  </details>
</template>

<style scoped>
.ref-answer {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  overflow: hidden;
}
.ref-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
  background: var(--surface-soft);
}
.ref-head::-webkit-details-marker {
  display: none;
}
.ref-badge {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 600;
  line-height: 18px;
  white-space: nowrap;
}
.ref-toggle {
  display: inline-flex;
  color: var(--text-tertiary);
  transition: transform 0.16s var(--ease);
}
.ref-answer[open] .ref-toggle {
  transform: rotate(180deg);
}
.ref-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 12px 14px 14px;
}
.compact .ref-body {
  gap: 11px;
  padding: 10px 12px 12px;
}
.ref-title {
  margin: 0 0 5px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-tertiary);
}
.ref-block.warn .ref-title {
  color: var(--warning);
}
.ref-text {
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--text-secondary);
  word-break: break-word;
  white-space: pre-wrap;
}
.ref-text p {
  margin: 0;
}
.ref-text p + p {
  margin-top: 8px;
}
.ref-list {
  margin: 0;
  padding-left: 1.3em;
}
.ref-list li {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  word-break: break-word;
}
.ref-block.warn .ref-list li {
  color: var(--text-secondary);
}
@media (prefers-reduced-motion: reduce) {
  .ref-toggle {
    transition: none;
  }
}
</style>
