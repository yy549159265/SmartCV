/**
 * 纸面尺寸 —— 简历成品的页面宽高（实时预览 / 诊断简历页 / 导出 PDF 共用）。
 *
 * 和 previewZoom 一样是模块级 useStorage：全局共享、自动记忆到 localStorage。
 * 预览纸块、隐藏测量层、导出流、PDF 的 @page size 全部读这里，改一处全链生效。
 *
 * 比例规则：**高度永远 = 宽度 × A4 纵向比例（1123/794 ≈ 1.414）**。
 * 只调宽度，页面始终是竖长 A4 形，最宽时也不会变成近似正方形；
 * 宽度变化后测量层自身的 ResizeObserver 会自动触发重新分页，页数实时跟着变。
 */
import { computed } from 'vue'
import { useStorage } from '@vueuse/core'
import { PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'

/** A4 纵向比例（高/宽 ≈ 1.414）：任何宽度下都保持标准 A4 的竖长身形 */
export const PAGE_RATIO = PAGE_HEIGHT / PAGE_WIDTH

/** 可调范围（px）：620 保证内容区不低于 524px；1000 是宽屏上限（再宽页面过大，打印也不友好） */
export const PAGE_WIDTH_MIN = 620
export const PAGE_WIDTH_MAX = 1000

/** 快捷档位（编辑页工具栏的预设按钮；size = 宽×高，高度恒为 A4 纵向比例） */
export const PAGE_WIDTH_PRESETS = [
  { label: '标准 A4', value: 794, size: '794×1123' },
  { label: '加宽', value: 900, size: '900×1273' },
  { label: '宽屏', value: 1000, size: '1000×1414' },
] as const

/**
 * 当前纸面宽度（默认 = constants.PAGE_WIDTH，即标准 A4 794px）。
 * 存储 key 带 v2：v1 时代高度固定 1123、最宽可到 1200（接近正方形），
 * 比例规则变了，旧值不再适用，升级后重新回落到标准 A4。
 */
export const pageWidth = useStorage('smartcv-page-width-v2', PAGE_WIDTH)

/** 纸面高度 = 宽度 × A4 纵向比例（永远竖长，不会近似正方形） */
export const pageHeight = computed(() => Math.round(pageWidth.value * PAGE_RATIO))

/** 内容区宽度 = 纸宽 - 左右留白（测量层、对比弹窗等用） */
export const contentWidth = computed(() => pageWidth.value - PAGE_PADDING * 2)

/** 一页可用内容高度 = 纸高 - 上下留白（分页计算的单页容量） */
export const contentHeight = computed(() => pageHeight.value - PAGE_PADDING * 2)
