/**
 * 样式计算工具
 *
 * 实现任务要求的"样式继承规则"：
 *   章节的 字号 / 颜色 / 行距 / 块间距 会同步应用到内部所有内容；
 *   内容自己的设置优先于继承值；
 *   谁都没设置时，使用全局默认值。
 *
 * 优先级：内容自己的 > 章节的 > 全局默认
 */
import {
  DEFAULT_CHAPTER_GAP,
  DEFAULT_COLOR,
  DEFAULT_FONT_SIZE,
  DEFAULT_GAP,
  DEFAULT_LINE_HEIGHT,
  DEFAULT_TEXT_ALIGN,
  DEFAULT_TITLE_SIZE,
} from './constants'
import type { Content, Section, LayoutWindow, ContentStyle, SectionStyle, TextAlign } from '@/types'

/** 计算出的"最终样式"：所有字段都有值，可以直接拿来绑定 CSS */
export interface EffectiveContentStyle {
  fontSize: number
  color: string
  lineHeight: number
  gap: number
  textAlign: TextAlign
}

export interface EffectiveSectionStyle extends EffectiveContentStyle {
  titleSize: number
  /** 本章节与上一个章节之间的间距（px） */
  spaceBefore: number
}

/** 计算章节的最终样式（标题字号独立，其余字段用于继承） */
export function effectiveSectionStyle(section: Section): EffectiveSectionStyle {
  const s = section.style ?? {}
  return {
    titleSize: s.titleSize ?? DEFAULT_TITLE_SIZE,
    fontSize: s.fontSize ?? DEFAULT_FONT_SIZE,
    color: s.color ?? DEFAULT_COLOR,
    lineHeight: s.lineHeight ?? DEFAULT_LINE_HEIGHT,
    gap: s.gap ?? DEFAULT_GAP,
    textAlign: s.textAlign ?? DEFAULT_TEXT_ALIGN,
    spaceBefore: s.spaceBefore ?? DEFAULT_CHAPTER_GAP,
  }
}

/**
 * 计算内容的最终样式：内容自己的 > 章节的 > 默认。
 * row = 该内容所在的布局窗口（决定它是横向还是竖向排列）。
 */
export function effectiveContentStyle(row: LayoutWindow, section: Section, content: Content): EffectiveContentStyle {
  const gs = section.style ?? {}
  const bs = content.style ?? {}
  return {
    fontSize: bs.fontSize ?? gs.fontSize ?? DEFAULT_FONT_SIZE,
    color: bs.color ?? gs.color ?? DEFAULT_COLOR,
    lineHeight: bs.lineHeight ?? gs.lineHeight ?? DEFAULT_LINE_HEIGHT,
    gap: bs.gap ?? gs.gap ?? DEFAULT_GAP,
    textAlign: bs.textAlign ?? gs.textAlign ?? DEFAULT_TEXT_ALIGN,
  }
}

/**
 * 把一组样式补丁合并进目标样式对象。
 * 约定：补丁里值为 undefined 的字段 = "删除该字段"（恢复继承/默认值）。
 * 例子：mergeStyle(content.style, { fontSize: undefined }) 之后，
 *       content.style 里不再有 fontSize，effectiveContentStyle 会自动用章节的继承值。
 */
export function mergeStyle<T extends object>(target: T, patch: Partial<T> | undefined): void {
  if (!patch) return
  const record = target as Record<string, unknown>
  for (const key of Object.keys(patch) as (keyof T)[]) {
    const value = patch[key]
    if (value === undefined) {
      delete record[String(key)]
    } else {
      record[String(key)] = value
    }
  }
}

/** 供样式面板判断：内容的某个样式字段当前是否"跟随章节"（即自己没设置） */
export function isFollowing(key: keyof ContentStyle, style: ContentStyle): boolean {
  return style[key] === undefined
}
