<script setup lang="ts">
/**
 * 讲解模式：当前题不答，改成和教练讨论。
 * 可以继续追问，也可以随时「返回作答」回答同一道题。
 */

import { nextTick, ref, watch } from 'vue'

import type { FollowLevel, QuestionCard, TeachingTurn } from '@/api/interview'
import { asrClock } from '@/composables/useAsrSettings'
import { useSpeechDictation } from '@/composables/useSpeechDictation'
import { LEVEL_LABEL, dimensionLabel } from '@/utils/interview'
import { renderMarkdown } from '@/utils/markdown'
import IconGlyph from '@/components/IconGlyph.vue'
import MicButton from '@/components/interview/MicButton.vue'

const props = defineProps<{
  card: QuestionCard | null
  question: string
  level: FollowLevel | ''
  turns: TeachingTurn[]
  stream: string
  streaming: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  return: []
  skip: []
}>()

const draft = ref('')
const chatEl = ref<HTMLElement | null>(null)
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
} = useSpeechDictation(draft)

watch(
  () => [props.turns.length, props.stream],
  async () => {
    await nextTick()
    const el = chatEl.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

function send() {
  const text = draft.value.trim()
  if (!text || props.streaming) return
  cancelMic()
  draft.value = ''
  emit('send', text)
}

watch(
  () => props.streaming,
  (streaming) => {
    if (streaming) cancelMic()
  },
)

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    send()
  }
}
</script>

<template>
  <section class="teaching">
    <header class="teach-head">
      <div class="head-tags">
        <span class="teach-badge">
          <IconGlyph name="book-open" :size="14" />
          讲解模式
        </span>
        <span v-if="card" class="meta">{{ dimensionLabel(card.dimension) }}</span>
        <span v-if="level" class="meta">{{ LEVEL_LABEL[level] }}</span>
      </div>
    </header>

    <p class="teach-question">{{ question }}</p>

    <div ref="chatEl" class="chat">
      <div v-for="(turn, index) in turns" :key="index" class="bubble-row" :class="turn.role">
        <span v-if="turn.role === 'teacher'" class="avatar">AI</span>
        <div class="bubble md-body" v-html="renderMarkdown(turn.content)"></div>
      </div>
      <div v-if="stream" class="bubble-row teacher">
        <span class="avatar">AI</span>
        <div class="bubble md-body streaming" v-html="renderMarkdown(stream)"></div>
      </div>
      <div v-else-if="streaming" class="bubble-row teacher">
        <span class="avatar">AI</span>
        <div class="bubble typing">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>

    <div class="composer">
      <textarea
        v-model="draft"
        class="composer-input"
        rows="2"
        placeholder="继续追问，例如：这里的线程池参数为什么这样设？"
        :disabled="streaming"
        @keydown="onKeydown"
        @beforeinput="stopMic"
      ></textarea>
      <div class="composer-foot">
        <div class="composer-tools">
          <MicButton
            :listening="micListening"
            :supported="micSupported"
            :disabled="streaming"
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
                  : 'Ctrl / ⌘ + Enter 发送'
            }}
          </span>
        </div>
        <button
          class="btn primary"
          type="button"
          :disabled="streaming || micTranscribing || !draft.trim()"
          @click="send"
        >
          发送
        </button>
      </div>
    </div>

    <footer class="teach-actions">
      <button class="btn ghost" type="button" :disabled="streaming" @click="emit('skip')">
        跳过本题
      </button>
      <button class="btn" type="button" :disabled="streaming" @click="emit('return')">
        <IconGlyph name="undo-2" :size="15" />
        返回作答
      </button>
    </footer>
  </section>
</template>

<style scoped>
.teaching {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  overflow: hidden;
}
.teach-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--primary-faint);
}
.head-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.teach-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12.5px;
  font-weight: 600;
}
.meta {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.teach-question {
  margin: 0;
  padding: 14px 18px;
  font-size: 14.5px;
  line-height: 1.7;
  color: var(--text);
  border-bottom: 1px dashed var(--border);
  word-break: break-word;
}

.chat {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 380px;
  min-height: 120px;
  padding: 16px 18px;
  overflow-y: auto;
  background: var(--surface-soft);
}
.bubble-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}
.bubble-row.user {
  justify-content: flex-end;
}
.avatar {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 11.5px;
  font-weight: 600;
}
.bubble {
  max-width: min(86%, 680px);
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel-bg);
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  word-break: break-word;
}
.bubble-row.user .bubble {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}
.bubble.streaming::after {
  content: '';
  display: inline-block;
  width: 2px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--primary);
  animation: blink 1s step-end infinite;
}
.typing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 36px;
}
.typing span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-tertiary);
  animation: bounce 1.2s ease-in-out infinite;
}
.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
@keyframes bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

.composer {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}
.composer-input {
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  field-sizing: content;
  min-height: 52px;
}
.composer-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--focus-ring);
}
.composer-input:disabled {
  background: var(--surface-soft);
  color: var(--text-tertiary);
}
.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.composer-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.composer-hint {
  font-size: 12px;
  color: var(--text-tertiary);
}
.teach-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px 14px;
  border-top: 1px solid var(--border);
  background: var(--panel-bg);
}

@media (max-width: 640px) {
  .bubble {
    max-width: 92%;
  }
  .teach-actions {
    flex-direction: column-reverse;
    align-items: stretch;
  }
  .btn {
    justify-content: center;
  }
}
</style>
