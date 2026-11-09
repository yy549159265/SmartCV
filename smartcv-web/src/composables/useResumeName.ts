import { useStorage } from '@vueuse/core'
import { sanitizeFileTitle } from '@/utils/filename'

export const resumeName = useStorage('smartcv-resume-name', '我的简历')

export function resumeFilename(): string {
  return sanitizeFileTitle(resumeName.value, '我的简历')
}
