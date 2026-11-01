/**
 * 时间展示工具（简历库列表、备份文件夹状态共用）。
 */

/** 相对时间：刚刚 / 12 分钟前 / 3 小时前 / 2 天前 / 2026/11/2 */
export function formatRelativeTime(timestamp: number): string {
  if (!timestamp) return '—'
  const diff = Date.now() - timestamp
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return new Date(timestamp).toLocaleDateString('zh-CN')
}

/** 绝对时间：2026/11/2 14:30（设置页的“最近同步”用） */
export function formatDateTime(timestamp: number): string {
  if (!timestamp) return '尚未同步'
  return new Date(timestamp).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
