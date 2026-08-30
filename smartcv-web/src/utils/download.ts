/**
 * 文件下载工具：把数据导出成文件（JSON 等）
 */
import { message } from '@/utils/feedback'

/** 把数据序列化成 JSON 文件触发浏览器下载 */
export function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  message.success(`已导出 ${filename}`)
}
