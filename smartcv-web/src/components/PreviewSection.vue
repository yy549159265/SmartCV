<script setup lang="ts">
/**
 * 章节的"只读渲染版"（右侧预览页 / 隐藏测量层 / 页面碎片导出共用）
 *
 * 章节内部渲染多个"布局窗口"（rows），每个窗口独立横向/竖向，窗口之间上下堆叠。
 *
 * 除了渲染一整个章节，还支持只渲染其中的一段（页面碎片）：
 *  - 长章节（超过一页）会被 utils/pagination 按顶层行边界分成多段，
 *    第一段渲染标题，其它段只渲染行、不带标题与上下留白 —— 这样跨页排布时不会重复标题/留白。
 *
 * 注意：这里只有展示，没有任何编辑控件、边框按钮，高度和 A4 成品完全一致
 * —— 测量层正是靠它来算分页的。
 *
 * data-section-id / data-forced 属性由父组件传进来（Vue 会自动透传到根元素），
 * 测量层靠这两个属性认出每个章节并读取它的位置和高度。
 */
import { computed } from 'vue'
import PreviewLayoutWindow from './PreviewLayoutWindow.vue'
import { effectiveSectionStyle } from '@/utils/style'
import { computeTableCols } from '@/utils/layout'
import type { Section } from '@/types'

const props = withDefaults(
  defineProps<{
    section: Section
    /** 只渲染这几个布局窗口（长章节被切分时用）；不传 = 整章 */
    rowFrom?: number
    rowTo?: number
    /** 是否渲染章节标题（长章节只有第一片为 true） */
    showTitle?: boolean
    /** 是否渲染章节上边距 padding（只有第一片为 true） */
    topPad?: boolean
    /** 是否渲染章节下边距 padding（只有最后一片为 true） */
    bottomPad?: boolean
    /** 强制 margin-top（每页第一片由调用方置 0，避免页首额外留白） */
    spaceBefore?: number
  }>(),
  {
    showTitle: true,
    topPad: true,
    bottomPad: true,
  },
)

/** 顶层窗口列表算出的全局列数（横向容器用来均分格子宽度，用整章算，切分后仍对齐） */
const tableCols = computed(() => computeTableCols(props.section.rows))

/** 需要渲染的行（默认整章；切分时用 rowFrom/rowTo 取子集） */
const visibleRows = computed(() => {
  const all = props.section.rows
  if (props.rowFrom === undefined) return all
  const from = props.rowFrom
  const to = props.rowTo ?? all.length - 1
  return all.slice(from, to + 1)
})

/** 章节最终生效样式 */
const eff = computed(() => effectiveSectionStyle(props.section))

/** 标题样式：标题字号独立设置 */
const titleStyle = computed(() => ({
  fontSize: `${eff.value.titleSize}px`,
  color: eff.value.color,
}))

/** 章节样式：spaceBefore = 与上一个章节之间的间距（可由调用方覆盖） */
const sectionStyle = computed(() => ({
  marginTop: `${props.spaceBefore !== undefined ? props.spaceBefore : eff.value.spaceBefore}px`,
}))

/** 章节留白：顶部 4px / 底部 16px（与 measurement 里的 padding 常量保持一致） */
const padStyle = computed(() => ({
  paddingTop: props.topPad === false ? '0px' : '4px',
  paddingBottom: props.bottomPad === false ? '0px' : '16px',
}))
</script>

<template>
  <section class="preview-section" :style="[sectionStyle, padStyle]">
    <h3 v-if="showTitle !== false" class="preview-section-title" :style="titleStyle">{{ section.title }}</h3>
    <!-- 布局窗口树（递归渲染） -->
    <div class="preview-rows">
      <PreviewLayoutWindow
        v-for="row in visibleRows"
        :key="row.id"
        :section="section"
        :row="row"
        :table-cols="tableCols"
      />
    </div>
  </section>
</template>

<style scoped>
.preview-section {
  /* padding 由 inline style 动态控制（整章 = 4 上 / 16 下；切分时按需隐藏） */
}

.preview-section-title {
  margin: 0 0 8px;
  font-weight: 600;
}

/* 顶层窗口上下堆叠；章节间距由 spaceBefore（marginTop）控制，不用固定 gap */
.preview-rows {
  display: flex;
  flex-direction: column;
  gap: 0;
}
</style>
