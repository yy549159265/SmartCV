<script setup lang="ts">
import { computed } from 'vue'
import type { CareerStage } from '@/types/market'

const props = defineProps<{
  stages: CareerStage[]
}>()

/**
 * 阶段名只保留时间。
 * 旧数据可能把「2020.09-2023.06 教育期」整段写进 stage，
 * 这里统一截出时间范围，阶段说明交给 role / focus 展示。
 */
const DATE_RANGE = /^\s*((?:19|20)\d{2}(?:[./-]\d{1,2})?(?:\s*(?:-|–|—|~|至)\s*(?:(?:19|20)\d{2}(?:[./-]\d{1,2})?|至今|现在|今))?)(?=$|[^\d])/

function stageTime(stage: string): string {
  const text = (stage || '').trim()
  const matched = text.match(DATE_RANGE)
  return matched ? matched[1].trim() : text
}

const steps = computed(() =>
  props.stages.map((stage) => ({
    time: stageTime(stage.stage),
    role: stage.role,
    focus: stage.focus,
  })),
)
</script>

<template>
  <div class="career-fishbone">
    <div
      v-for="(step, index) in steps"
      :key="index"
      class="career-step"
      :class="{ dated: step.time }"
    >
      <div class="step-head">
        <span v-if="step.time" class="step-time">{{ step.time }}</span>
        <span v-if="step.role" class="step-role">{{ step.role }}</span>
      </div>
      <p v-if="step.focus" class="step-focus">{{ step.focus }}</p>
    </div>
  </div>
</template>

<style scoped>
/* 与技术矩阵一致：竖向中轴、阶段节点、斜刺连接正文。 */
.career-fishbone {
  position: relative;
  padding-left: 18px;
}
.career-fishbone::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 4px;
  bottom: 6px;
  width: 2px;
  border-radius: 2px;
  background: linear-gradient(180deg, var(--border-strong), var(--primary-soft));
}
.career-step {
  position: relative;
  padding-bottom: 12px;
}
.career-step:last-child {
  padding-bottom: 0;
}
/* 中轴上的阶段节点；有时间的阶段用品牌色标记。 */
.career-step::before {
  content: '';
  position: absolute;
  left: -16px;
  top: 3px;
  width: 9px;
  height: 9px;
  border: 2px solid var(--border-strong);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.92);
}
.career-step.dated::before {
  border-color: var(--primary);
}
/* 从节点斜向连到阶段文字，形成鱼骨刺。 */
.career-step::after {
  content: '';
  position: absolute;
  left: -7px;
  top: 8px;
  width: 7px;
  height: 1px;
  background: var(--border-strong);
  transform: rotate(-20deg);
  transform-origin: right center;
}
.step-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
}
.step-time {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.step-role {
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.step-focus {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.65;
  /* 阶段说明完整显示，不省略、不裁切。 */
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
