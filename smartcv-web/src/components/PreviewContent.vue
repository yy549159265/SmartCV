<script setup lang="ts">
import { computed, type CSSProperties } from 'vue'
import DiffActionButton from './DiffActionButton.vue'
import { effectiveContentStyle } from '@/utils/style'
import { renderMarkdown } from '@/utils/markdown'
import { diffAttr as resolveDiffAttr, type ChangeView, type DiffMark } from '@/utils/resumeDiff'
import type { Content, Section, LayoutWindow } from '@/types'

const props = defineProps<{
  section: Section
  row: LayoutWindow
  content: Content
  diffMark?: DiffMark
  diffView?: ChangeView
  diffUnits?: Record<number, DiffMark>
  diffUnitViews?: Record<number, ChangeView>
  unitDiffs?: Record<number, string>
}>()

const diffAttr = computed(() => resolveDiffAttr(props.diffMark, props.diffView))

const unitAttr = (i: number) => resolveDiffAttr(props.diffUnits?.[i], props.diffUnitViews?.[i])
const unitView = (i: number) => props.diffUnitViews?.[i]

const unitDiffHtml = (i: number): string | null => {
  if (props.diffUnitViews?.[i]?.reverted) return null
  return props.unitDiffs?.[i] ?? null
}

const eff = computed(() => effectiveContentStyle(props.row, props.section, props.content))

const md = (text?: unknown) => renderMarkdown(text)

const cols = computed(() => props.content.content.columns ?? [])

const JUSTIFY_MAP = {
  left: 'flex-start',
  center: 'center',
  right: 'flex-end',
} as const

const imageAlign = computed(() => props.content.content.imageAlign ?? 'left')
const IMAGE_ALIGN_MAP = { left: 'flex-start', center: 'center', right: 'flex-end' } as const

const rootStyle = computed(() => {
  const horizontal = props.row.layout === 'horizontal'
  return {
    fontSize: `${eff.value.fontSize}px`,
    color: eff.value.color,
    lineHeight: eff.value.lineHeight,
    textAlign: eff.value.textAlign,
    marginRight: horizontal ? `${eff.value.gap}px` : '0px',
    marginBottom: `${eff.value.gap}px`,
  }
})

const listItems = computed(() =>
  (props.content.content.items ?? []).map((item) =>
    typeof item === 'string'
      ? { text: item, indent: 0 }
      : { text: item.text ?? '', indent: item.indent ?? 0 },
  ),
)

const INDENT_STEP = 24

const imageStyle = computed<CSSProperties>(() => {
  const shape = props.content.content.imageShape === 'circle'
    ? 'circle'
    : props.content.content.imageShape === 'original'
      ? 'original'
      : 'rounded'
  const size = props.content.content.imageSize ?? 96
  return {
    width: `${size}px`,
    ...(shape === 'circle' ? { height: `${size}px` } : {}),
    borderRadius: shape === 'circle' ? '50%' : shape === 'rounded' ? '10px' : '0px',
    objectFit: shape === 'circle' ? 'cover' : 'contain',
  }
})
</script>

<template>
  <div
    class="preview-content md-body"
    :class="{ 'diff-action-host': !!diffView }"
    :data-diff="diffAttr"
    :data-diff-key="diffView ? `content:${content.id}` : undefined"
    :style="rootStyle"
  >
    <DiffActionButton v-if="diffView" class="diff-action-float" :view="diffView" />

    <div
      v-if="content.type === 'iconText'"
      class="pb-icontext"
      :class="{ 'diff-action-host': !!unitView(0) }"
      :data-diff="unitAttr(0)"
      :data-diff-key="unitView(0) ? `unit:${content.id}:0` : undefined"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <DiffActionButton v-if="unitView(0)" class="diff-action-float" :view="unitView(0)!" />
      <span v-if="content.content.icon" class="pb-icon" v-html="content.content.icon" />
      <div class="pb-text" v-html="unitDiffHtml(0) || md(content.content.text)" />
      <div v-if="(content.content.tags ?? []).length" class="pb-tags">
        <span v-for="t in content.content.tags" :key="t" class="pb-tag">{{ t }}</span>
      </div>
    </div>

    <div
      v-else-if="content.type === 'twoColumn'"
      class="pb-twocol"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <template v-for="(col, i) in cols" :key="i">
        <span v-if="i > 0 && content.content.separator" class="pb-sep">
          {{ content.content.separator }}
        </span>
        <div
          class="pb-col-wrap"
          :data-diff="unitAttr(i)"
          :data-diff-key="unitView(i) ? `unit:${content.id}:${i}` : undefined"
        >
          <DiffActionButton v-if="unitView(i)" class="diff-action-float" :view="unitView(i)!" />
          <div class="pb-col" v-html="unitDiffHtml(i) || md(col)" />
        </div>
      </template>
    </div>

    <div
      v-else-if="content.type === 'timeRange'"
      class="pb-timerange"
      :data-diff="unitAttr(0)"
      :data-diff-key="unitView(0) ? `unit:${content.id}:0` : undefined"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <DiffActionButton v-if="unitView(0)" class="diff-action-float" :view="unitView(0)!" />
      <span>{{ content.content.start }}</span>
      <span class="pb-dash"> - </span>
      <span>{{ content.content.end }}</span>
    </div>

    <div
      v-else-if="content.type === 'tag'"
      class="pb-tags"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <span
        v-for="(t, i) in content.content.tags"
        :key="i"
        class="pb-tag"
        :data-diff="unitAttr(i)"
        :data-diff-key="unitView(i) ? `unit:${content.id}:${i}` : undefined"
      >
        {{ t }}
        <DiffActionButton v-if="unitView(i)" class="diff-action-float" :view="unitView(i)!" />
      </span>
    </div>

    <div v-else-if="content.type === 'listText'" class="pb-list">
      <div
        v-for="(item, i) in listItems"
        :key="i"
        class="pb-list-item"
        :data-diff="unitAttr(i)"
        :data-diff-key="unitView(i) ? `unit:${content.id}:${i}` : undefined"
        :style="{
          marginLeft: `${(item.indent ?? 0) * INDENT_STEP}px`,
          justifyContent: JUSTIFY_MAP[eff.textAlign],
        }"
      >
        <DiffActionButton v-if="unitView(i)" class="diff-action-float" :view="unitView(i)!" />
        <span class="pb-list-marker">
          {{ content.content.listType === 'ordered' ? `${i + 1}.` : '•' }}
        </span>
        <span class="pb-list-text" v-html="unitDiffHtml(i) || md(item.text)" />
      </div>
    </div>

    <div
      v-else-if="content.type === 'image'"
      class="pb-image"
      :style="{ justifyContent: IMAGE_ALIGN_MAP[imageAlign] }"
    >
      <img
        v-if="content.content.image"
        :src="content.content.image"
        :style="imageStyle"
        alt="图片"
      />
      <span v-else class="pb-image-empty">（未上传图片）</span>
    </div>

    <div
      v-else-if="content.type === 'spacer'"
      class="pb-spacer"
      :style="{ height: `${eff.fontSize * eff.lineHeight}px` }"
    />
  </div>
</template>

<style scoped>
.preview-content {
  min-width: 0;
}

.diff-action-host {
  position: relative;
}
.diff-action-float {
  position: absolute;
  top: calc(50% - 10px);
  left: -20px;
  z-index: 6;
}

.pb-icontext {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.pb-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5em;
  height: 1.5em;
  line-height: inherit;
}
.pb-icon :deep(svg) {
  width: 1.3em;
  height: 1.3em;
  display: block;
}
.pb-text {
  flex: 0 1 auto;
  min-width: 0;
  overflow-wrap: anywhere;
}

.pb-twocol {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.pb-col-wrap {
  min-width: 0;
}
.pb-col {
  flex: 0 1 auto;
  min-width: 0;
  overflow-wrap: anywhere;
}
.pb-sep {
  flex: none;
  opacity: 0.6;
}

.pb-timerange {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
}
.pb-dash {
  margin: 0 6px;
  color: inherit;
  opacity: 0.6;
}

.pb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pb-tag {
  display: inline-content;
  padding: 0 9px;
  border-radius: 999px;
  background: #eef1f6;
  font-size: 0.92em;
  line-height: 1.5;
  white-space: nowrap;
}

.pb-image {
  display: flex;
  align-items: center;
}
.pb-image img {
  display: block;
  max-width: 100%;
}
.pb-image-empty {
  font-size: 0.85em;
  color: #9ca3af;
}

.pb-spacer {
  width: 100%;
}

.pb-list {
  margin: 0;
}
.pb-list-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 2px;
}
.pb-list-item:last-child {
  margin-bottom: 0;
}
.pb-list-marker {
  flex: none;
  min-width: 1.4em;
}
.pb-list-text {
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
