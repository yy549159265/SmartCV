import { useStorage } from '@vueuse/core'

/** 流程图里三类光点箭头：采集入面板、面板进报告、报告节点进章节。 */
export type MotionChannel = 'bus' | 'report' | 'flow'
export type MotionMode = 'fixed' | 'random'

export const MOTION_CHANNELS: { key: MotionChannel; label: string }[] = [
  { key: 'bus', label: '主链路' },
  { key: 'report', label: '报告' },
  { key: 'flow', label: '成稿' },
]

export interface MarketMotionSettings {
  mode: MotionMode
  /** 固定模式下每条链路的颜色；随机模式忽略，改从调色板里抽。 */
  colors: Record<MotionChannel, string>
  /** 弧线上下方向是否逐条随机；关闭后固定模式保持调用方给定的弯曲方向。 */
  directionRandom: boolean
  tail: number
  duration: number
  width: number
  alpha: number
}

export const DEFAULT_MARKET_MOTION: MarketMotionSettings = {
  mode: 'fixed',
  colors: {
    bus: '#4753c7',
    report: '#4753c7',
    flow: '#3f8f5a',
  },
  directionRandom: true,
  tail: 300,
  duration: 780,
  width: 7,
  alpha: 0.8,
}

/** 随机模式调色板：保持冷色为主，少量暖色点缀，浅色背景上都能看清。 */
export const RANDOM_MOTION_COLORS = [
  '#4753c7',
  '#3f8f5a',
  '#0891b2',
  '#d97706',
  '#db2777',
  '#7c3aed',
]

export const RANDOM_RANGES = {
  /** 弧线弯曲幅度；真正落值时再随机左右方向。 */
  bow: [50, 240] as const,
  tail: [120, 480] as const,
  duration: [380, 1200] as const,
  width: [4, 10] as const,
  alpha: [0.55, 1] as const,
}

export const marketMotion = useStorage<MarketMotionSettings>(
  'smartcv-market-motion',
  DEFAULT_MARKET_MOTION,
  undefined,
  { mergeDefaults: true },
)

// 老版本存的是没有 directionRandom 的对象：补成开启，保证升级后方向仍然随机。
if (typeof marketMotion.value.directionRandom !== 'boolean') {
  marketMotion.value = { ...marketMotion.value, directionRandom: true }
}

export function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min)
}

export function pickRandomMotionColor(): string {
  return RANDOM_MOTION_COLORS[Math.floor(Math.random() * RANDOM_MOTION_COLORS.length)]
}

let lastBowSign: 1 | -1 = Math.random() < 0.5 ? -1 : 1

/**
 * 弧线方向的随机符号：+1 向下弯，-1 向上弯。
 *
 * 纯 50/50 逐条抛硬币时，「一上一下」的严格交替会频繁出现，肉眼看着像固定规律。
 * 这里保留 30% 沿用上一次方向的惯性，让同向箭头能连续出现，再配合幅度抖动，
 * 整体更像随机散布而不是机械翻转。
 */
export function randomBowSign(): 1 | -1 {
  if (Math.random() >= 0.3) {
    lastBowSign = Math.random() < 0.5 ? -1 : 1
  }
  return lastBowSign
}

/**
 * 在基准弯曲幅度上套一个 70%–130% 的抖动，并随机决定向上还是向下弯。
 * 固定模式只抖动方向与幅度，颜色 / 拖尾 / 速度仍按配置固定。
 */
export function withRandomDirection(base: number): number {
  const magnitude = Math.max(12, Math.abs(base))
  const jitter = 0.7 + Math.random() * 0.6
  return Math.round(magnitude * jitter) * randomBowSign()
}

/** 一次随机抽取：每个箭头起飞时单独调用，颜色 / 方向 / 长短 / 速度都独立。 */
export function randomMotionStyle() {
  const bow = Math.round(randomBetween(...RANDOM_RANGES.bow))
  return {
    color: pickRandomMotionColor(),
    // 正负号决定弧线向上还是向下弯，每个箭头独立。
    bow: bow * randomBowSign(),
    tail: Math.round(randomBetween(...RANDOM_RANGES.tail)),
    duration: Math.round(randomBetween(...RANDOM_RANGES.duration)),
    width: Math.round(randomBetween(...RANDOM_RANGES.width) * 10) / 10,
    alpha: Math.round(randomBetween(...RANDOM_RANGES.alpha) * 100) / 100,
  }
}
