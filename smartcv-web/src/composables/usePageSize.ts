import { computed } from 'vue'
import { useStorage } from '@vueuse/core'
import { PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'

export const PAGE_RATIO = PAGE_HEIGHT / PAGE_WIDTH

export const PAGE_WIDTH_MIN = 620
export const PAGE_WIDTH_MAX = 1000

export const PAGE_WIDTH_PRESETS = [
  { label: '标准 A4', value: 794, size: '794×1123' },
  { label: '加宽', value: 900, size: '900×1273' },
  { label: '宽屏', value: 1000, size: '1000×1414' },
] as const

export const pageWidth = useStorage('smartcv-page-width-v2', PAGE_WIDTH)

export const pageHeight = computed(() => Math.round(pageWidth.value * PAGE_RATIO))

export const contentWidth = computed(() => pageWidth.value - PAGE_PADDING * 2)

export const contentHeight = computed(() => pageHeight.value - PAGE_PADDING * 2)
