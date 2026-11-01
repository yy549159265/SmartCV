/**
 * 文件下载工具：把数据导出成文件（JSON / PDF 等）。
 *
 * 绑定了「本地备份文件夹」时优先写入文件夹；写入失败 / 未绑定时用这里的
 * 浏览器下载兜底。
 */
import { message } from '@/utils/feedback'

/** 触发浏览器下载一个 Blob */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** 把数据序列化成 JSON 文件触发浏览器下载 */
export function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  downloadBlob(blob, filename)
  message.success(`已导出 ${filename}`)
}
