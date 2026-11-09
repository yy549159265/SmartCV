<script setup lang="ts">
import { computed, ref } from 'vue'
import { useResumeStore } from '@/stores/resume'
import IconGlyph from './IconGlyph.vue'
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
  mode: 'section' | 'content'
  sectionId: string
  contentId?: string
}>()

const store = useResumeStore()

const section = computed(() => store.sectionById(props.sectionId))
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

const style = computed<SectionStyle | ContentStyle | undefined>(() =>
  props.mode === 'content' ? content.value?.style : section.value?.style,
)

const sectionStyle = computed<SectionStyle | undefined>(() => section.value?.style)

const isSpacer = computed(() => content.value?.type === 'spacer')

type TabKey = 'text' | 'title' | 'spacing'
const tab = ref<TabKey>('text')

const tabs = computed<{ key: TabKey; label: string }[]>(() =>
  props.mode === 'section'
    ? [
        { key: 'text', label: '文字' },
        { key: 'title', label: '标题' },
        { key: 'spacing', label: '间距' },
      ]
    : [
        { key: 'text', label: '文字' },
        { key: 'spacing', label: '间距' },
      ],
)

function setSectionStyle(patch: Partial<SectionStyle>) {
  if (section.value) store.updateSection(section.value.id, { style: patch })
}
function setContentStyle(patch: Partial<ContentStyle>) {
  if (section.value && content.value) {
    store.updateContent(section.value.id, content.value.id, { style: patch })
  }
}
function setStyle<K extends keyof SectionStyle>(key: K, value: SectionStyle[K]) {
  if (props.mode === 'section') setSectionStyle({ [key]: value } as Partial<SectionStyle>)
  else setContentStyle({ [key]: value } as Partial<ContentStyle>)
}

const followMap = computed<Record<'fontSize' | 'color' | 'lineHeight' | 'gap' | 'textAlign', boolean>>(() => ({
  fontSize: content.value?.style.fontSize === undefined,
  color: content.value?.style.color === undefined,
  lineHeight: content.value?.style.lineHeight === undefined,
  gap: content.value?.style.gap === undefined,
  textAlign: content.value?.style.textAlign === undefined,
}))

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

const colorPresets = [
  '#334155', '#1f2937', '#4f7cff', '#0ea5e9',
  '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
]
</script>

<template>
  <div class="style-panel">
    <div class="style-tabs" role="tablist">
      <button
        v-for="t in tabs"
        :key="t.key"
        type="button"
        role="tab"
        class="style-tab"
        :class="{ active: tab === t.key }"
        :aria-selected="tab === t.key"
        @click="tab = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <div v-show="tab === 'text'" class="style-pane">
      <div class="prop-row">
        <span class="prop-chip"><IconGlyph name="type" :size="13" /></span>
        <span class="prop-label">正文字号</span>
        <div class="prop-control" :class="{ disabled: mode === 'content' && followMap.fontSize }">
          <n-slider
            :value="style?.fontSize ?? DEFAULT_FONT_SIZE"
            :min="10"
            :max="100"
            :step="1"
            :disabled="mode === 'content' && followMap.fontSize"
            :tooltip="false"
            @update:value="(v: number) => setStyle('fontSize', v)"
          />
        </div>
        <span class="prop-value">{{ style?.fontSize ?? DEFAULT_FONT_SIZE }}px</span>
        <button
          v-if="mode === 'content'"
          type="button"
          class="follow-pill"
          :class="{ on: followMap.fontSize }"
          :title="followMap.fontSize ? '当前跟随章节，点击改为自定义' : '当前自定义，点击恢复跟随章节'"
          @click="setFollow('fontSize', !followMap.fontSize)"
        >
          {{ followMap.fontSize ? '跟随' : '自定义' }}
        </button>
      </div>

      <div v-if="!isSpacer" class="prop-row">
        <span class="prop-chip"><IconGlyph name="droplet" :size="13" /></span>
        <span class="prop-label">文字颜色</span>
        <div class="prop-control prop-control-right" :class="{ disabled: mode === 'content' && followMap.color }">
          <n-color-picker
            size="small"
            :value="style?.color ?? DEFAULT_COLOR"
            :show-alpha="false"
            :swatches="colorPresets"
            :disabled="mode === 'content' && followMap.color"
            @update:value="(v: string) => setStyle('color', v)"
          />
        </div>
        <button
          v-if="mode === 'content'"
          type="button"
          class="follow-pill"
          :class="{ on: followMap.color }"
          :title="followMap.color ? '当前跟随章节，点击改为自定义' : '当前自定义，点击恢复跟随章节'"
          @click="setFollow('color', !followMap.color)"
        >
          {{ followMap.color ? '跟随' : '自定义' }}
        </button>
      </div>

      <div v-if="!isSpacer" class="prop-row">
        <span class="prop-chip"><IconGlyph name="align-left" :size="13" /></span>
        <span class="prop-label">文字位置</span>
        <div class="prop-control prop-control-right" :class="{ disabled: mode === 'content' && followMap.textAlign }">
          <n-radio-group
            :value="style?.textAlign ?? DEFAULT_TEXT_ALIGN"
            size="small"
            :disabled="mode === 'content' && followMap.textAlign"
            @update:value="(v: TextAlign) => setStyle('textAlign', v)"
          >
            <n-radio-button value="left">左</n-radio-button>
            <n-radio-button value="center">中</n-radio-button>
            <n-radio-button value="right">右</n-radio-button>
          </n-radio-group>
        </div>
        <button
          v-if="mode === 'content'"
          type="button"
          class="follow-pill"
          :class="{ on: followMap.textAlign }"
          :title="followMap.textAlign ? '当前跟随章节，点击改为自定义' : '当前自定义，点击恢复跟随章节'"
          @click="setFollow('textAlign', !followMap.textAlign)"
        >
          {{ followMap.textAlign ? '跟随' : '自定义' }}
        </button>
      </div>

      <div class="prop-row">
        <span class="prop-chip"><IconGlyph name="stretch-vertical" :size="13" /></span>
        <span class="prop-label">行距</span>
        <div class="prop-control" :class="{ disabled: mode === 'content' && followMap.lineHeight }">
          <n-slider
            :value="style?.lineHeight ?? DEFAULT_LINE_HEIGHT"
            :min="1"
            :max="2.4"
            :step="0.1"
            :disabled="mode === 'content' && followMap.lineHeight"
            :tooltip="false"
            @update:value="(v: number) => setStyle('lineHeight', v)"
          />
        </div>
        <span class="prop-value">{{ (style?.lineHeight ?? DEFAULT_LINE_HEIGHT).toFixed(1) }}</span>
        <button
          v-if="mode === 'content'"
          type="button"
          class="follow-pill"
          :class="{ on: followMap.lineHeight }"
          :title="followMap.lineHeight ? '当前跟随章节，点击改为自定义' : '当前自定义，点击恢复跟随章节'"
          @click="setFollow('lineHeight', !followMap.lineHeight)"
        >
          {{ followMap.lineHeight ? '跟随' : '自定义' }}
        </button>
      </div>
    </div>

    <div v-if="mode === 'section'" v-show="tab === 'title'" class="style-pane">
      <div class="prop-row">
        <span class="prop-chip"><IconGlyph name="heading" :size="13" /></span>
        <span class="prop-label">标题字号</span>
        <div class="prop-control">
          <n-slider
            :value="sectionStyle?.titleSize ?? DEFAULT_TITLE_SIZE"
            :min="12"
            :max="100"
            :step="1"
            :tooltip="false"
            @update:value="(v: number) => setStyle('titleSize', v)"
          />
        </div>
        <span class="prop-value">{{ sectionStyle?.titleSize ?? DEFAULT_TITLE_SIZE }}px</span>
      </div>

      <div class="prop-row">
        <span class="prop-chip"><IconGlyph name="underline" :size="13" /></span>
        <span class="prop-label">标题横线</span>
        <div class="prop-control prop-control-right">
          <n-switch
            :value="sectionStyle?.titleUnderline ?? DEFAULT_TITLE_UNDERLINE"
            @update:value="(v: boolean) => setStyle('titleUnderline', v)"
          >
            <template #checked>开</template>
            <template #unchecked>关</template>
          </n-switch>
        </div>
      </div>
    </div>

    <div v-show="tab === 'spacing'" class="style-pane">
      <div class="prop-row">
        <span class="prop-chip"><IconGlyph name="arrow-up-down" :size="13" /></span>
        <span class="prop-label">块间距</span>
        <div class="prop-control" :class="{ disabled: mode === 'content' && followMap.gap }">
          <n-slider
            :value="style?.gap ?? DEFAULT_GAP"
            :min="0"
            :max="36"
            :step="2"
            :disabled="mode === 'content' && followMap.gap"
            :tooltip="false"
            @update:value="(v: number) => setStyle('gap', v)"
          />
        </div>
        <span class="prop-value">{{ style?.gap ?? DEFAULT_GAP }}px</span>
        <button
          v-if="mode === 'content'"
          type="button"
          class="follow-pill"
          :class="{ on: followMap.gap }"
          :title="followMap.gap ? '当前跟随章节，点击改为自定义' : '当前自定义，点击恢复跟随章节'"
          @click="setFollow('gap', !followMap.gap)"
        >
          {{ followMap.gap ? '跟随' : '自定义' }}
        </button>
      </div>

      <div v-if="mode === 'section'" class="prop-row">
        <span class="prop-chip"><IconGlyph name="arrow-up-down" :size="13" /></span>
        <span class="prop-label">章节间距</span>
        <div class="prop-control">
          <n-slider
            :value="sectionStyle?.spaceBefore ?? DEFAULT_CHAPTER_GAP"
            :min="0"
            :max="60"
            :step="2"
            :tooltip="false"
            @update:value="(v: number) => setStyle('spaceBefore', v)"
          />
        </div>
        <span class="prop-value">{{ sectionStyle?.spaceBefore ?? DEFAULT_CHAPTER_GAP }}px</span>
      </div>
    </div>

  </div>
</template>

<style scoped>
.style-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 2px;
}

.style-tabs {
  display: flex;
  gap: 2px;
  padding: 2px;
  border-radius: 8px;
  background: var(--surface-soft);
}
.style-tab {
  flex: 1;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.style-tab:hover {
  color: var(--text);
}
.style-tab.active {
  background: var(--panel-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.08);
}

.style-pane {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.prop-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 4px;
}
.prop-chip {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: var(--primary-soft);
  color: var(--primary);
}
.prop-label {
  flex: none;
  width: 52px;
  font-size: 12px;
  color: var(--text-secondary);
}
.prop-control {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}
.prop-control-right {
  justify-content: flex-end;
}
.prop-control.disabled {
  opacity: 0.45;
}
.prop-control :deep(.n-slider) {
  flex: 1;
}
.prop-value {
  flex: none;
  width: 34px;
  text-align: right;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.follow-pill {
  flex: none;
  height: 20px;
  padding: 0 7px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel-bg);
  font-size: 10.5px;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.follow-pill:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.follow-pill.on {
  border-color: var(--primary);
  background: var(--primary-faint);
  color: var(--primary);
  font-weight: 600;
}
</style>
