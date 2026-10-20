/**
 * 全局轻提示（toast 消息 / 确认框）
 * 用 naive-ui 的"离散 API"：不依赖组件树里的 <n-message-provider> / <n-dialog-provider>，
 * 任何地方 import { message, dialog } from '@/utils/feedback' 就能弹出来。
 */
import { createDiscreteApi } from 'naive-ui'
import { themeOverrides } from '@/styles/naive-theme'

const { message, dialog } = createDiscreteApi(['message', 'dialog'], {
  // 与 <n-config-provider> 使用同一套覆盖，toast / 确认框不会退回默认绿
  configProviderProps: { themeOverrides },
})

export { message, dialog }
