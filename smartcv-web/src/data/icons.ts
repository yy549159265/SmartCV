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
  name: string
  icons: string[]
}

export function brandSvg(icon: { path: string; hex: string }): string {
  return `<svg viewBox="0 0 24 24" width="1em" height="1em" xmlns="http://www.w3.org/2000/svg" fill="#${icon.hex}" aria-hidden="true"><path d="${icon.path}"/></svg>`
}

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

export const ALL_ICONS: string[] = ICON_GROUPS.flatMap((g) => g.icons)

export const LIST_TEXT_ICON =
  '<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" ' +
  'stroke-width="1.7" stroke-linecap="round" aria-hidden="true">' +
  '<circle cx="4.5" cy="6" r="1.2" fill="currentColor" stroke="none"/>' +
  '<circle cx="4.5" cy="12" r="1.2" fill="currentColor" stroke="none"/>' +
  '<circle cx="4.5" cy="18" r="1.2" fill="currentColor" stroke="none"/>' +
  '<path d="M8.5 6h11M8.5 12h11M8.5 18h11"/></svg>'
