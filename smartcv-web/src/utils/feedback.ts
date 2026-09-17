/**
 * 全局轻提示（toast 消息 / 确认框）
 * 用 naive-ui 的"离散 API"：不依赖组件树里的 <n-message-provider> / <n-dialog-provider>，
 * 任何地方 import { message, dialog } from '@/utils/feedback' 就能弹出来。
 */
import { createDiscreteApi } from 'naive-ui'

const { message, dialog } = createDiscreteApi(['message', 'dialog'])

export { message, dialog }
