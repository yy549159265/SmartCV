/**
 * 全局类型定义 —— 简历数据模型
 *
 * 整份简历数据是一棵三层树：
 *   Resume（简历）
 *     └─ Section[]（章节：章节，页面级）
 *          └─ LayoutWindow[]（布局窗口：章节内的布局容器，每个可独立选横/竖）
 *               └─ Content[]（内容：内容单元）
 *
 * 重要概念（任务要求，务必记住）：
 *  1. 内容的【类型】是通用形态，只描述"长什么样"，与具体内容无关；
 *  2. 【预设模板】只是「类型 + 默认内容」的命名组合（如"联系电话"预设 = iconText 类型 + 一个号码）；
 *  3. 组件渲染时只认 content.type，永远不认预设名 —— 代码里不会出现"联系电话"这类写死的判断。
 */

/** 内容的通用类型：按"长什么样"划分 */
export type ContentType = 'iconText' | 'twoColumn' | 'timeRange' | 'tag' | 'listText' | 'image' | 'spacer'

/** 章节内部内容的布局模式：横向均分 / 竖向堆叠 */
export type SectionLayout = 'horizontal' | 'vertical'

/** 文字对齐方式：左 / 中 / 右 */
export type TextAlign = 'left' | 'center' | 'right'

/** 列表文字型的列表样式：圆点无序 / 数字有序 */
export type ListStyle = 'bullet' | 'ordered'

/** 列表文字型的一条列表项 */
export interface ListItem {
  /** 列表项文字（支持 Markdown） */
  text: string
  /** 缩进层级：0 = 顶格，1 = 缩进一级，2 = 缩进两级（最多两级） */
  indent?: number
}

/**
 * 内容的内容。
 * 所有类型共用一个对象，每个类型只读取自己需要的字段：
 *  - iconText  读取 icon / text
 *  - twoColumn 读取 columns（各栏文字）/ separator（栏与栏之间的分隔符）
 *  - timeRange 读取 start / end
 *  - tag       读取 tags
 *  - listText  读取 listType / items（每项 = { text, indent }）
 */
export interface ContentData {
  /** iconText：图标（emoji 即可，留空 = 不显示图标） */
  icon?: string
  /** iconText：文字内容（支持 Markdown） */
  text?: string
  /** twoColumn：各栏文字（每栏一个字符串；栏数任意，每栏平均分配宽度） */
  columns?: string[]
  /** twoColumn：栏与栏之间的分隔符（如 "|"、"·"、" / "；留空 = 不显示分隔符） */
  separator?: string
  /** timeRange：开始时间 */
  start?: string
  /** timeRange：结束时间 */
  end?: string
  /** tag：标签数组 */
  tags?: string[]
  /** listText：列表样式 */
  listType?: ListStyle
  /** listText：列表项（每项支持 Markdown 与缩进层级） */
  items?: ListItem[]
  /** image：图片数据（dataURL），上传图片内容用（头像等） */
  image?: string
  /** image：图片显示尺寸（px，取图片宽度，默认 96） */
  imageSize?: number
  /** image：图片形状（圆形 / 圆角 / 原图；头像照片一般是长方形，默认圆角） */
  imageShape?: 'circle' | 'rounded' | 'original'
  /** image：图片对齐位置（左 / 中 / 右） */
  imageAlign?: TextAlign
}

/** 基础样式：章节与内容共有的部分 */
export interface BaseStyle {
  /** 字体大小（px） */
  fontSize?: number
  /** 文字颜色（十六进制） */
  color?: string
  /** 行距（倍数，1.6 表示 1.6 倍行高） */
  lineHeight?: number
  /** 文字位置：左 / 中 / 右（继承规则与字号一致） */
  textAlign?: TextAlign
}

/**
 * 章节样式。
 * 继承规则：章节的 fontSize / color / lineHeight / gap 会"继承"给内部所有内容，
 * 内容自己的设置优先于继承值；titleSize（标题字号）只属于章节自己，不继承。
 */
export interface SectionStyle extends BaseStyle {
  /** 章节标题字号（px），独立设置 */
  titleSize?: number
  /** 内部内容之间的间距（px） */
  gap?: number
  /** 本章节与上一个章节之间的间距（px，默认 0） */
  spaceBefore?: number
}

/** 内容样式：字段优先于章节的继承值；不设置（undefined）就跟随章节 */
export interface ContentStyle extends BaseStyle {
  /** 覆盖章节继承下来的"块间距" */
  gap?: number
}

/** 内容：布局窗口内部的具体内容单元 */
export interface Content {
  id: string
  /** 固定标记：区分"真实内容"与组件库里的"预设对象"（预设没有 kind 字段） */
  kind: 'content'
  /** 通用类型，组件按它渲染 */
  type: ContentType
  /** 内容数据 */
  content: ContentData
  /** 样式设置（空对象 = 全部跟随章节继承） */
  style: ContentStyle
  /**
   * true = 紧贴模式：去掉本内容与"后一个组件"之间的间距
   * （横向窗口 = 去掉右边距；竖向窗口 = 去掉下边距），让后面的组件挨着它。
   */
  tight?: boolean
}

/**
 * 布局窗口：章节内部的一个布局容器。
 *
 * 两种用途（二选一）：
 *  - 叶子窗口：放内容（layout = 内容的排列方向）；
 *  - 容器窗口：放子窗口（rows 存在且非空，layout = 子窗口的排列方向）。
 *
 * 这样窗口可以任意嵌套组合：窗口横向并排（放在横向容器里）、
 * 上下堆叠（放在竖向容器里）、也可以里面再套窗口 —— 自由布局。
 */
export interface LayoutWindow {
  id: string
  /** 排列方向：叶子窗口 = 内容方向；容器窗口 = 子窗口方向 */
  layout: SectionLayout
  /** 叶子窗口：内容（容器窗口不用） */
  contents: Content[]
  /** 容器窗口：子窗口（叶子窗口不用，undefined = 叶子） */
  rows?: LayoutWindow[]
  /**
   * true = 紧贴模式：本窗口与"后一个窗口"之间不留间距
   * （横向容器 = 去掉右边距；竖向容器 = 去掉下边距）。
   */
  tight?: boolean
}

/** 章节（页面级）：简历的一个章节 */
export interface Section {
  id: string
  /** 固定标记：区分"真实章节"与组件库里的"预设对象" */
  kind: 'section'
  /** 章节标题 */
  title: string
  /** 样式设置 */
  style: SectionStyle
  /** 布局窗口：章节内可放多个，上下堆叠 */
  rows: LayoutWindow[]
  /** true = 强制分页：这个章节一定从下一页开头开始 */
  pageBreakBefore?: boolean
}

/** 整份简历 = 章节数组（全应用唯一数据源，存在 stores/resume.ts 里） */
export type Resume = Section[]
