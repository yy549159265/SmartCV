<script setup lang="ts">
/**
 * 内容的"只读渲染版"（右侧预览 / 隐藏测量层共用）
 *
 * 【关键】渲染完全按 content.type 驱动：每个分支只判断类型，
 * 代码里不出现"个人介绍""教育经历"等预设名 —— 新增预设无需改这里。
 * 文本内容统一走 Markdown 渲染（utils/markdown.ts）。
 * 样式按"内容自己 > 章节继承 > 默认"计算（utils/style.ts）。
 * 横向/竖向的块间距取决于内容【所在布局窗口】的方向（row.layout）。
 *
 * 另外支持可选的 diffMark：「优化简历」页的对比弹窗用它把改动过的内容块高亮出来。
 * 不传（预览、分页测量层、PDF 导出三处都不传）时，渲染结果与没有这个属性时完全一致。
 *
 * 再细一层 diffUnits / diffUnitViews：后端一次 patch 只替换一个「文字单元」
 * （列表项 / 某一栏 / 标签…），这时只高亮那一行，不罩住整个内容块。
 */
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
  /** 差异标记：'added' | 'removed' | 'changed'；不传 = 未改动 */
  diffMark?: DiffMark
  /** 这处改动的操作态（对比弹窗用）；不传 = 只显示高亮、不能切换 */
  diffView?: ChangeView
  /** 内容内部逐个文字单元的标记（序号与后端坐标的 i 一致）；不传 = 不标单元 */
  diffUnits?: Record<number, DiffMark>
  /** 逐个文字单元的操作态；不传 = 只显示高亮、不能切换 */
  diffUnitViews?: Record<number, ChangeView>
}>()

/** 实际挂到 data-diff 上的标记：还原过的改动换成"已还原 / 已忽略"两档样式 */
const diffAttr = computed(() => resolveDiffAttr(props.diffMark, props.diffView))

/** 第 i 个文字单元：高亮 + 切换按钮（一次 patch 只改一个单元时用） */
const unitAttr = (i: number) => resolveDiffAttr(props.diffUnits?.[i], props.diffUnitViews?.[i])
const unitView = (i: number) => props.diffUnitViews?.[i]

/** 最终生效样式（已处理继承） */
const eff = computed(() => effectiveContentStyle(props.row, props.section, props.content))

/** Markdown 文本 → HTML（v-html 用） */
const md = (text?: unknown) => renderMarkdown(text)

/** 分栏型：各栏文字（栏数任意） */
const cols = computed(() => props.content.content.columns ?? [])

/** 文字位置 → flex 的 justify-content（图标文字 / 时间段 / 标签这些"行内排列"用） */
const JUSTIFY_MAP = {
  left: 'flex-start',
  center: 'center',
  right: 'flex-end',
} as const

/** 图片对齐：左 / 中 / 右（水平移动图片） */
const imageAlign = computed(() => props.content.content.imageAlign ?? 'left')
const IMAGE_ALIGN_MAP = { left: 'flex-start', center: 'center', right: 'flex-end' } as const

/** 根元素样式：字号/颜色/行距/文字位置 + 块间距（横向窗口用右边距，竖向窗口用下边距） */
const rootStyle = computed(() => {
  const horizontal = props.row.layout === 'horizontal'
  return {
    fontSize: `${eff.value.fontSize}px`,
    color: eff.value.color,
    lineHeight: eff.value.lineHeight,
    textAlign: eff.value.textAlign,
    // 横向窗口：块与块之间的水平间距；竖向窗口：块之间的垂直间距。
    // 横向窗口开启 flex-wrap 后块可能换行，所以下边距两种布局都给
    // （换行后行与行之间也要留空隙）。
    marginRight: horizontal ? `${eff.value.gap}px` : '0px',
    marginBottom: `${eff.value.gap}px`,
  }
})

/** 列表项（统一成 { text, indent } 对象形式，兼容旧数据里的纯字符串） */
const listItems = computed(() =>
  (props.content.content.items ?? []).map((item) =>
    typeof item === 'string'
      ? { text: item, indent: 0 }
      : { text: item.text ?? '', indent: item.indent ?? 0 },
  ),
)

/** 缩进层级：每级 24px（与编辑侧保持一致） */
const INDENT_STEP = 24

/**
 * 图片显示样式：
 *  - circle 圆形：裁成正方形 + 圆形（适合头像）；
 *  - rounded 圆角：保持原图比例 + 圆角（头像照片默认）；
 *  - original 原图：保持原图比例、不加圆角。
 * 兼容旧数据里的 'square'（当作圆角处理）。
 */
const imageStyle = computed<CSSProperties>(() => {
  const shape = props.content.content.imageShape === 'circle'
    ? 'circle'
    : props.content.content.imageShape === 'original'
      ? 'original'
      : 'rounded'
  const size = props.content.content.imageSize ?? 96
  return {
    width: `${size}px`,
    // 圆形要正方形裁剪；圆角/原图保持原图宽高比（不锁高度）
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
    :style="rootStyle"
  >
    <!-- 逐处切换：左上角浮出 ← / →（不参与布局，不影响排版与分页） -->
    <DiffActionButton v-if="diffView" class="diff-action-float" :view="diffView" />

    <!-- 图标文字型：图标 + 文字 + 可选标签（整体随"文字位置"设置左右移动） -->
    <div
      v-if="content.type === 'iconText'"
      class="pb-icontext"
      :class="{ 'diff-action-host': !!unitView(0) }"
      :data-diff="unitAttr(0)"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <!-- 单元级改动（后端只改了这段文字）：按钮浮在这一行左侧 -->
      <DiffActionButton v-if="unitView(0)" class="diff-action-float" :view="unitView(0)!" />
      <!-- 图标可能是 emoji，也可能是品牌 SVG（v-html 两种都能渲染） -->
      <span v-if="content.content.icon" class="pb-icon" v-html="content.content.icon" />
      <div class="pb-text" v-html="md(content.content.text)" />
      <div v-if="(content.content.tags ?? []).length" class="pb-tags">
        <span v-for="t in content.content.tags" :key="t" class="pb-tag">{{ t }}</span>
      </div>
    </div>

    <!-- 分栏型：任意多栏 + 分隔符，各栏按内容宽度排列（紧挨分隔符）；
         整体随"文字位置"设置左右移动 -->
    <div
      v-else-if="content.type === 'twoColumn'"
      class="pb-twocol"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <template v-for="(col, i) in cols" :key="i">
        <span v-if="i > 0 && content.content.separator" class="pb-sep">
          {{ content.content.separator }}
        </span>
        <div class="pb-col-wrap" :data-diff="unitAttr(i)">
          <DiffActionButton v-if="unitView(i)" class="diff-action-float" :view="unitView(i)!" />
          <div class="pb-col" v-html="md(col)" />
        </div>
      </template>
    </div>

    <!-- 时间段型：「开始时间 - 结束时间」（整体随"文字位置"设置左右移动） -->
    <div
      v-else-if="content.type === 'timeRange'"
      class="pb-timerange"
      :data-diff="unitAttr(0)"
      :style="{ justifyContent: JUSTIFY_MAP[eff.textAlign] }"
    >
      <DiffActionButton v-if="unitView(0)" class="diff-action-float" :view="unitView(0)!" />
      <span>{{ content.content.start }}</span>
      <span class="pb-dash"> - </span>
      <span>{{ content.content.end }}</span>
    </div>

    <!-- 标签型：标签芯片（整体随"文字位置"设置左右移动） -->
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
      >
        {{ t }}
        <DiffActionButton v-if="unitView(i)" class="diff-action-float" :view="unitView(i)!" />
      </span>
    </div>

    <!-- 列表文字型：圆点无序列表 / 数字有序列表，每项支持 Markdown 与缩进层级。
         标记（• / 1. 2.）不用浏览器的原生 ::marker，而是直接写成内容：
         浏览器里长得一样，且打印 PDF 时标记不会丢失 -->
    <div v-else-if="content.type === 'listText'" class="pb-list">
      <div
        v-for="(item, i) in listItems"
        :key="i"
        class="pb-list-item"
        :data-diff="unitAttr(i)"
        :style="{
          marginLeft: `${(item.indent ?? 0) * INDENT_STEP}px`,
          justifyContent: JUSTIFY_MAP[eff.textAlign],
        }"
      >
        <!-- 单元级改动：按钮浮在这一行左侧（后端坐标的 i = 这一项的序号） -->
        <DiffActionButton v-if="unitView(i)" class="diff-action-float" :view="unitView(i)!" />
        <span class="pb-list-marker">
          {{ content.content.listType === 'ordered' ? `${i + 1}.` : '•' }}
        </span>
        <span class="pb-list-text" v-html="md(item.text)" />
      </div>
    </div>

    <!-- 图片型：上传的图片（头像等），形状可选圆形 / 圆角 / 原图；
         对齐可选 左 / 中 / 右（水平移动图片） -->
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

    <!-- 占位组件：纯空白，高度 = 正文字号 × 行距（调整字号/行距即改变空白高度） -->
    <div
      v-else-if="content.type === 'spacer'"
      class="pb-spacer"
      :style="{ height: `${eff.fontSize * eff.lineHeight}px` }"
    />
  </div>
</template>

<style scoped>
.preview-content {
  min-width: 0; /* 横向布局里允许被压缩换行 */
}

/* ---- 对比弹窗：逐处切换按钮 ---- */
.diff-action-host {
  position: relative;
}
/* 浮在块的左边距里：不占布局宽高，所以不影响排版；贴着这段文字的开头，
   一眼能看出按钮管的是哪一处（放右上角时容易被当成右侧的 ✎ 角标）。 */
.diff-action-float {
  position: absolute;
  top: calc(50% - 10px);
  left: -20px;
  z-index: 6;
}

/* ---- 图标文字型 ---- */
.pb-icontext {
  display: flex;
  /* 垂直居中：图标（emoji / 品牌 SVG）与文字都对齐到同一光学中心。
     品牌 SVG 没有文字基线，按 baseline 对齐会让它"贴底上浮"、与 emoji 错位；
     居中后两者和文字都对齐，且行距变大时一起移动，不会出现"文字下沉、标签留在上面"。 */
  align-items: center;
  flex-wrap: wrap; /* 文字后面的标签放不下时换到下一行，而不是把文字挤扁 */
  gap: 10px;
}
.pb-icon {
  flex: none;
  /* 统一图标占位：emoji 和品牌 SVG 都用同样大小的盒子居中显示，
     这样"图标到文字"的间距两种图标完全一致，不会对不上。
     垂直居中由外层 .pb-icontext 的 align-items:center 统一负责 */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5em;
  height: 1.5em;
  line-height: inherit;
}
/* 品牌 SVG：稍放大到接近 emoji 的视觉大小（:deep 才能命中 v-html 插入的 svg） */
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

/* ---- 分栏型：各栏按内容宽度排列，紧挨着分隔符（不会散开占满整行） ---- */
.pb-twocol {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
/* 每栏外面包一层：给"这一栏改了"的高亮和切换按钮留定位基准（不传 marks 时无额外效果） */
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

/* ---- 时间段型 ---- */
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

/* ---- 标签型 ---- */
.pb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pb-tag {
  display: inline-content;
  padding: 1px 10px;
  border-radius: 999px;
  background: #eef1f6;
  font-size: 0.92em;
  line-height: 1.7;
  white-space: nowrap;
}

/* ---- 图片型 ---- */
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

/* ---- 占位组件 ---- */
.pb-spacer {
  width: 100%;
}

/* ---- 列表文字型 ---- */
.pb-list {
  margin: 0;
}
.pb-list-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 4px;
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
