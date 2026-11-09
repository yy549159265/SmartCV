import type { ContentType, SectionLayout, TextAlign } from '@/types'

export const PAGE_WIDTH = 794
export const PAGE_HEIGHT = 1123
export const PAGE_PADDING = 48

export const DEFAULT_FONT_SIZE = 14
export const DEFAULT_TITLE_SIZE = 20
export const DEFAULT_TITLE_UNDERLINE = true
export const DEFAULT_COLOR = '#334155'
export const DEFAULT_LINE_HEIGHT = 1.25
export const DEFAULT_GAP = 4
export const DEFAULT_TEXT_ALIGN: TextAlign = 'left'
export const DEFAULT_CHAPTER_GAP = 0

export const CONTENT_TYPE_NAMES: Record<ContentType, string> = {
  iconText: '图标文字',
  twoColumn: '分栏',
  timeRange: '时间段',
  tag: '标签',
  listText: '列表文字',
  image: '图片',
  spacer: '占位',
}
