<script setup lang="ts">
/**
 * 样式设置面板（章节 / 内容共用）
 *
 * 注意：本组件只负责渲染"面板内容"，不含弹层外壳 ——
 * 谁用它，谁决定把它放进什么弹层里：
 *  - SectionCard：放在章节工具栏的「🎨 样式」n-popover 里；
 *  - ContentCard：放在 ⋯ 菜单的 n-popover 里。
 *
 * - 章节（mode="section"）：标题字号独立设置；正文字号/颜色/行距/块间距
 *   会"继承"给内部所有内容；
 * - 内容（mode="content"）：每个字段都能选择"跟随章节"（继承）或自己设置。
 *
 * 写入统一走 store.updateSection / store.updateContent（单一数据源）。
 */
import { computed } from 'vue'
import { useResumeStore } from '@/stores/resume'
import {
  DEFAULT_CHAPTER_GAP,
  DEFAULT_COLOR,
  DEFAULT_FONT_SIZE,
  DEFAULT_GAP,
  DEFAULT_LINE_HEIGHT,
  DEFAULT_TEXT_ALIGN,
  DEFAULT_TITLE_SIZE,
  DEFAULT_TITLE_UNDERLINE,
} from '@/utils/constants'
import type { Content, LayoutWindow, ContentStyle, SectionStyle, TextAlign } from '@/types'

const props = defineProps<{
  /** section = 设置章节样式；content = 设置内容样式 */
  mode: 'section' | 'content'
  sectionId: string
  /** mode="content" 时必传 */
  contentId?: string
}>()

const store = useResumeStore()

/** 目标章节（两种模式都需要它） */
const section = computed(() => store.sectionById(props.sectionId))
/** 目标内容（仅 content 模式；内容可能在嵌套窗口里，递归查找所有窗口） */
const content = computed(() => {
  const search = (rows: LayoutWindow[]): Content | undefined => {
    for (const row of rows) {
      const found = row.contents.find((b) => b.id === props.contentId)
      if (found) return found
      if (row.rows) {
        const nested = search(row.rows)
        if (nested) return nested
      }
    }
    return undefined
  }
  return search(section.value?.rows ?? [])
})

/** 当前样式对象（section 模式 = 章节样式；content 模式 = 内容样式） */
const style = computed<SectionStyle | ContentStyle | undefined>(() =>
  props.mode === 'content' ? content.value?.style : section.value?.style,
)

/** 章节样式（类型固定为 SectionStyle，标题字号等章节专属字段用它读） */
const sectionStyle = computed<SectionStyle | undefined>(() => section.value?.style)

/** 占位组件：高度由 字号 × 行距 决定，它没有文字，所以不提供「文字颜色」 */
const isSpacer = computed(() => content.value?.type === 'spacer')

/* ---------- 通用：把样式字段写回 store ---------- */

/** 更新章节样式字段 */
function setSectionStyle(patch: Partial<SectionStyle>) {
  if (section.value) store.updateSection(section.value.id, { style: patch })
}
/** 更新内容样式字段 */
function setContentStyle(patch: Partial<ContentStyle>) {
  if (section.value && content.value) {
    store.updateContent(section.value.id, content.value.id, { style: patch })
  }
}
/** 按模式分发：写入当前目标对象的样式 */
function setStyle<K extends keyof SectionStyle>(key: K, value: SectionStyle[K]) {
  if (props.mode === 'section') setSectionStyle({ [key]: value } as Partial<SectionStyle>)
  else setContentStyle({ [key]: value } as Partial<ContentStyle>)
}

/* ---------- 内容专属：字段"是否跟随章节" ---------- */

/**
 * 内容样式里没有设置某个字段（undefined）→ 该字段跟随章节。
 * 下面 4 个"跟随"开关与字段一一对应。
 */
const followMap = computed<Record<'fontSize' | 'color' | 'lineHeight' | 'gap' | 'textAlign', boolean>>(() => ({
  fontSize: content.value?.style.fontSize === undefined,
  color: content.value?.style.color === undefined,
  lineHeight: content.value?.style.lineHeight === undefined,
  gap: content.value?.style.gap === undefined,
  textAlign: content.value?.style.textAlign === undefined,
}))

/** 切换"跟随/自定义"：跟随 = 清除字段（传 undefined 即删除） */
function setFollow(key: 'fontSize' | 'color' | 'lineHeight' | 'gap' | 'textAlign', follow: boolean) {
  if (!content.value) return
  const defaults: Record<typeof key, number | string> = {
    fontSize: DEFAULT_FONT_SIZE,
    color: DEFAULT_COLOR,
    lineHeight: DEFAULT_LINE_HEIGHT,
    gap: DEFAULT_GAP,
    textAlign: DEFAULT_TEXT_ALIGN,
  }
  setContentStyle({ [key]: follow ? undefined : defaults[key] } as Partial<ContentStyle>)
}

/* ---------- 颜色选择器的预设色板 ---------- */
const colorPresets = [
  '#334155', '#1f2937', '#4f7cff', '#0ea5e9',
  '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
]
</script>

<template>
  <div class="style-panel">
    <!-- 标题字号：只有章节有（独立设置，不继承） -->
    <div v-if="mode === 'section'" class="style-row">
          <span class="style-label">标题字号</span>
          <div class="style-control">
            <n-slider
              :value="sectionStyle?.titleSize ?? DEFAULT_TITLE_SIZE"
              :min="12"
              :max="100"
              :step="1"
              :tooltip="false"
              @update:value="(v: number) => setStyle('titleSize', v)"
            />
            <span class="style-value">{{ sectionStyle?.titleSize ?? DEFAULT_TITLE_SIZE }}px</span>
          </div>
        </div>

        <!-- 标题横线：默认开启；横线恒为满行长度 -->
        <div v-if="mode === 'section'" class="style-row">
          <span class="style-label">标题横线</span>
          <div class="style-control">
            <n-switch
              :value="sectionStyle?.titleUnderline ?? DEFAULT_TITLE_UNDERLINE"
              @update:value="(v: boolean) => setStyle('titleUnderline', v)"
            >
              <template #checked>开</template>
              <template #unchecked>关</template>
            </n-switch>
          </div>
        </div>

        <!-- 章节间距：本章节与上一个章节之间的距离（只有章节有） -->
        <div v-if="mode === 'section'" class="style-row">
          <span class="style-label">章节间距</span>
          <div class="style-control">
            <n-slider
              :value="sectionStyle?.spaceBefore ?? DEFAULT_CHAPTER_GAP"
              :min="0"
              :max="60"
              :step="2"
              :tooltip="false"
              @update:value="(v: number) => setStyle('spaceBefore', v)"
            />
            <span class="style-value">{{ sectionStyle?.spaceBefore ?? DEFAULT_CHAPTER_GAP }}px</span>
          </div>
        </div>

        <!-- 正文字号 -->
        <div class="style-row">
          <span class="style-label">
            正文字号
            <n-switch
              v-if="mode === 'content'"
              class="follow-switch"
              size="small"
              :value="followMap.fontSize"
              @update:value="(v: boolean) => setFollow('fontSize', v)"
            >
              <template #checked>跟随</template>
              <template #unchecked>自定义</template>
            </n-switch>
          </span>
          <div class="style-control">
            <n-slider
              :value="style?.fontSize ?? DEFAULT_FONT_SIZE"
              :min="10"
              :max="100"
              :step="1"
              :disabled="mode === 'content' && followMap.fontSize"
              :tooltip="false"
              @update:value="(v: number) => setStyle('fontSize', v)"
            />
            <span class="style-value">{{ style?.fontSize ?? DEFAULT_FONT_SIZE }}px</span>
          </div>
        </div>

        <!-- 文字颜色（占位组件没有文字，不显示这一行） -->
        <div v-if="!isSpacer" class="style-row">
          <span class="style-label">
            文字颜色
            <n-switch
              v-if="mode === 'content'"
              class="follow-switch"
              size="small"
              :value="followMap.color"
              @update:value="(v: boolean) => setFollow('color', v)"
            >
              <template #checked>跟随</template>
              <template #unchecked>自定义</template>
            </n-switch>
          </span>
          <div class="style-control">
            <n-color-picker
              size="small"
              :value="style?.color ?? DEFAULT_COLOR"
              :show-alpha="false"
              :swatches="colorPresets"
              @update:value="(v: string) => setStyle('color', v)"
            />
          </div>
        </div>

        <!-- 文字位置：左 / 中 / 右（占位组件没有文字，不显示） -->
        <div v-if="!isSpacer" class="style-row">
          <span class="style-label">
            文字位置
            <n-switch
              v-if="mode === 'content'"
              class="follow-switch"
              size="small"
              :value="followMap.textAlign"
              @update:value="(v: boolean) => setFollow('textAlign', v)"
            >
              <template #checked>跟随</template>
              <template #unchecked>自定义</template>
            </n-switch>
          </span>
          <n-radio-group
            :value="style?.textAlign ?? DEFAULT_TEXT_ALIGN"
            size="small"
            @update:value="(v: TextAlign) => setStyle('textAlign', v)"
          >
            <n-radio-button value="left">左</n-radio-button>
            <n-radio-button value="center">中</n-radio-button>
            <n-radio-button value="right">右</n-radio-button>
          </n-radio-group>
        </div>

        <!-- 行距 -->
        <div class="style-row">
          <span class="style-label">
            行距
            <n-switch
              v-if="mode === 'content'"
              class="follow-switch"
              size="small"
              :value="followMap.lineHeight"
              @update:value="(v: boolean) => setFollow('lineHeight', v)"
            >
              <template #checked>跟随</template>
              <template #unchecked>自定义</template>
            </n-switch>
          </span>
          <div class="style-control">
            <n-slider
              :value="style?.lineHeight ?? DEFAULT_LINE_HEIGHT"
              :min="1"
              :max="2.4"
              :step="0.1"
              :disabled="mode === 'content' && followMap.lineHeight"
              :tooltip="false"
              @update:value="(v: number) => setStyle('lineHeight', v)"
            />
            <span class="style-value">{{ (style?.lineHeight ?? DEFAULT_LINE_HEIGHT).toFixed(1) }}</span>
          </div>
        </div>

        <!-- 块间距（竖向/横向间距） -->
        <div class="style-row">
          <span class="style-label">
            块间距
            <n-switch
              v-if="mode === 'content'"
              class="follow-switch"
              size="small"
              :value="followMap.gap"
              @update:value="(v: boolean) => setFollow('gap', v)"
            >
              <template #checked>跟随</template>
              <template #unchecked>自定义</template>
            </n-switch>
          </span>
          <div class="style-control">
            <n-slider
              :value="style?.gap ?? DEFAULT_GAP"
              :min="0"
              :max="36"
              :step="2"
              :disabled="mode === 'content' && followMap.gap"
              :tooltip="false"
              @update:value="(v: number) => setStyle('gap', v)"
            />
            <span class="style-value">{{ style?.gap ?? DEFAULT_GAP }}px</span>
          </div>
        </div>

        <p v-if="mode === 'section'" class="style-hint">
          💡 正文字号 / 颜色 / 行距 / 块间距会继承给章节内所有内容
        </p>
        <p v-else class="style-hint">
          💡 开启「自定义」后该字段独立生效；「跟随」= 使用章节的继承值
        </p>
  </div>
</template>

<style scoped>
.style-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 2px;
}

.style-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.style-label {
  font-size: 12px;
  color: #6b7280;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.follow-switch {
  --n-rail-height: 16px;
}

.style-control {
  display: flex;
  align-items: center;
  gap: 10px;
}
.style-control :deep(.n-slider) {
  flex: 1;
}

.style-value {
  width: 42px;
  text-align: right;
  font-size: 12px;
  color: #374151;
  font-variant-numeric: tabular-nums;
}

.style-hint {
  margin: 0;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.5;
}
</style>
