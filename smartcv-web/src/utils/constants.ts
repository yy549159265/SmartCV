/**
 * 全局常量
 * 集中放各种"魔法数字"：A4 尺寸、默认样式值等。
 * 想改默认值，改这里就行，组件里不会散落重复的常量。
 */
import type { ContentType, SectionLayout, TextAlign } from '@/types'

/* ---------- 纸张尺寸（单位 px，按 96dpi 换算） ---------- */

/** 默认纸面宽度：标准 A4 纵向 794px（用户可在编辑页工具栏调宽，高度按 A4 纵向比例联动，见 composables/usePageSize） */
export const PAGE_WIDTH = 794
/** A4 纸面高度：297mm ≈ 1123px（主页 hero / 示例库等固定展示仍按标准 A4 渲染） */
export const PAGE_HEIGHT = 1123
/** 纸张四周留白（页边距） */
export const PAGE_PADDING = 48

/* ---------- 默认样式（当章节、内容都没有设置时使用；紧凑取向，让标准 A4 一页能放下更多内容） ---------- */

/** 默认正文字号 */
export const DEFAULT_FONT_SIZE = 14
/** 默认标题字号 */
export const DEFAULT_TITLE_SIZE = 20
/** 默认：标题下方显示横线（恒为满行长度） */
export const DEFAULT_TITLE_UNDERLINE = true
/** 默认文字颜色 */
export const DEFAULT_COLOR = '#334155'
/** 默认行距倍数 */
export const DEFAULT_LINE_HEIGHT = 1.25
/** 默认块间距 */
export const DEFAULT_GAP = 4
/** 默认文字位置 */
export const DEFAULT_TEXT_ALIGN: TextAlign = 'left'
/** 默认章节间距（本章节与上一个章节之间的距离；滑块可 0~60 自由调） */
export const DEFAULT_CHAPTER_GAP = 0

/* ---------- 展示用文案 ---------- */

/** 内容类型的显示名（组件库、提示文案用） */
export const CONTENT_TYPE_NAMES: Record<ContentType, string> = {
  iconText: '图标文字',
  twoColumn: '分栏',
  timeRange: '时间段',
  tag: '标签',
  listText: '列表文字',
  image: '图片',
  spacer: '占位',
}

