/**
 * 全局轻提示（toast 消息）
 * 用 naive-ui 的"离散 API"：不依赖组件树里的 <n-message-provider>，
 * 任何地方 import { message } from '@/utils/feedback' 就能弹提示。
 */
import { createDiscreteApi } from 'naive-ui'

const { message } = createDiscreteApi(['message'])

export { message }
