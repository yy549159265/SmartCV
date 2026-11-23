<script setup lang="ts">
import { computed } from 'vue'

import { asrClock, type AsrMode } from '@/composables/useAsrSettings'
import IconGlyph from '@/components/IconGlyph.vue'

const props = withDefaults(
  defineProps<{
    listening: boolean
    supported: boolean
    disabled?: boolean
    /** DeepSeek 模式：录音已结束，正在上传识别。 */
    transcribing?: boolean
    /** DeepSeek 模式：录音期间的声音波形，0~1。 */
    waveform?: number[]
    mode?: AsrMode
    /** 已录音秒数。 */
    elapsed?: number
    maxSeconds?: number
  }>(),
  {
    disabled: false,
    transcribing: false,
    waveform: () => [],
    mode: 'sherpa',
    elapsed: 0,
    maxSeconds: 60,
  },
)

const emit = defineEmits<{ toggle: [] }>()

const deepseek = computed(() => props.mode === 'deepseek')
const bars = computed(() =>
  props.waveform.length ? props.waveform : new Array(14).fill(0.12),
)

const label = computed(() => {
  if (props.transcribing) return '识别中…'
  if (props.listening) {
    return deepseek.value ? `录音中 ${asrClock(props.elapsed)}` : '正在听…'
  }
  return deepseek.value ? '录音识别' : '语音输入'
})

const title = computed(() => {
  if (!props.supported) return '当前浏览器不支持语音输入，请使用 Chrome 或 Edge'
  if (props.transcribing) return '正在上传录音并识别'
  if (props.listening) {
    return deepseek.value
      ? `再点一次结束录音并识别（最长 ${props.maxSeconds} 秒）`
      : '再点一次结束语音输入'
  }
  return deepseek.value
    ? `点击开始录音，最长 ${props.maxSeconds} 秒；结束后上传识别`
    : '语音输入：录音会发送到语音识别服务，识别结果不保存录音'
})

const ariaLabel = computed(() => {
  if (props.transcribing) return '正在识别语音'
  if (props.listening) return deepseek.value ? '结束录音并识别' : '停止语音输入'
  return deepseek.value ? '开始录音识别' : '语音输入'
})

function barHeight(level: number): string {
  return `${Math.max(2, Math.round(Math.min(1, level) * 14))}px`
}
</script>

<template>
  <button
    class="btn ghost sm mic-btn"
    :class="{ listening, transcribing }"
    type="button"
    :disabled="disabled || !supported || transcribing"
    :aria-pressed="listening"
    :aria-label="ariaLabel"
    :title="title"
    @click="emit('toggle')"
  >
    <span v-if="listening && deepseek" class="mic-wave" aria-hidden="true">
      <i v-for="(level, index) in bars" :key="index" :style="{ height: barHeight(level) }"></i>
    </span>
    <span v-else-if="listening" class="mic-dot" aria-hidden="true"></span>
    <span v-else-if="transcribing" class="mic-spin" aria-hidden="true"></span>
    <IconGlyph v-else name="mic" :size="14" />
    {{ label }}
  </button>
</template>

<style scoped>
.mic-btn {
  font-variant-numeric: tabular-nums;
}
.mic-btn.listening,
.mic-btn.listening:hover:not(:disabled),
.mic-btn.transcribing,
.mic-btn.transcribing:hover:not(:disabled) {
  color: var(--primary);
  background: var(--primary-soft);
  font-weight: 600;
}
.mic-btn.transcribing {
  cursor: progress;
}
.mic-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--danger);
  box-shadow: 0 0 0 3px var(--danger-soft);
  animation: mic-blink 1.3s ease-in-out infinite;
}
.mic-wave {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 14px;
}
.mic-wave i {
  width: 2px;
  min-height: 2px;
  border-radius: 1px;
  background: currentColor;
  transition: height 0.08s linear;
}
.mic-spin {
  width: 12px;
  height: 12px;
  border: 2px solid color-mix(in srgb, var(--primary) 28%, transparent);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: mic-spin 0.7s linear infinite;
}
@keyframes mic-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.2;
  }
}
@keyframes mic-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .mic-dot,
  .mic-spin {
    animation: none;
  }
  .mic-wave i {
    transition: none;
  }
}
</style>
