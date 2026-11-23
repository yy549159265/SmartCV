<script setup lang="ts">
/**
 * 第 2 步：先确定出题场景与范围。
 *
 * 项目面试：选一个项目，可加考察方向与追问强度。
 * 综合面试：动机 / 规划 / 薪资 / 稳定性 / 真实性，不使用考察方向与追问强度。
 * 对话还是清单，等题包生成后再选。
 */

import { computed, ref } from 'vue'

import type {
  FollowDepth,
  InterviewFocus,
  PackFocus,
  PackScene,
  ResumeProfile,
} from '@/api/interview'
import { message } from '@/utils/feedback'
import IconGlyph from '@/components/IconGlyph.vue'

const props = defineProps<{
  profile: ResumeProfile
  generating?: boolean
  /** 上一次生成失败的原因；有值时在底部持续展示，而不是只弹一条会自动消失的提示。 */
  error?: string
  initial?: {
    scene: PackScene
    followDepth: FollowDepth | null
    focus?: PackFocus
    projectIds: string[]
  } | null
}>()

const emit = defineEmits<{
  back: []
  generate: [
    options: {
      scene: PackScene
      followDepth: FollowDepth | null
      focus: InterviewFocus | null
      projectIds: string[]
    },
  ]
}>()

const FOCUS_OPTIONS: {
  value: InterviewFocus
  label: string
  desc: string
}[] = [
  { value: 'business', label: '业务场景', desc: '为什么做、谁在用、业务链路与指标' },
  { value: 'tech', label: '实现细节', desc: '具体怎么做：接口、数据、并发、异常边界' },
  { value: 'architecture', label: '架构设计', desc: '系统怎么搭：拆分、容量、扩展、容灾、成本' },
  { value: 'review', label: '复盘决策', desc: '方案取舍、问题解决、效果验证与个人贡献' },
]

const FOCUS_VALUES = FOCUS_OPTIONS.map((option) => option.value)

const scene = ref<PackScene>(
  props.initial?.scene === 'comprehensive' ? 'comprehensive' : 'project',
)
const followDepth = ref<FollowDepth>(props.initial?.followDepth ?? 'normal')
// 考察方向可选：没有默认选中项，不选时传 null，生成请求按 balanced 混合出题。
// 旧题包里的 balanced 同样视为未选择。
const focus = ref<InterviewFocus | null>(
  props.initial?.focus && FOCUS_VALUES.includes(props.initial.focus as InterviewFocus)
    ? (props.initial.focus as InterviewFocus)
    : null,
)
const selectedProjects = ref<string[]>(
  (props.initial?.projectIds ?? []).filter(Boolean).slice(0, 1),
)

if (!selectedProjects.value.length && props.profile.projects[0]) {
  selectedProjects.value = [props.profile.projects[0].id]
}

const projects = computed(() => props.profile.projects)
const canGenerate = computed(
  () => scene.value === 'comprehensive' || selectedProjects.value.length === 1,
)

function toggleProject(id: string) {
  selectedProjects.value = [id]
}

/** 方向可选：再次点击已选项即取消，回到默认的均衡混合出题。 */
function toggleFocus(value: InterviewFocus) {
  focus.value = focus.value === value ? null : value
}

function submit() {
  if (!canGenerate.value) {
    message.warning('请选择一个项目')
    return
  }
  emit('generate', {
    scene: scene.value,
    followDepth: scene.value === 'project' ? followDepth.value : null,
    focus: scene.value === 'project' ? focus.value : null,
    projectIds: scene.value === 'project' ? [...selectedProjects.value] : [],
  })
}
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <h2 class="panel-title">选择面试场景</h2>
    </header>

    <div class="segments" role="group" aria-label="面试场景">
      <button
        type="button"
        class="segment"
        :class="{ on: scene === 'project' }"
        @click="scene = 'project'"
      >
        <span class="segment-title">项目面试</span>
        <span class="segment-desc">围绕一个项目，从背景挖到个人贡献</span>
      </button>
      <button
        type="button"
        class="segment"
        :class="{ on: scene === 'comprehensive' }"
        @click="scene = 'comprehensive'"
      >
        <span class="segment-title">综合面试</span>
        <span class="segment-desc">动机、职业规划、薪资期待、稳定性与真实性</span>
      </button>
    </div>

    <div v-if="scene === 'project'" class="block">
      <div class="block-head">
        <h3 class="block-title">选择项目</h3>
        <span class="block-count">单选</span>
      </div>
      <p v-if="!projects.length" class="block-empty">
        画像里没有项目。可以返回确认页补充项目，或改用综合面试。
      </p>
      <div v-else class="option-list">
        <button
          v-for="project in projects"
          :key="project.id"
          type="button"
          class="option-row"
          :class="{ selected: selectedProjects.includes(project.id) }"
          @click="toggleProject(project.id)"
        >
          <span class="option-mark" :class="{ on: selectedProjects.includes(project.id) }">
            <IconGlyph v-if="selectedProjects.includes(project.id)" name="check" :size="13" />
          </span>
          <span class="option-body">
            <span class="option-title">{{ project.name }}</span>
            <span class="option-desc">{{ project.role || '未填写角色' }}</span>
            <span v-if="project.techStack.length" class="option-tags">
              <span v-for="tech in project.techStack" :key="tech" class="tag">{{ tech }}</span>
            </span>
          </span>
        </button>
      </div>
    </div>

    <div v-if="scene === 'project'" class="block">
      <div class="block-head">
        <h3 class="block-title">考察方向</h3>
        <span class="block-count">可选</span>
      </div>
      <div class="choice-grid" role="group" aria-label="考察方向">
        <button
          v-for="option in FOCUS_OPTIONS"
          :key="option.value"
          type="button"
          class="choice-item"
          :class="{ on: focus === option.value }"
          :aria-pressed="focus === option.value"
          @click="toggleFocus(option.value)"
        >
          <span class="choice-title">{{ option.label }}</span>
          <span class="choice-desc">{{ option.desc }}</span>
        </button>
      </div>
    </div>

    <div v-if="scene === 'project'" class="block">
      <div class="block-head">
        <h3 class="block-title">面试强度</h3>
      </div>
      <div class="choice-grid" role="group" aria-label="面试强度">
        <button
          type="button"
          class="choice-item"
          :class="{ on: followDepth === 'normal' }"
          :aria-pressed="followDepth === 'normal'"
          @click="followDepth = 'normal'"
        >
          <span class="choice-title">
            常规
            <span class="choice-default">默认</span>
          </span>
          <span class="choice-desc">正常技术交流，按回答质量继续追问</span>
        </button>
        <button
          type="button"
          class="choice-item"
          :class="{ on: followDepth === 'deep' }"
          :aria-pressed="followDepth === 'deep'"
          @click="followDepth = 'deep'"
        >
          <span class="choice-title">深度追问</span>
          <span class="choice-desc">追问更直接，更关注数据口径、方案依据与个人贡献</span>
        </button>
      </div>
    </div>

    <div v-if="error" class="gen-fail" role="alert">
      <IconGlyph name="info" :size="16" />
      <p class="gen-fail-text">{{ error }}</p>
    </div>

    <footer class="panel-foot">
      <button class="btn ghost" type="button" :disabled="generating" @click="emit('back')">
        <IconGlyph name="chevron-left" :size="15" />
        上一步
      </button>
      <button
        class="btn primary"
        type="button"
        :disabled="!canGenerate || generating"
        @click="submit"
      >
        <span v-if="generating" class="spinner" aria-hidden="true"></span>
        {{ generating ? '正在生成问题包…' : error ? '重新生成问题包' : '生成问题包' }}
        <IconGlyph v-if="!generating" name="arrow-right" :size="15" />
      </button>
    </footer>
  </section>
</template>

<style scoped>
.panel {
  padding: 26px 30px 30px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-paper);
}
.panel-title {
  margin: 0 0 18px;
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.segments {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.segment {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.segment:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
}
.segment.on {
  border-color: var(--primary);
  background: var(--primary-faint);
  box-shadow: 0 0 0 1px var(--primary);
}
.segment-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.segment-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.block {
  margin-top: 24px;
}
.block-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
.block-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.block-count {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.block-empty {
  margin: 0;
  padding: 14px 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text-tertiary);
}

.choice-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.choice-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.choice-item:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
}
.choice-item.on {
  border-color: var(--primary);
  background: var(--primary-faint);
  box-shadow: 0 0 0 1px var(--primary);
}
.choice-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.choice-default {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 18px;
}
.choice-desc {
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-secondary);
  word-break: break-word;
}

.option-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.option-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  padding: 13px 15px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.option-row:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
}
.option-row.selected {
  border-color: var(--primary);
  background: var(--primary-faint);
}
.option-mark {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: var(--panel-bg);
  color: #fff;
}
.option-mark.on {
  border-color: var(--primary);
  background: var(--primary);
}
.option-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.option-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
  word-break: break-word;
}
.option-desc {
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-tertiary);
  word-break: break-word;
}
.option-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 2px;
}
.tag {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-soft);
  font-size: 12px;
  line-height: 18px;
  color: var(--text-secondary);
}

.gen-fail {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 24px;
  padding: 12px 14px;
  border: 1px solid rgba(143, 97, 40, 0.28);
  border-radius: var(--radius-md);
  background: var(--warning-soft);
  color: var(--warning);
}
.gen-fail svg {
  margin-top: 1px;
}
.gen-fail-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--warning);
  word-break: break-word;
}

.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
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

@media (max-width: 760px) {
  .panel {
    padding: 20px 18px 24px;
  }
  .segments,
  .choice-grid {
    grid-template-columns: 1fr;
  }
  .panel-foot {
    flex-direction: column-reverse;
    align-items: stretch;
  }
  .btn {
    justify-content: center;
  }
}
</style>
