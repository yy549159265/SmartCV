/**
 * 简历名称 —— 编辑页顶部改名、优化页导出共用的全局名称。
 *
 * 用途：导出的 PDF / JSON 文件名（见 OptimizePage 的导出逻辑），
 * 只存在浏览器本地（useStorage），不写入简历数据本身。
 * 模块级 ref：编辑页改完名字，优化页导出立刻生效。
 */
import { useStorage } from '@vueuse/core'
import { sanitizeFileTitle } from '@/utils/filename'

/** 简历名称（默认「我的简历」） */
export const resumeName = useStorage('smartcv-resume-name', '我的简历')

/** 文件名安全化：去掉路径分隔符等非法字符；清空后回退默认名 */
export function resumeFilename(): string {
  return sanitizeFileTitle(resumeName.value, '我的简历')
}
