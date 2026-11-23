<script setup lang="ts">
/**
 * AI 模拟面试页。
 *
 * 左侧是五个步骤 + 最近面试，右侧随步骤切换：
 *   1 确认简历 → 2 选择面试场景 → 3 生成问题包 → 4 选择面试方式 → 5 面试 / 清单 / 复盘
 *
 * 顺序由 canGo 控制：没有场景不出题，没有题包不选方式，没有方式不进房间。
 * 最近面试是独立只读弹层，不参与步骤流转，也不改写当前线程与题包。
 *
 * 所有状态由 stores/interview.ts 管；页面只负责步骤导航与布局。
 */

import { computed, onMounted, ref, watch } from 'vue'

import type {
  Anchor,
  InterviewFocus,
  PackFocus,
  PackScene,
  FollowDepth,
  ResumeProfile,
  TokenUsage,
  UseMode,
} from '@/api/interview'
import { useInterviewStore } from '@/stores/interview'
import { useResumeStore } from '@/stores/resume'
import { message } from '@/utils/feedback'
import { formatDateTime, formatTokenCount, usageTitle } from '@/utils/interview'
import {
  getPack,
  getProfile,
  getSession,
  putSession,
  type SessionRecord,
} from '@/utils/interviewDb'
import ScenePicker from '@/components/interview/ScenePicker.vue'
import HistoryDetail from '@/components/interview/HistoryDetail.vue'
import HistoryList from '@/components/interview/HistoryList.vue'
import InterviewRoom from '@/components/interview/InterviewRoom.vue'
import ModePicker from '@/components/interview/ModePicker.vue'
import PackList from '@/components/interview/PackList.vue'
import PackReview from '@/components/interview/PackReview.vue'
import ProfileReview from '@/components/interview/ProfileReview.vue'
import IconGlyph from '@/components/IconGlyph.vue'

const emit = defineEmits<{ navigate: [page: 'editor'] }>()

const store = useInterviewStore()
const resumeStore = useResumeStore()

const step = ref(1)
const useMode = ref<UseMode>('dialog')
/** 第 4 步必须点过开始，才允许进入第 5 步。 */
const modeConfirmed = ref(false)
/** 上一次出题失败的原因；停在第 2 步持续展示，避免只看到一闪而过的提示。 */
const genError = ref('')

/** 最近面试的独立浏览视图；不写入当前面试状态，也不切换步骤。 */
const historyView = ref<{ session: SessionRecord; profile: ResumeProfile | null } | null>(
  null,
)
const historyLoading = ref(false)

/** 只有拿到当前题（或已结束且有复盘）的线程才允许进入第 5 步。 */
const canResume = computed(
  () =>
    Boolean(store.threadId) &&
    !store.expired &&
    (store.phase === 'finished' || Boolean(store.question?.text)),
)
const inInterview = computed(
  () =>
    canResume.value &&
    ['interviewing', 'teaching', 'finished'].includes(store.phase),
)

/** 步骤旁只放总数，明细放进 title；没有调用过模型或供应商没回传用量时不占位。 */
function stepUsage(usage: TokenUsage | null) {
  if (!usage || !usage.calls || !usage.totalTokens) return null
  return { tokens: formatTokenCount(usage.totalTokens), title: usageTitle(usage) }
}

const steps = computed(() => [
  { n: 1, label: '确认简历', desc: '画像与证据锚点', usage: stepUsage(store.profileUsage) },
  { n: 2, label: '选择面试场景', desc: '项目或综合' },
  { n: 3, label: '生成问题包', desc: '确认题量与追问', usage: stepUsage(store.packUsage) },
  { n: 4, label: '选择面试方式', desc: '对话或清单' },
  {
    n: 5,
    label: store.reviewSession
      ? store.reviewSession.useMode === 'checklist'
        ? '清单回看'
        : '面试回看'
      : inInterview.value
        ? '对话面试'
        : useMode.value === 'checklist'
          ? '清单自测'
          : '对话面试',
    desc: store.reviewSession
      ? '只读查看历史记录'
      : inInterview.value
        ? '作答、讲解与复盘'
        : useMode.value === 'checklist'
          ? '筛选与展开参考答案'
          : '开始作答',
    usage: stepUsage(store.roomUsage),
  },
])

const hasResume = computed(() => resumeStore.resume.length > 0)
const profileRecord = computed(() => store.profileRecord)
const packRecord = computed(() => store.packRecord)

/** 对话面试与清单自测共用第 3 步生成的问题包。 */
const activeCards = computed(() => packRecord.value?.cards ?? null)
const activeWarnings = computed(() => packRecord.value?.warnings ?? [])
const activeScene = computed<PackScene>(() =>
  packRecord.value?.scene === 'comprehensive' ? 'comprehensive' : 'project',
)
const activeFocus = computed<PackFocus>(() => packRecord.value?.focus ?? 'balanced')
const activeSeen = computed(() => {
  const record = packRecord.value
  if (!record) return []
  return useMode.value === 'checklist'
    ? (record.checklistSeenCardIds ?? [])
    : record.seenCardIds
})

const historyItems = computed(() => {
  const active = store.activeSession
  const finished = store.finishedSessions
  return active ? [active, ...finished] : finished
})

const inProgress = computed(
  () =>
    canResume.value &&
    (store.phase === 'interviewing' || store.phase === 'teaching'),
)

const contentInitial = computed(() => {
  const pack = packRecord.value
  if (!pack || store.packStale) return null
  return {
    scene: (pack.scene === 'comprehensive' ? 'comprehensive' : 'project') as PackScene,
    followDepth: pack.followDepth,
    focus: pack.focus ?? 'balanced',
    projectIds: [...pack.projectIds],
  }
})

const interviewHint = computed(() => {
  if (!packRecord.value) return ''
  if (store.expired) {
    return '这场对话面试的服务端记录已过期，无法继续作答；题目与追问仍可查看。'
  }
  if (store.packStale) {
    return '简历画像在出题后修改过，本场仍使用开始时的画像；想要新题请重新生成。'
  }
  return ''
})

function canGo(n: number): boolean {
  if (
    store.streaming ||
    store.generating ||
    store.analyzing ||
    store.creatingThread
  ) {
    return n === step.value
  }
  // 画像改过以后旧题包作废，出题之后的所有步骤都锁住，必须先在当前步骤重新生成。
  if (store.packStale && n >= 3) return false
  if (n === 1) return true
  if (n === 2) return Boolean(profileRecord.value)
  if (n === 3) return Boolean(profileRecord.value && packRecord.value)
  if (n === 4) return Boolean(profileRecord.value && packRecord.value)
  if (n === 5) {
    if (store.reviewSession) return true
    if (!packRecord.value) return false
    if (inInterview.value || store.expired) return true
    return modeConfirmed.value && useMode.value === 'checklist'
  }
  return false
}

function go(n: number) {
  if (!canGo(n)) return
  step.value = n
}

async function onAnalyze() {
  await store.analyze()
}

async function onUseLatest() {
  await store.useLatestProfile()
  step.value = 1
}

async function onSaveProfile(
  profile: ResumeProfile,
  anchors: Anchor[],
  usage: TokenUsage | null,
) {
  await store.saveProfile(profile, anchors, usage)
  genError.value = ''
  step.value = 2
}

async function onGenerate(options: {
  scene: PackScene
  followDepth: FollowDepth | null
  focus: InterviewFocus | null
  projectIds: string[]
}) {
  genError.value = ''
  const ok = await store.generate(options)
  if (ok) {
    useMode.value = store.packRecord?.useMode ?? 'dialog'
    modeConfirmed.value = false
    step.value = 3
    return
  }
  genError.value = store.error || '问题包生成失败，请重试'
}

async function onSelectMode(mode: UseMode) {
  useMode.value = mode
  await store.setUseMode(mode)
}

async function onStartMode() {
  if (!packRecord.value) return
  // 已有可恢复的对话线程：只回到面谈室，不重新建场（建场会收尾旧线程）。
  if (inInterview.value) {
    modeConfirmed.value = true
    step.value = 5
    return
  }
  if (useMode.value === 'checklist') {
    if (store.packStale) {
      message.warning('简历画像已修改，请重新生成问题包')
      return
    }
    const ok = await store.openChecklist()
    if (ok) {
      modeConfirmed.value = true
      step.value = 5
    }
    return
  }
  const ok = await store.startInterview()
  if (ok) {
    modeConfirmed.value = true
    step.value = 5
  }
}

async function onStartFromPack() {
  const ok = await store.startInterview()
  if (ok) {
    modeConfirmed.value = true
    step.value = 5
  }
}

function onRestart() {
  store.backToChoosing()
  modeConfirmed.value = false
  step.value = 2
}

function onPackBack() {
  store.backToChoosing()
  modeConfirmed.value = false
  step.value = 2
}

function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/** 浏览最近面试：只在弹层里读快照，不改当前步骤、题包与线程。 */
async function onOpenHistory(threadId: string) {
  if (store.streaming || historyLoading.value) return
  historyLoading.value = true
  try {
    const session = await getSession(threadId).catch(() => null)
    if (!session) {
      message.warning('这条面试记录已经不存在')
      return
    }
    const pack = await getPack(session.packId).catch(() => null)
    const profile = pack?.resumeFingerprint
      ? await getProfile(pack.resumeFingerprint).catch(() => null)
      : null
    historyView.value = { session, profile: profile?.profile ?? null }
  } finally {
    historyLoading.value = false
  }
}

function closeHistoryView() {
  historyView.value = null
}

async function onHistorySeen(cardId: string) {
  const view = historyView.value
  if (!view) return
  const seen = view.session.checklistSeenCardIds ?? []
  if (seen.includes(cardId)) return
  view.session.checklistSeenCardIds = [...seen, cardId]
  await putSession(plain(view.session)).catch(() => undefined)
}

function onCloseReview() {
  store.closeHistoryReview()
  if (store.packStale) {
    modeConfirmed.value = false
    step.value = 2
    return
  }
  if (canResume.value) {
    useMode.value = 'dialog'
    step.value = 5
    return
  }
  if (store.packRecord?.useMode === 'checklist' && store.checklistSessionId) {
    useMode.value = 'checklist'
    modeConfirmed.value = true
    step.value = 5
    return
  }
  step.value = store.packRecord ? 4 : 2
}

onMounted(async () => {
  await store.init()
  await store.syncResume()
  if (packRecord.value) useMode.value = packRecord.value.useMode
  if (store.packStale) {
    // 画像与旧题包对不上：停在场景步骤，先按当前画像重新生成。
    step.value = 2
  } else if (inInterview.value) {
    modeConfirmed.value = true
    step.value = 5
  } else if (packRecord.value?.useMode === 'checklist' && store.checklistSessionId) {
    // 已经进入过清单：刷新后直接回到清单内容，而不是退回方式选择。
    modeConfirmed.value = true
    step.value = 5
  } else if (packRecord.value) {
    // 题包已生成但还没开始：停在第 4 步选方式。
    step.value = 4
  } else {
    step.value = 1
  }
})

watch(
  () => store.phase,
  () => {
    if (inInterview.value && packRecord.value) {
      modeConfirmed.value = true
      step.value = 5
    }
  },
)
</script>

<template>
  <div class="interview-page">
    <div class="page-inner">
      <header class="page-head">
        <div class="head-copy">
          <span class="eyebrow">AI 模拟面试</span>
          <h1 class="page-title">把简历上的项目，先 AI 模拟面试一遍</h1>
        </div>
      </header>

      <div class="layout">
        <aside class="rail">
          <nav class="steps" aria-label="面试步骤">
            <button
              v-for="item in steps"
              :key="item.n"
              type="button"
              class="step"
              :class="{ active: step === item.n, done: step > item.n }"
              :disabled="!canGo(item.n)"
              @click="go(item.n)"
            >
              <span class="step-num">
                <IconGlyph v-if="step > item.n" name="check" :size="12" />
                <template v-else>{{ item.n }}</template>
              </span>
              <span class="step-text">
                <span class="step-label-row">
                  <span class="step-label">{{ item.label }}</span>
                  <span v-if="item.usage" class="step-usage" :title="item.usage.title">
                    {{ item.usage.tokens }} tokens
                  </span>
                </span>
                <span class="step-desc">{{ item.desc }}</span>
              </span>
            </button>
          </nav>

          <HistoryList
            :items="historyItems"
            :current-id="store.activeHistoryId"
            :disabled="store.streaming || historyLoading"
            @open="onOpenHistory"
          />
        </aside>

        <main class="main">
          <div v-if="!hasResume" class="state-card">
            <span class="state-icon">
              <IconGlyph name="file-text" :size="22" />
            </span>
            <h2>还没有简历内容</h2>
            <p>
              模拟面试完全基于你的简历出题。先去「编辑简历」导入或填写内容，再回来生成画像。
            </p>
            <button class="btn primary" type="button" @click="emit('navigate', 'editor')">
              去编辑简历
              <IconGlyph name="arrow-right" :size="15" />
            </button>
          </div>

          <template v-else>
            <div v-if="inProgress && step !== 5" class="banner">
              <span class="banner-text">
                有一场面试正在进行（第 {{ store.question?.index ?? 1 }} /
                {{ store.question?.total ?? 0 }} 题），离开不会中断服务端进度。
              </span>
              <button class="banner-btn" type="button" @click="step = 5">继续面试</button>
            </div>

            <div v-if="step === 5 && interviewHint && !store.reviewSession" class="banner warn">
              <IconGlyph name="info" :size="15" />
              <span class="banner-text">{{ interviewHint }}</span>
              <button class="banner-btn" type="button" @click="onPackBack">重新出题</button>
            </div>

            <div v-if="(step === 3 || step === 4) && store.packStale" class="banner warn">
              <IconGlyph name="info" :size="15" />
              <span class="banner-text">简历画像已修改，这份问题包已作废，请重新生成。</span>
              <button class="banner-btn" type="button" @click="step = 2">重新生成</button>
            </div>

            <div v-if="store.packStale && step === 2" class="banner warn">
              <IconGlyph name="info" :size="15" />
              <span class="banner-text">简历画像已修改，旧问题包作废。请按当前画像重新生成。</span>
            </div>

            <!-- 1 确认简历 -->
            <template v-if="step === 1">
              <div v-if="store.analyzing" class="state-card analyzing">
                <span class="spinner-lg" aria-hidden="true"></span>
                <h2>正在读你的简历</h2>
                <p>抽取方向、技术栈、项目与可追问的原文证据，通常需要十几秒。</p>
              </div>

              <ProfileReview
                v-else-if="profileRecord"
                :key="profileRecord.editedAt"
                :record="profileRecord"
                :analyzing="store.analyzing"
                @analyze="onAnalyze"
                @save="onSaveProfile"
              />

              <div v-else class="state-card">
                <span class="state-icon">
                  <IconGlyph name="scan-line" :size="22" />
                </span>
                <h2>先让 AI 读一遍简历</h2>
                <p>
                  只提取求职方向、技术栈、项目，以及可以被追问的原文句子。不改写简历，也不会把简历内容发到其它地方。
                </p>
                <div class="state-actions">
                  <button class="btn primary" type="button" @click="onAnalyze">
                    <IconGlyph name="sparkles" :size="15" />
                    开始分析简历
                  </button>
                  <button v-if="store.latest" class="btn ghost" type="button" @click="onUseLatest">
                    沿用上次画像（{{ formatDateTime(store.latest?.editedAt) }}）
                  </button>
                </div>
                <p v-if="store.latest" class="state-hint">
                  上次画像可能来自更早版本的简历。如果简历改过，请重新分析。
                </p>
              </div>
            </template>

            <!-- 2 选择面试场景 -->
            <ScenePicker
              v-else-if="step === 2 && profileRecord"
              :profile="profileRecord.profile"
              :generating="store.generating"
              :error="genError"
              :initial="contentInitial"
              @back="step = 1"
              @generate="onGenerate"
            />

            <!-- 3 生成问题包 -->
            <template v-else-if="step === 3">
              <PackReview
                v-if="packRecord"
                :cards="packRecord.cards"
                :focus="packRecord.focus"
                :warnings="packRecord.warnings"
                :profile="profileRecord?.profile ?? null"
                :rewrite-follow-up="store.rewriteFollowUp"
                :add-follow-up="store.addFollowUp"
                :delete-follow-up="store.deleteFollowUp"
                @back="step = 2"
                @next="go(4)"
              />
              <div v-else class="state-card">
                <span class="state-icon">
                  <IconGlyph name="layout-list" :size="22" />
                </span>
                <h2>还没有问题包</h2>
                <p>先选择面试场景，再生成问题包。</p>
                <button class="btn primary" type="button" @click="step = 2">
                  去选择场景
                  <IconGlyph name="arrow-right" :size="15" />
                </button>
              </div>
            </template>

            <!-- 4 选择面试方式 -->
            <template v-else-if="step === 4">
              <ModePicker
                v-if="packRecord"
                :use-mode="useMode"
                :starting="store.creatingThread"
                :has-thread="inInterview"
                :finished="store.phase === 'finished'"
                @select="onSelectMode"
                @back="step = 3"
                @start="onStartMode"
              />
              <div v-else class="state-card">
                <span class="state-icon">
                  <IconGlyph name="compass" :size="22" />
                </span>
                <h2>还没有问题包</h2>
                <p>先选择面试场景并生成问题包。</p>
                <button class="btn primary" type="button" @click="step = 2">
                  去选择场景
                  <IconGlyph name="arrow-right" :size="15" />
                </button>
              </div>
            </template>

            <!-- 5 对话面试 / 清单自测 / 最近面试回看 -->
            <template v-else-if="step === 5">
              <HistoryDetail
                v-if="store.reviewSession"
                :session="store.reviewSession"
                :profile="profileRecord?.profile ?? null"
                @close="onCloseReview"
                @seen="store.markReviewSeen"
              />
              <InterviewRoom
                v-else-if="canResume"
                @restart="onRestart"
              />
              <PackList
                v-else-if="activeCards"
                :cards="activeCards"
                :warnings="activeWarnings"
                :scene="activeScene"
                :focus="activeFocus"
                :profile="profileRecord?.profile ?? null"
                :seen-card-ids="activeSeen"
                :mode="useMode"
                :startable="useMode === 'dialog' && Boolean(profileRecord)"
                :starting="store.creatingThread"
                :generating-card-ids="store.answerGeneratingCardIds"
                :generating-follow-ups-card-ids="store.followUpsGeneratingCardIds"
                :rewrite-follow-up="store.rewriteFollowUp"
                :add-follow-up="store.addFollowUp"
                :delete-follow-up="store.deleteFollowUp"
                @seen="store.markSeen"
                @generate-answer="store.generateAnswer"
                @generate-follow-ups="store.generateFollowUpAnswers"
                @start="onStartFromPack"
                @back="onPackBack"
              />
              <div v-else class="state-card">
                <span class="state-icon">
                  <IconGlyph name="compass" :size="22" />
                </span>
                <h2>还没有面试题目</h2>
                <p>先选择面试场景并生成问题包，再开始作答。</p>
                <button class="btn primary" type="button" @click="step = 2">
                  去选择场景
                  <IconGlyph name="arrow-right" :size="15" />
                </button>
              </div>
            </template>
          </template>
        </main>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="historyView" class="history-modal" @click.self="closeHistoryView">
        <div class="history-panel" role="dialog" aria-modal="true" aria-label="面试记录">
          <header class="history-panel-head">
            <h2 class="history-panel-title">面试记录</h2>
            <button
              class="history-close"
              type="button"
              aria-label="关闭面试记录"
              @click="closeHistoryView"
            >
              <IconGlyph name="x" :size="16" />
            </button>
          </header>
          <div class="history-panel-body">
            <HistoryDetail
              :session="historyView.session"
              :profile="historyView.profile"
              dismiss-label="关闭"
              @close="closeHistoryView"
              @seen="onHistorySeen"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.interview-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: var(--app-bg);
}
.page-inner {
  max-width: 1180px;
  margin: 0 auto;
  padding: 34px 30px 72px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 32px;
  padding-bottom: 26px;
}
.head-copy {
  max-width: 720px;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--primary);
}
.eyebrow::before {
  content: '';
  width: 16px;
  height: 1px;
  background: currentColor;
  opacity: 0.55;
}
.page-title {
  margin: 12px 0 0;
  font-family: var(--font-sans);
  font-size: 34px;
  font-weight: 600;
  line-height: 1.18;
  letter-spacing: -0.03em;
  color: var(--text);
}
.layout {
  display: flex;
  align-items: flex-start;
  gap: 30px;
}
.rail {
  position: sticky;
  top: 24px;
  flex: none;
  width: 240px;
}
.steps {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--panel-bg);
  box-shadow: var(--shadow-xs);
}
.step {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  width: 100%;
  padding: 10px 11px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--dur-2) var(--ease),
    box-shadow var(--dur-2) var(--ease);
}
.step:hover:not(:disabled) {
  background: var(--surface-soft);
}
.step:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.step.active {
  background: var(--primary-faint);
  box-shadow: inset 2px 0 0 var(--primary);
}
.step-num {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 23px;
  height: 23px;
  margin-top: 1px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: var(--panel-bg);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
  transition:
    background-color var(--dur-2) var(--ease),
    border-color var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease);
}
.step.done .step-num {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}
.step.active .step-num {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--panel-bg);
}
.step-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.step-label-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.step-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}
.step-usage {
  flex: none;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 11px;
  line-height: 17px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  cursor: help;
}
.step.active .step-usage {
  background: var(--panel-bg);
  color: var(--text-secondary);
}
.step.active .step-label {
  color: var(--text);
}
.step-desc {
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--text-tertiary);
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border: 1px solid var(--primary-line);
  border-radius: var(--radius-md);
  background: var(--primary-faint);
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.65;
}
.banner.warn {
  border-color: rgba(143, 97, 40, 0.24);
  background: var(--warning-soft);
  color: var(--warning);
}
.banner.warn svg {
  flex: none;
  margin-top: 1px;
}
.banner-text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}
.banner-list {
  flex: 1;
  min-width: 0;
}
.banner-list p {
  margin: 0 0 3px;
  word-break: break-word;
}
.banner-list p:last-child {
  margin-bottom: 0;
}
.banner-btn {
  flex: none;
  height: 26px;
  padding: 0 10px;
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font-size: 12.5px;
  opacity: 0.85;
  cursor: pointer;
  white-space: nowrap;
}
.banner-btn:hover {
  opacity: 1;
}

.state-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 34px 32px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--panel-bg);
  box-shadow: var(--shadow-paper);
}
.state-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--primary-soft);
  color: var(--primary);
}
.state-card h2 {
  margin: 4px 0 0;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.state-card p {
  margin: 0;
  max-width: 640px;
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-secondary);
}
.state-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.state-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
.analyzing {
  align-items: center;
  text-align: center;
}
.analyzing p {
  text-align: center;
}
.spinner-lg {
  width: 28px;
  height: 28px;
  border: 3px solid var(--primary-soft);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 940px) {
  .page-head {
    flex-direction: column;
    gap: 16px;
  }
  .layout {
    flex-direction: column;
    align-items: stretch;
    gap: 18px;
  }
  .rail {
    position: static;
    width: 100%;
  }
  .steps {
    flex-direction: row;
    overflow-x: auto;
  }
  .step {
    flex: 1;
    min-width: 140px;
  }
  .step-desc {
    display: none;
  }
}

@media (max-width: 640px) {
  .page-inner {
    padding: 22px 16px 56px;
  }
  .page-title {
    font-size: 27px;
  }
  .steps {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 2px;
    overflow: visible;
  }
  .step {
    min-width: 0;
    padding: 9px 10px;
  }
  .step-label {
    font-size: 13px;
  }
  .state-card {
    padding: 24px 20px;
  }
  .banner {
    flex-wrap: wrap;
  }
}

/* 最近面试独立浏览：固定在视口上的只读弹层，不影响当前步骤。 */
.history-modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 32px 24px;
  overflow-y: auto;
  background: rgba(20, 24, 38, 0.46);
  backdrop-filter: blur(3px);
}
.history-panel {
  display: flex;
  flex-direction: column;
  width: min(1040px, 100%);
  max-height: calc(100vh - 64px);
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--app-bg);
  box-shadow: 0 36px 90px -34px rgba(20, 24, 38, 0.5);
}
.history-panel-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--panel-bg);
}
.history-panel-title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text);
}
.history-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.history-close:hover {
  background: var(--surface-soft);
  color: var(--text);
}
.history-panel-body {
  flex: 1;
  min-height: 0;
  padding: 22px 24px 26px;
  overflow-y: auto;
}

@media (max-width: 720px) {
  .history-modal {
    padding: 0;
  }
  .history-panel {
    width: 100%;
    height: 100vh;
    max-height: none;
    border: none;
    border-radius: 0;
  }
  .history-panel-body {
    padding: 18px 16px 24px;
  }
}
</style>
