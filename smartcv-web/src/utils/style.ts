import {
  DEFAULT_CHAPTER_GAP,
  DEFAULT_COLOR,
  DEFAULT_FONT_SIZE,
  DEFAULT_GAP,
  DEFAULT_LINE_HEIGHT,
  DEFAULT_TEXT_ALIGN,
  DEFAULT_TITLE_SIZE,
  DEFAULT_TITLE_UNDERLINE,
} from './constants'
import type { Content, Section, LayoutWindow, ContentStyle, SectionStyle, TextAlign } from '@/types'

export interface EffectiveContentStyle {
  fontSize: number
  color: string
  lineHeight: number
  gap: number
  textAlign: TextAlign
}

export interface EffectiveSectionStyle extends EffectiveContentStyle {
  titleSize: number
  spaceBefore: number
  titleUnderline: boolean
}

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
    titleUnderline: s.titleUnderline ?? DEFAULT_TITLE_UNDERLINE,
  }
}

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

export function isFollowing(key: keyof ContentStyle, style: ContentStyle): boolean {
  return style[key] === undefined
}
