import type { EvidenceLink } from '@/types/market'

/** 来源链接的悬停说明：标题 · 站点 · 发布时间（有才显示）；补充网址再附上备注。 */
export function linkTitle(link: EvidenceLink): string {
  const parts = [link.title, link.site, link.published]
  if (link.userTag?.note) parts.push(`备注：${link.userTag.note}`)
  return parts.filter(Boolean).join(' · ')
}
