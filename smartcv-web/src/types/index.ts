/**
 * 简历数据模型：Resume = Section[] → rows(LayoutWindow[]) → contents(Content[])。
 *
 * 分两套概念，不要混：
 *  - ContentType 描述「长什么样」（渲染只看它，代码里不写死「联系电话」这类判断）；
 *  - 预设（data/presets.ts）= ContentType + 默认内容 的命名组合，只用于组件库。
 */

export type ContentType = 'iconText' | 'twoColumn' | 'timeRange' | 'tag' | 'listText' | 'image' | 'spacer'

export type SectionLayout = 'horizontal' | 'vertical'

export type TextAlign = 'left' | 'center' | 'right'

export type ListStyle = 'bullet' | 'ordered'

export interface ListItem {
  text: string
  indent?: number
}

export interface ContentData {
  icon?: string
  text?: string
  columns?: string[]
  separator?: string
  start?: string
  end?: string
  tags?: string[]
  listType?: ListStyle
  items?: ListItem[]
  image?: string
  imageSize?: number
  imageShape?: 'circle' | 'rounded' | 'original'
  imageAlign?: TextAlign
}

export interface BaseStyle {
  fontSize?: number
  color?: string
  lineHeight?: number
  textAlign?: TextAlign
}

export interface SectionStyle extends BaseStyle {
  titleSize?: number
  gap?: number
  spaceBefore?: number
  titleUnderline?: boolean
}

export interface ContentStyle extends BaseStyle {
  gap?: number
}

export interface Content {
  id: string
  kind: 'content'
  type: ContentType
  content: ContentData
  style: ContentStyle
  tight?: boolean
}

export interface LayoutWindow {
  id: string
  layout: SectionLayout
  contents: Content[]
  rows?: LayoutWindow[]
  tight?: boolean
}

export interface Section {
  id: string
  kind: 'section'
  title: string
  icon?: string
  style: SectionStyle
  rows: LayoutWindow[]
  pageBreakBefore?: boolean
}

export type Resume = Section[]
