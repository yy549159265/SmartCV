/**
 * 图标库 —— 图标文字型内容的"图标选择器"数据源
 *
 * 按用途分组的图标集合：emoji 分组 + 品牌 logo（GitHub 等）。
 * 品牌 logo 来自 simple-icons（矢量路径 + 官方品牌色），
 * 渲染时用 v-html 直接内联成 SVG。
 * 想增删图标，只改这个文件即可（ContentCard 的图标选择器会自动跟随）。
 */
import {
  siBilibili,
  siDiscord,
  siGitee,
  siGithub,
  siJuejin,
  siSinaweibo,
  siTelegram,
  siWechat,
  siX,
  siYoutube,
  siZhihu,
} from 'simple-icons'

export interface IconGroup {
  /** 分组名（选择器里显示） */
  name: string
  /** 该组的图标列表（emoji 字符串或内联 SVG 字符串） */
  icons: string[]
}

/* ---------- 品牌 logo：把 simple-icons 的路径拼成内联 SVG ---------- */

/** 单个品牌图标 → 内联 SVG 字符串（填官方品牌色，24×24 视口，1em 大小随字号缩放） */
export function brandSvg(icon: { path: string; hex: string }): string {
  // 注意：必须写死 width/height（1em），否则 SVG 在 v-html / flex 布局里会被算成 0×0（空白）
  return `<svg viewBox="0 0 24 24" width="1em" height="1em" xmlns="http://www.w3.org/2000/svg" fill="#${icon.hex}" aria-hidden="true"><path d="${icon.path}"/></svg>`
}

/** 品牌图标组（GitHub、Gitee、掘金、X、B 站等常见平台） */
const BRAND_ICONS: string[] = [
  brandSvg(siGithub),
  brandSvg(siGitee),
  brandSvg(siJuejin),
  brandSvg(siX),
  brandSvg(siYoutube),
  brandSvg(siBilibili),
  brandSvg(siZhihu),
  brandSvg(siSinaweibo),
  brandSvg(siWechat),
  brandSvg(siTelegram),
  brandSvg(siDiscord),
]

export const ICON_GROUPS: IconGroup[] = [
  {
    name: '品牌',
    icons: BRAND_ICONS,
  },
  {
    name: '人物',
    icons: ['👤', '👨‍💻', '👩‍💻', '🧑‍🎓', '👨‍🎓', '👩‍🎓', '🙋', '💪', '🧑‍🏫', '👔'],
  },
  {
    name: '联系方式',
    icons: ['📞', '☎️', '📱', '✉️', '📧', '💬', '💌', '🖥️'],
  },
  {
    name: '地点',
    icons: ['📍', '🏠', '🏢', '🏫', '🏙️', '🌍', '🗺️', '🧭'],
  },
  {
    name: '学习',
    icons: ['🎓', '📚', '📖', '✏️', '📝', '🔬', '🧪', '💡', '🏅', '🥇'],
  },
  {
    name: '工作',
    icons: ['💼', '📅', '🗓️', '📋', '📊', '📈', '⚙️', '🛠️', '🏆', '📌'],
  },
  {
    name: '技能',
    icons: ['💻', '🎨', '🎵', '🎬', '🗣️', '🤝', '🚀', '🧩', '🛡️', '🔧'],
  },
  {
    name: '链接',
    icons: ['🔗', '🌐', '📎', '📇', '🐙', '🐦', '📺', '📷'],
  },
  {
    name: '其他',
    icons: ['✨', '⭐', '❤️', '🔥', '☕', '🍀', '🎯', '🧭', '⏰', '📦'],
  },
]

/** 扁平化后的全部图标（快速判断/遍历用） */
export const ALL_ICONS: string[] = ICON_GROUPS.flatMap((g) => g.icons)
