/**
 * 全局常量
 * 集中放各种"魔法数字"：A4 尺寸、默认样式值等。
 * 想改默认值，改这里就行，组件里不会散落重复的常量。
 */
import type { ContentType, SectionLayout, TextAlign } from '@/types'

/* ---------- A4 纸张尺寸（单位 px，按 96dpi 换算） ---------- */

/** A4 纸宽度：210mm ≈ 794px */
export const PAGE_WIDTH = 794
/** A4 纸高度：297mm ≈ 1123px */
export const PAGE_HEIGHT = 1123
/** 纸张四周留白（页边距） */
export const PAGE_PADDING = 48
/** 一页里内容区的宽度 = 纸宽 - 左右留白 */
export const CONTENT_WIDTH = PAGE_WIDTH - PAGE_PADDING * 2
/** 一页里内容区的高度 = 纸高 - 上下留白 */
export const CONTENT_HEIGHT = PAGE_HEIGHT - PAGE_PADDING * 2

/* ---------- 默认样式（当章节、内容都没有设置时使用） ---------- */

/** 默认正文字号 */
export const DEFAULT_FONT_SIZE = 15
/** 默认标题字号 */
export const DEFAULT_TITLE_SIZE = 25
/** 默认：标题下方显示横线（恒为满行长度） */
export const DEFAULT_TITLE_UNDERLINE = true
/** 默认文字颜色 */
export const DEFAULT_COLOR = '#334155'
/** 默认行距倍数 */
export const DEFAULT_LINE_HEIGHT = 1.2
/** 默认块间距 */
export const DEFAULT_GAP = 6
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

