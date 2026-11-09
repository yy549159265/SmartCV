import { createDiscreteApi } from 'naive-ui'
import { themeOverrides } from '@/styles/naive-theme'

const { message, dialog } = createDiscreteApi(['message', 'dialog'], {
  configProviderProps: { themeOverrides },
})

export { message, dialog }
