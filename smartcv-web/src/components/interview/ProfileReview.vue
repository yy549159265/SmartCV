<script setup lang="ts">
/**
 * 简历画像确认：一份可逐项核对的画像。
 *
 * 项目可改名称 / 角色 / 简介 / 技术栈；技术栈按掌握程度分组校正。
 * 证据锚点可让 AI 按用户思路重写追问方向或类型；原文与引用坐标保持不变，
 * 改写项目描述也不会动到锚点。
 */

import { computed, nextTick, ref, watch } from 'vue'

import { editContent } from '@/api/interview'
import type {
  Anchor,
  AnchorKind,
  Coord,
  ResumeProfile,
  TechLevel,
  TokenUsage,
} from '@/api/interview'
import type { ProfileRecord } from '@/utils/interviewDb'
import { KIND_LABEL, mergeUsage } from '@/utils/interview'
import { dialog, message } from '@/utils/feedback'
import IconGlyph from '@/components/IconGlyph.vue'
import ReferenceBadge from './ReferenceBadge.vue'
import ResumeSourcePanel from './ResumeSourcePanel.vue'

const props = defineProps<{
  record: ProfileRecord
  analyzing?: boolean
}>()

const emit = defineEmits<{
  analyze: []
  /** usage 是本次停留期间锚点改写新增的 token，交给第 1 步累计。 */
  save: [profile: ResumeProfile, anchors: Anchor[], usage: TokenUsage | null]
}>()

const LEVELS: TechLevel[] = ['精通', '熟练', '掌握']
const ANCHOR_KINDS: AnchorKind[] = ['metric', 'architecture', 'tech', 'result', 'contribution']
const ANCHOR_INFO =
  '锚点取自简历原文，出题会围绕这些句子追问；同一项目少于 2 条时不单独展示。'
type TabKey = 'project' | 'tech' | 'anchor'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'project', label: '简历项目' },
  { key: 'tech', label: '技术栈' },
  { key: 'anchor', label: '证据锚点' },
]

function cloneProfile(profile: ResumeProfile): ResumeProfile {
  const copy = JSON.parse(JSON.stringify(profile)) as ResumeProfile
  copy.intro = copy.intro ?? ''
  copy.introRefs = copy.introRefs ?? []
  copy.techStacks = copy.techStacks.map((item) => ({ ...item, refs: item.refs ?? [] }))
  return copy
}

function cloneAnchors(anchors: Anchor[]): Anchor[] {
  return JSON.parse(JSON.stringify(anchors)) as Anchor[]
}

const draft = ref<ResumeProfile>(cloneProfile(props.record.profile))
const draftAnchors = ref<Anchor[]>(cloneAnchors(props.record.anchors))
const activeTab = ref<TabKey>('project')
const projectId = ref('')
const anchorKey = ref('')
const activeKind = ref<AnchorKind | ''>('')
/** 用户删过锚点的分组保持可见，避免 2 条删到 1 条后整组消失。 */
const pinnedAnchorKeys = ref<string[]>([])
const editingAnchorId = ref('')
const anchorInstruction = ref('')
const anchorSaving = ref(false)
const anchorInput = ref<HTMLTextAreaElement | null>(null)
/** 锚点改写是新一次模型调用，保存时并入第 1 步用量。 */
const editUsage = ref<TokenUsage | null>(null)

/** 技术栈按掌握程度分组；三个分类始终展示，空分类也是拖拽目标。 */
const techGroups = computed(() =>
  LEVELS.map((level) => ({
    level,
    items: draft.value.techStacks
      .map((item, index) => ({ item, index }))
      .filter((row) => row.item.level === level),
  })),
)

function refsOf(item: { refs?: Coord[] }): Coord[] {
  return item.refs ?? []
}

const previewOpen = ref(false)
const previewCoords = ref<Coord[]>([])
const previewSeq = ref(0)

function openRefs(coords: Coord[]): void {
  if (!coords.length) return
  previewCoords.value = coords
  previewSeq.value += 1
  previewOpen.value = true
}

const dragIndex = ref<number | null>(null)
const dragOverLevel = ref<TechLevel | ''>('')

function onDragStart(index: number, event: DragEvent): void {
  dragIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(level: TechLevel): void {
  if (dragIndex.value !== null) dragOverLevel.value = level
}

function onDragLeave(level: TechLevel, event: DragEvent): void {
  const host = event.currentTarget as HTMLElement
  const next = event.relatedTarget as Node | null
  if (next && host.contains(next)) return
  if (dragOverLevel.value === level) dragOverLevel.value = ''
}

function onDrop(level: TechLevel): void {
  const index = dragIndex.value
  dragIndex.value = null
  dragOverLevel.value = ''
  if (index === null) return
  const item = draft.value.techStacks[index]
  if (!item || item.level === level) return
  item.level = level
}

function onDragEnd(): void {
  dragIndex.value = null
  dragOverLevel.value = ''
}

const editingIndex = ref<number | null>(null)
const editName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

async function startEdit(index: number, name: string): Promise<void> {
  if (dragIndex.value !== null) return
  editingIndex.value = index
  editName.value = name
  await nextTick()
  nameInput.value?.focus()
  nameInput.value?.select()
}

function commitEdit(): void {
  if (editingIndex.value === null) return
  const index = editingIndex.value
  const name = editName.value.trim()
  editingIndex.value = null
  if (!name) return
  const item = draft.value.techStacks[index]
  if (item) item.name = name
}

function cancelEdit(): void {
  editingIndex.value = null
}

function setNameInput(el: unknown): void {
  nameInput.value = el instanceof HTMLInputElement ? el : null
}

/** 锚点按项目分组，顺序跟随项目列表；不属于具体项目的统一放「通用」并置底。 */
const anchorGroups = computed(() => {
  const byProject = new Map<string, Anchor[]>()
  for (const project of draft.value.projects) byProject.set(project.id, [])
  const general: Anchor[] = []
  for (const anchor of draftAnchors.value) {
    const list = anchor.projectId ? byProject.get(anchor.projectId) : undefined
    if (list) list.push(anchor)
    else general.push(anchor)
  }
  return [
    ...draft.value.projects.map((project) => ({
      key: project.id,
      label: project.name || '未命名项目',
      anchors: byProject.get(project.id) ?? [],
    })),
    { key: '', label: '通用', anchors: general },
  ]
})

/** 只有一两条锚点的项目，多半是简历里轻轻带过的一句话，单独成组反而干扰核对。 */
const MIN_ANCHORS_PER_GROUP = 2

const visibleAnchorGroups = computed(() =>
  anchorGroups.value.filter(
    (group) =>
      group.anchors.length >= MIN_ANCHORS_PER_GROUP ||
      (group.anchors.length > 0 && pinnedAnchorKeys.value.includes(group.key)),
  ),
)

/** 删到整组为空后，把选择顺延到还在的分组。 */
watch(visibleAnchorGroups, (groups) => {
  if (!groups.some((group) => group.key === anchorKey.value)) {
    anchorKey.value = groups[0]?.key ?? ''
  }
})

const currentAnchorGroup = computed(
  () => visibleAnchorGroups.value.find((group) => group.key === anchorKey.value) ?? null,
)
/** 当前项目下的锚点再按类型分组；指标、架构这类标题就是出题时最先被追问的证据。 */
const anchorKindGroups = computed(() =>
  ANCHOR_KINDS.map((kind) => ({
    kind,
    label: kindLabel(kind),
    anchors: currentAnchorGroup.value?.anchors.filter((anchor) => anchor.kind === kind) ?? [],
  })).filter((group) => group.anchors.length),
)
const currentProjectAnchors = computed(() =>
  draftAnchors.value.filter((anchor) => anchor.projectId === projectId.value),
)

watch(
  anchorKindGroups,
  (groups) => {
    if (!groups.some((group) => group.kind === activeKind.value)) {
      activeKind.value = groups[0]?.kind ?? ''
    }
  },
  { immediate: true },
)

/** 切换画像或项目改名后，保证二级分类仍指向一个存在的项。 */
function resetSelections(): void {
  projectId.value = draft.value.projects[0]?.id ?? ''
  anchorKey.value = visibleAnchorGroups.value[0]?.key ?? ''
}

resetSelections()

watch(
  () => props.record,
  (record) => {
    draft.value = cloneProfile(record.profile)
    draftAnchors.value = cloneAnchors(record.anchors)
    pinnedAnchorKeys.value = []
    editingAnchorId.value = ''
    anchorInstruction.value = ''
    editUsage.value = null
    resetSelections()
  },
)

function tabCount(key: TabKey): number {
  if (key === 'tech') return draft.value.techStacks.length
  if (key === 'project') return draft.value.projects.length
  return visibleAnchorGroups.value.reduce((sum, group) => sum + group.anchors.length, 0)
}

function selectTab(key: TabKey): void {
  activeTab.value = key
  if (key === 'project' && !draft.value.projects.some((item) => item.id === projectId.value)) {
    projectId.value = draft.value.projects[0]?.id ?? ''
  }
  if (
    key === 'anchor' &&
    !visibleAnchorGroups.value.some((group) => group.key === anchorKey.value)
  ) {
    anchorKey.value = visibleAnchorGroups.value[0]?.key ?? ''
  }
}

function openProjectAnchors(id: string): void {
  if (!visibleAnchorGroups.value.some((group) => group.key === id)) return
  activeTab.value = 'anchor'
  anchorKey.value = id
}

function kindLabel(kind: AnchorKind): string {
  return KIND_LABEL[kind] ?? kind
}

/** 二级分类手风琴：再点一次收起，避免内容一直占着版面。 */
function toggleKind(kind: AnchorKind): void {
  activeKind.value = activeKind.value === kind ? '' : kind
  cancelAnchorEdit()
}

function anchorInputRef(id: string) {
  return (el: unknown): void => {
    if (el instanceof HTMLTextAreaElement && id === editingAnchorId.value) {
      anchorInput.value = el
    }
  }
}

async function startAnchorEdit(anchor: Anchor): Promise<void> {
  if (anchorSaving.value) return
  editingAnchorId.value = anchor.id
  anchorInstruction.value = ''
  await nextTick()
  anchorInput.value?.focus()
}

function cancelAnchorEdit(): void {
  editingAnchorId.value = ''
  anchorInstruction.value = ''
}

/** 锚点的 id / 原文 / 引用坐标始终沿用原值；只接受类型与追问方向的修改。 */
function applyAnchorEdit(anchor: Anchor, content: Record<string, unknown>): Anchor {
  const rawDirections = content.followDirections
  const directions = Array.isArray(rawDirections)
    ? rawDirections.map((item) => String(item).trim()).filter(Boolean)
    : []
  const kind = ANCHOR_KINDS.includes(content.kind as AnchorKind)
    ? (content.kind as AnchorKind)
    : anchor.kind
  return {
    ...anchor,
    kind,
    followDirections: directions.length ? directions : anchor.followDirections,
  }
}

async function submitAnchorEdit(anchor: Anchor): Promise<void> {
  const instruction = anchorInstruction.value.trim()
  if (!instruction) {
    message.warning('先写一下想怎么改')
    return
  }
  if (anchorSaving.value) return
  anchorSaving.value = true
  const targetId = anchor.id
  try {
    const project = draft.value.projects.find((item) => item.id === anchor.projectId)
    const result = await editContent({
      scene: 'anchor',
      instruction,
      content: { ...anchor },
      context: project ? { projectName: project.name } : {},
      lockedFields: ['id', 'quote', 'refs', 'projectId'],
    })
    const index = draftAnchors.value.findIndex((item) => item.id === targetId)
    if (index >= 0) {
      draftAnchors.value[index] = applyAnchorEdit(
        draftAnchors.value[index],
        result.content,
      )
    }
    editUsage.value = mergeUsage(editUsage.value, result.usage)
    cancelAnchorEdit()
    message.success(result.summary || '已按你的思路修改')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '修改失败')
  } finally {
    anchorSaving.value = false
  }
}

function removeAnchor(anchor: Anchor): void {
  const remaining = draftAnchors.value.filter((item) => item.id !== anchor.id)
  if (
    remaining.some((item) => item.projectId === anchor.projectId) &&
    !pinnedAnchorKeys.value.includes(anchor.projectId)
  ) {
    pinnedAnchorKeys.value = [...pinnedAnchorKeys.value, anchor.projectId]
  }
  draftAnchors.value = remaining
  if (editingAnchorId.value === anchor.id) cancelAnchorEdit()
}

function confirmDeleteAnchor(anchor: Anchor): void {
  if (anchorSaving.value) return
  dialog.warning({
    title: '删除这条锚点？',
    content: '删除后，出题不会再围绕这句话追问；保存画像后生效。',
    positiveText: '删除',
    negativeText: '保留',
    onPositiveClick: () => removeAnchor(anchor),
  })
}

watch(anchorKey, cancelAnchorEdit)

function onTechStackInput(projectIndex: number, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  draft.value.projects[projectIndex].techStack = raw
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function submit() {
  const direction = draft.value.direction.trim()
  if (!direction) {
    message.warning('请先填写求职方向')
    return
  }
  const profile: ResumeProfile = {
    direction,
    intro: (draft.value.intro ?? '').trim(),
    introRefs: draft.value.introRefs ?? [],
    techStacks: draft.value.techStacks
      .map((item) => ({ ...item, name: item.name.trim() }))
      .filter((item) => item.name),
    projects: draft.value.projects
      .map((item) => ({
        ...item,
        name: item.name.trim() || '未命名项目',
        intro: item.intro.trim(),
        role: item.role.trim(),
      }))
      .filter((item) => item.name),
  }
  emit('save', profile, draftAnchors.value, editUsage.value)
}
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <h2 class="panel-title">确认简历画像</h2>
      <button class="btn ghost" type="button" :disabled="analyzing" @click="emit('analyze')">
        <IconGlyph name="refresh-cw" :size="15" />
        {{ analyzing ? '重新分析中…' : '重新分析简历' }}
      </button>
    </header>

    <div v-if="record.warnings.length" class="warn-block">
      <IconGlyph name="info" :size="16" />
      <div class="warn-list">
        <p v-for="(warning, index) in record.warnings" :key="index">{{ warning }}</p>
      </div>
    </div>

    <div class="direction">
      <label class="direction-label" for="interview-direction">求职方向</label>
      <input
        id="interview-direction"
        v-model="draft.direction"
        class="direction-input"
        type="text"
        placeholder="例如：Java 后端开发 / 前端工程化"
      />
    </div>

    <div class="intro">
      <label class="direction-label" for="interview-intro">个人简介</label>
      <textarea
        id="interview-intro"
        v-model="draft.intro"
        class="intro-input"
        rows="3"
        placeholder="简历里没有可归纳的个人简介"
      ></textarea>
      <ReferenceBadge
        v-if="draft.introRefs?.length"
        :coords="draft.introRefs"
        class="intro-ref"
        @open="openRefs"
      />
    </div>

    <nav class="sections" role="tablist" aria-label="画像内容分类">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="section-tab"
        :class="{ active: activeTab === tab.key }"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.key"
        :title="tab.key === 'anchor' ? ANCHOR_INFO : undefined"
        :aria-label="tab.key === 'anchor' ? `证据锚点：${ANCHOR_INFO}` : undefined"
        @click="selectTab(tab.key)"
      >
        {{ tab.label }}
        <span v-if="tab.key === 'anchor'" class="tab-info" aria-hidden="true">
          <IconGlyph name="info" :size="11" />
        </span>
        <span class="section-count">{{ tabCount(tab.key) }}</span>
      </button>
    </nav>

    <div class="section-body" role="tabpanel">
      <!-- 简历项目：切换项目，编辑名称 / 角色 / 简介 / 技术栈 -->
      <template v-if="activeTab === 'project'">
        <p v-if="!draft.projects.length" class="content-empty">
          简历里没有可用于面试的项目：可能没有识别到项目，或项目都缺少足够的证据锚点（每个项目至少
          {{ MIN_ANCHORS_PER_GROUP }} 条）。请补充项目细节后重新分析简历。
        </p>
        <template v-else>
          <div class="chips" aria-label="项目列表">
            <button
              v-for="project in draft.projects"
              :key="project.id"
              class="chip-btn"
              :class="{ active: projectId === project.id }"
              type="button"
              :aria-pressed="projectId === project.id"
              @click="projectId = project.id"
            >
              {{ project.name || '未命名项目' }}
            </button>
          </div>

          <template v-for="(project, index) in draft.projects" :key="project.id">
            <article v-if="project.id === projectId" class="project-editor">
              <div class="field-grid">
                <label class="field">
                  <span class="field-label">项目名称</span>
                  <input v-model="project.name" class="input" type="text" />
                </label>
                <label class="field">
                  <span class="field-label">你的角色</span>
                  <input v-model="project.role" class="input" type="text" />
                </label>
              </div>

              <label class="field">
                <span class="field-label">项目简介</span>
                <textarea v-model="project.intro" class="textarea" rows="2"></textarea>
              </label>

              <label class="field">
                <span class="field-label">
                  技术栈
                  <span class="field-hint">用逗号分隔</span>
                </span>
                <input
                  class="input"
                  type="text"
                  :value="project.techStack.join('、')"
                  @input="onTechStackInput(index, $event)"
                />
              </label>

              <p class="project-evidence">
                <IconGlyph name="file-text" :size="14" />
                <span v-if="currentProjectAnchors.length">
                  本项目有 {{ currentProjectAnchors.length }} 条证据锚点，出题会围绕这些原文追问。
                </span>
                <span v-else>本项目还没有证据锚点，问题会偏向通用提问。</span>
                <button
                  v-if="currentProjectAnchors.length"
                  class="link-btn"
                  type="button"
                  @click="openProjectAnchors(project.id)"
                >
                  查看锚点
                  <IconGlyph name="arrow-right" :size="13" />
                </button>
              </p>
            </article>
          </template>
        </template>
      </template>

      <!-- 技术栈：分类固定展示，技能是可拖动的气泡 -->
      <template v-else-if="activeTab === 'tech'">
        <p v-if="!draft.techStacks.length" class="section-note">
          简历里没有识别到明确的技术栈。三个分类仍然保留，可以把技能拖到对应分类。
        </p>
        <div class="bubble-field" :class="{ 'is-dragging': dragIndex !== null }">
          <section
            v-for="group in techGroups"
            :key="group.level"
            class="tech-group"
            :class="{ 'drop-target': dragOverLevel === group.level }"
            @dragover.prevent="onDragOver(group.level)"
            @dragleave="onDragLeave(group.level, $event)"
            @drop.prevent="onDrop(group.level)"
          >
            <h3 class="tech-group-head">
              {{ group.level }}
              <span class="tech-group-count">{{ group.items.length }}</span>
            </h3>
            <div class="bubble-row">
              <div
                v-for="row in group.items"
                :key="row.index"
                class="tech-bubble"
                :class="{
                  dragging: dragIndex === row.index,
                  editing: editingIndex === row.index,
                }"
                :draggable="editingIndex !== row.index"
                @dragstart="onDragStart(row.index, $event)"
                @dragend="onDragEnd"
                @dblclick="startEdit(row.index, row.item.name)"
              >
                <input
                  v-if="editingIndex === row.index"
                  :ref="setNameInput"
                  v-model="editName"
                  class="bubble-input"
                  type="text"
                  aria-label="修改技能名称"
                  @click.stop
                  @dblclick.stop
                  @keydown.enter.prevent="commitEdit"
                  @keydown.esc.prevent="cancelEdit"
                  @blur="commitEdit"
                />
                <span v-else class="bubble-name">{{ row.item.name }}</span>
                <ReferenceBadge
                  v-if="refsOf(row.item).length"
                  :coords="refsOf(row.item)"
                  class="bubble-ref"
                  @open="openRefs"
                />
              </div>
              <span v-if="!group.items.length" class="bubble-empty">拖技能到这里</span>
            </div>
          </section>
        </div>
        <p class="tech-hint">拖到分类标题上即可调整掌握程度；双击技能可改名。</p>
      </template>

      <!-- 证据锚点：按项目 + 通用分组，锚点太少的组不展示 -->
      <template v-else>
        <p v-if="!draftAnchors.length" class="content-empty">
          暂无可用锚点，问题包会偏向通用题。
        </p>
        <template v-else>
          <div class="chips" aria-label="锚点分组">
            <button
              v-for="group in visibleAnchorGroups"
              :key="group.key || 'general'"
              class="chip-btn"
              :class="{ active: anchorKey === group.key }"
              type="button"
              :aria-pressed="anchorKey === group.key"
              @click="anchorKey = group.key"
            >
              {{ group.label }}
              <span class="chip-count">{{ group.anchors.length }}</span>
            </button>
          </div>

          <p v-if="!currentAnchorGroup" class="content-empty">
            证据锚点按项目汇总，少于 {{ MIN_ANCHORS_PER_GROUP }}
            条的项目不在这里展示。当前简历里可追问的细节还不够，补充项目细节后重新分析简历。
          </p>
          <div v-else class="anchor-groups">
            <section
              v-for="group in anchorKindGroups"
              :key="group.kind"
              class="anchor-group"
              :class="{ open: activeKind === group.kind }"
            >
              <button
                class="anchor-group-head"
                type="button"
                :aria-expanded="activeKind === group.kind"
                @click="toggleKind(group.kind)"
              >
                <IconGlyph name="chevron-right" :size="14" class="anchor-group-chevron" />
                <span class="anchor-group-title">{{ group.label }}</span>
                <span class="anchor-group-count">{{ group.anchors.length }}</span>
              </button>

              <div v-if="activeKind === group.kind" class="anchor-group-body">
                <div
                  v-for="anchor in group.anchors"
                  :key="anchor.id"
                  class="anchor-item"
                >
                  <p class="anchor-text">
                    {{
                      anchor.followDirections.length
                        ? anchor.followDirections.join('；')
                        : '暂无可追问方向'
                    }}
                    <button
                      v-if="refsOf(anchor).length"
                      class="anchor-mark"
                      type="button"
                      title="在简历原文中查看引用"
                      @click="openRefs(refsOf(anchor))"
                    >
                      原文
                    </button>
                    <button
                      class="anchor-mark"
                      type="button"
                      :disabled="anchorSaving"
                      title="让 AI 按你的思路改写追问方向"
                      @click="startAnchorEdit(anchor)"
                    >
                      AI 改写
                    </button>
                    <button
                      class="anchor-mark anchor-mark-danger"
                      type="button"
                      :disabled="anchorSaving"
                      title="从本次面试的证据锚点中删除"
                      @click="confirmDeleteAnchor(anchor)"
                    >
                      删除
                    </button>
                  </p>

                  <div v-if="editingAnchorId === anchor.id" class="anchor-editor">
                    <textarea
                      :ref="anchorInputRef(anchor.id)"
                      v-model="anchorInstruction"
                      class="anchor-input"
                      rows="3"
                      aria-label="描述想怎么修改这条锚点"
                      placeholder="描述你想怎么改，例如：追问方向聚焦到统计口径和压测方法"
                      :disabled="anchorSaving"
                      @keydown.enter.meta.prevent="submitAnchorEdit(anchor)"
                      @keydown.enter.ctrl.prevent="submitAnchorEdit(anchor)"
                      @keydown.esc.prevent="cancelAnchorEdit"
                    ></textarea>
                    <div class="anchor-editor-actions">
                      <button
                        class="btn ghost sm"
                        type="button"
                        :disabled="anchorSaving"
                        @click="cancelAnchorEdit"
                      >
                        取消
                      </button>
                      <button
                        class="btn primary sm"
                        type="button"
                        :disabled="anchorSaving"
                        @click="submitAnchorEdit(anchor)"
                      >
                        {{ anchorSaving ? '改写中…' : '按这个思路改写' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </template>
      </template>
    </div>

    <footer class="panel-foot">
      <p class="foot-hint">保存后会按这份画像与锚点出题，改动会作废旧问题包。</p>
      <button class="btn primary" type="button" @click="submit">
        保存，选择面试方式
        <IconGlyph name="arrow-right" :size="15" />
      </button>
    </footer>

    <ResumeSourcePanel
      :open="previewOpen"
      :coords="previewCoords"
      :seq="previewSeq"
      @close="previewOpen = false"
    />
  </section>
</template>

<style scoped>
.panel {
  padding: 26px 30px 32px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-paper);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.panel-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.warn-block {
  display: flex;
  gap: 9px;
  margin-top: 18px;
  padding: 3px 0 3px 12px;
  border-left: 2px solid rgba(143, 97, 40, 0.38);
  color: var(--warning);
}
.warn-block svg {
  flex: none;
  margin-top: 2px;
}
.warn-list p {
  margin: 0 0 4px;
  font-size: 13px;
  line-height: 1.6;
}
.warn-list p:last-child {
  margin-bottom: 0;
}

.direction {
  margin-top: 22px;
}
.direction-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.direction-input {
  display: block;
  width: 100%;
  max-width: 620px;
  padding: 2px 0 8px;
  border: none;
  border-bottom: 1px solid transparent;
  border-radius: 0;
  background: transparent;
  font-family: inherit;
  font-size: 14.5px;
  font-weight: 400;
  line-height: 1.75;
  color: var(--text-secondary);
  transition:
    border-color var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease);
}
.direction-input::placeholder {
  color: var(--text-tertiary);
}
.direction-input:hover {
  border-bottom-color: var(--border);
}
.direction-input:focus {
  outline: none;
  border-bottom-color: var(--primary);
  color: var(--text);
}

.intro {
  position: relative;
  max-width: 620px;
  margin-top: 18px;
}
.intro-ref {
  position: absolute;
  top: -5px;
  right: 0;
}
.intro-input {
  display: block;
  width: 100%;
  max-width: 620px;
  padding: 2px 0 8px;
  border: none;
  border-bottom: 1px solid transparent;
  background: transparent;
  font-family: inherit;
  font-size: 14.5px;
  line-height: 1.75;
  color: var(--text-secondary);
  resize: none;
  field-sizing: content;
  min-height: 54px;
  transition:
    border-color var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease);
}
.intro-input::placeholder {
  color: var(--text-tertiary);
}
.intro-input:hover {
  border-bottom-color: var(--border);
}
.intro-input:focus {
  outline: none;
  border-bottom-color: var(--primary);
  color: var(--text);
}

.sections {
  display: flex;
  gap: 26px;
  margin-top: 26px;
  border-bottom: 1px solid var(--border);
}
.section-tab {
  position: relative;
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  flex: none;
  padding: 0 1px 11px;
  border: none;
  background: transparent;
  font-size: 14.5px;
  font-weight: 500;
  white-space: nowrap;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--dur-2) var(--ease);
}
.section-tab:hover {
  color: var(--text);
}
.section-tab.active {
  font-weight: 600;
  color: var(--text);
}
.section-tab::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--primary);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--dur-3) var(--ease-out);
}
.section-tab.active::after {
  transform: scaleX(1);
}
.section-count {
  font-size: 12.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
}
.section-tab.active .section-count {
  color: var(--primary);
}
.tab-info {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  align-self: center;
  flex: none;
  width: 15px;
  height: 15px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  transition:
    background-color var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease);
}
.section-tab:hover .tab-info,
.section-tab.active .tab-info {
  background: var(--primary-soft);
  color: var(--primary);
}

.section-body {
  margin-top: 22px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 7px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  font-size: 13px;
  line-height: 1.45;
  text-align: left;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color var(--dur-2) var(--ease),
    border-color var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease);
}
.chip-btn:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
  color: var(--text);
}
.chip-btn.active {
  border-color: var(--primary-line);
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.chip-count {
  flex: none;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
}
.chip-btn.active .chip-count {
  color: var(--primary);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.field-label {
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.field-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-tertiary);
}
.input,
.select,
.textarea {
  width: 100%;
  padding: 8px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-bg);
  color: var(--text);
  font-size: 14.5px;
  line-height: 1.55;
  transition:
    border-color var(--dur-2) var(--ease),
    box-shadow var(--dur-2) var(--ease);
}
.input {
  height: 40px;
}
.input:focus,
.select:focus,
.textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--focus-ring);
}
.textarea {
  resize: vertical;
  min-height: 64px;
  field-sizing: content;
}

.project-editor {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-top: 22px;
}
.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.project-evidence {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.project-evidence svg {
  flex: none;
  color: var(--text-tertiary);
}
.link-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0;
  border: none;
  background: transparent;
  font-size: 13px;
  font-weight: 500;
  color: var(--primary);
  cursor: pointer;
}
.link-btn:hover {
  text-decoration: underline;
}

.bubble-field {
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin-top: 20px;
  padding: 28px 26px;
  border: 1px solid var(--primary-line);
  border-radius: 46px 58px 44px 62px / 40px 50px 38px 56px;
  background: var(--primary-faint);
  animation: bubble-sway 12s ease-in-out infinite;
}
@keyframes bubble-sway {
  0%,
  100% {
    border-radius: 46px 58px 44px 62px / 40px 50px 38px 56px;
  }
  50% {
    border-radius: 60px 44px 58px 46px / 54px 36px 50px 40px;
  }
}
.bubble-field.is-dragging {
  animation-play-state: paused;
}
.tech-group {
  padding: 2px;
  border-radius: var(--radius-md);
  transition:
    background-color var(--dur-2) var(--ease),
    box-shadow var(--dur-2) var(--ease);
}
.tech-group.drop-target {
  background: var(--panel-bg);
  box-shadow: inset 0 0 0 1px var(--primary);
}
.tech-group-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0;
  padding: 0 4px 8px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  transition:
    color var(--dur-2) var(--ease),
    border-color var(--dur-2) var(--ease);
}
.tech-group.drop-target .tech-group-head {
  border-bottom-color: var(--primary);
  color: var(--primary);
}
.tech-group-count {
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
}
.bubble-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 12px 4px 2px;
}
.tech-bubble {
  position: relative;
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 9px 15px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel-bg);
  font-size: 13.5px;
  line-height: 1.45;
  color: var(--text);
  cursor: grab;
  user-select: none;
  transition:
    border-color var(--dur-2) var(--ease),
    background-color var(--dur-2) var(--ease),
    box-shadow var(--dur-2) var(--ease),
    transform var(--dur-2) var(--ease);
}
.tech-bubble:hover {
  border-color: var(--primary-line);
  box-shadow: var(--shadow-xs);
  transform: translateY(-1px);
}
.tech-bubble.dragging {
  opacity: 0.45;
  cursor: grabbing;
}
.tech-bubble.editing {
  cursor: text;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--focus-ring);
}
.bubble-name {
  min-width: 0;
  overflow-wrap: anywhere;
}
.bubble-input {
  width: 10em;
  max-width: 100%;
  padding: 0;
  border: none;
  outline: none;
  background: transparent;
  color: inherit;
  font: inherit;
  line-height: inherit;
}
.bubble-ref {
  position: absolute;
  top: -8px;
  right: -8px;
}
.bubble-empty {
  padding: 8px 2px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.tech-hint {
  margin: 16px 0 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-tertiary);
}

.section-note {
  margin: 16px 0 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-tertiary);
}
.anchor-groups {
  margin-top: 14px;
}
.anchor-group {
  border-top: 1px solid var(--border);
}
.anchor-group:last-child {
  border-bottom: 1px solid var(--border);
}
.anchor-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 11px 2px;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--dur-2) var(--ease);
}
.anchor-group-head:hover,
.anchor-group.open .anchor-group-head {
  color: var(--text);
}
.anchor-group-chevron {
  flex: none;
  color: var(--text-tertiary);
  transition:
    transform var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease);
}
.anchor-group.open .anchor-group-chevron {
  transform: rotate(90deg);
  color: var(--primary);
}
.anchor-group-title {
  flex: none;
}
.anchor-group-count {
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.anchor-group-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0 2px 14px 22px;
}
.anchor-item {
  min-width: 0;
}
.anchor-text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--text);
  word-break: break-word;
}
/* 原文 / 改写做成正文末尾的上标，不另起一行；点开才出现对应面板。 */
.anchor-mark {
  display: inline;
  margin-left: 4px;
  padding: 0;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 10px;
  font-weight: 500;
  line-height: 1;
  vertical-align: super;
  color: var(--text-tertiary);
  cursor: pointer;
  text-decoration-line: underline;
  text-decoration-style: dotted;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 2px;
  transition: color var(--dur-2) var(--ease);
}
.anchor-mark:hover {
  color: var(--primary);
  text-decoration-style: solid;
  text-decoration-color: currentColor;
}
.anchor-mark-danger:hover {
  color: var(--danger);
}
.anchor-mark:disabled {
  opacity: 0.45;
  cursor: default;
  text-decoration: none;
}
.anchor-editor {
  margin-top: 9px;
  padding-top: 9px;
  border-top: 1px dashed var(--border);
}
.anchor-input {
  display: block;
  width: 100%;
  min-height: 68px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--text);
  resize: vertical;
}
.anchor-input::placeholder {
  color: var(--text-tertiary);
}
.anchor-input:focus {
  outline: none;
  border-color: var(--primary);
  background: var(--panel-bg);
  box-shadow: 0 0 0 3px var(--focus-ring);
}
.anchor-input:disabled {
  opacity: 0.7;
}
.anchor-editor-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 9px;
}

.content-empty {
  margin: 0;
  padding: 32px 0 24px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-tertiary);
}

.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
.foot-hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-tertiary);
}

@media (max-width: 860px) {
  .panel {
    padding: 20px 18px 24px;
  }
  .panel-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  .direction-input {
    max-width: 100%;
  }
  .field-grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }
  .panel-foot {
    flex-direction: column;
    align-items: stretch;
  }
  .panel-foot .btn {
    justify-content: center;
  }
}

@media (max-width: 640px) {
  .sections {
    gap: 20px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .sections::-webkit-scrollbar {
    display: none;
  }
  .bubble-field {
    padding: 20px 16px;
    border-radius: 28px 34px 26px 36px / 24px 30px 22px 34px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .bubble-field {
    animation: none;
  }
}
</style>
