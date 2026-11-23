/** 面试页的展示文案与简历指纹。 */

import type {
  AnchorKind,
  Dimension,
  FollowLevel,
  PackFocus,
  Priority,
  Scene,
  TokenUsage,
} from '@/api/interview'

export const DIMENSION_LABEL: Record<Dimension, string> = {
  project_background: '项目背景',
  business_need: '业务需求',
  architecture: '架构选型',
  implementation: '核心实现',
  difficulty: '技术难点',
  problem_solving: '问题解决',
  result: '项目成果',
  contribution: '个人贡献',
  tech_stack: '技术栈掌握',
  motivation: '求职动机',
  career_plan: '职业规划',
  salary: '薪资',
  stability: '稳定性',
  authenticity: '项目真实性',
}

export const LEVEL_LABEL: Record<FollowLevel, string> = {
  L1: 'L1 细节',
  L2: 'L2 权衡',
  L3: 'L3 归因',
}

export const LEVEL_HINT: Record<FollowLevel, string> = {
  L1: '具体怎么做、边界条件与数据来源',
  L2: '为什么这样选、替代方案与代价',
  L3: '结果归因、个人贡献与条件变化',
}

export function levelHint(level: FollowLevel): string {
  return `${LEVEL_LABEL[level]}：${LEVEL_HINT[level]}`
}

export const KIND_LABEL: Record<AnchorKind, string> = {
  tech: '技术',
  result: '结果',
  architecture: '架构',
  metric: '指标',
  contribution: '贡献',
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  high: '重点',
  medium: '常规',
  low: '补充',
}

export const SCENE_LABEL: Record<Scene, string> = {
  project: '项目面试',
  comprehensive: '综合面试',
  checklist: '清单自测',
}

export const FOCUS_LABEL: Record<PackFocus, string> = {
  balanced: '均衡',
  business: '业务场景',
  tech: '实现细节',
  architecture: '架构设计',
  review: '复盘决策',
}

/** 综合面试用 balanced 占位，不额外展示，避免每个题包都挂一个无信息量的标签。 */
export function focusLabel(focus: PackFocus | null | undefined): string {
  if (!focus || focus === 'balanced') return ''
  return FOCUS_LABEL[focus] ?? ''
}

export const FINISH_LABEL: Record<string, string> = {
  all_done: '全部完成',
  user_end: '主动结束',
}

export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABEL[dimension as Dimension] ?? dimension
}

/**
 * FNV-1a 双种子，输入是稳定序列化的简历 JSON。
 *
 * 序列化时去掉所有节点 id：简历每次载入都会重新生成 id，同一份内容刷新后
 * 指纹若包含 id 就会变，之前保存的画像将永远对不上。指纹只认内容本身。
 */
export function resumeFingerprint(resume: unknown): string {
  const text = JSON.stringify(resume ?? [], (key, value) => (key === 'id' ? undefined : value))
  let a = 0x811c9dc5
  let b = 0x1000193
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i)
    a ^= code
    a = Math.imul(a, 0x01000193) >>> 0
    b ^= code + i
    b = Math.imul(b, 0x85ebca6b) >>> 0
  }
  return `${a.toString(16).padStart(8, '0')}${b.toString(16).padStart(8, '0')}`
}

export function mergeUsage(
  base: TokenUsage | null | undefined,
  delta: TokenUsage | null | undefined,
): TokenUsage {
  return {
    inputTokens: (base?.inputTokens ?? 0) + (delta?.inputTokens ?? 0),
    outputTokens: (base?.outputTokens ?? 0) + (delta?.outputTokens ?? 0),
    totalTokens: (base?.totalTokens ?? 0) + (delta?.totalTokens ?? 0),
    calls: (base?.calls ?? 0) + (delta?.calls ?? 0),
  }
}

/** 步骤旁的空间很小：千位以下显示原数，千 / 百万用一位小数。 */
export function formatTokenCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(Math.round(value))
}

export function usageTitle(usage: TokenUsage): string {
  return `输入 ${usage.inputTokens} · 输出 ${usage.outputTokens} · ${usage.calls} 次调用`
}

export function formatDateTime(value: number | string | null | undefined): string {
  if (!value) return ''
  const date = typeof value === 'number' ? new Date(value) : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}
