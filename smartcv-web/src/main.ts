/**
 * 应用入口文件
 * 依次安装：
 *  1. Pinia        —— 状态管理（简历数据的单一数据源在 stores/resume.ts）
 *  2. naive-ui     —— UI 组件库（全量注册，模板里直接用 <n-button> 等，无需逐个 import）
 *  3. MotionPlugin —— @vueuse/motion 动画指令（v-motion）
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { MotionPlugin } from '@vueuse/motion'
import { useDebounceFn } from '@vueuse/core'
import naive from 'naive-ui'

import App from './App.vue'
import { useResumeStore } from '@/stores/resume'
import './styles/global.css'
// highlight.js 代码高亮主题（Markdown 渲染代码块用）
import 'highlight.js/styles/github.css'

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)
app.use(naive)
app.use(MotionPlugin)

app.mount('#app')

// 自动保存：监听简历数据的任何变化，防抖 400ms 后写入浏览器 localStorage。
// 这样刷新页面 / 关闭浏览器再打开，用户编辑的内容都还在（无需手动点保存）。
const resumeStore = useResumeStore(pinia)
const autoSave = useDebounceFn(() => resumeStore.saveToStorage(), 400)
resumeStore.$subscribe(() => autoSave())

// 页面关闭/刷新前立刻保存一次：防抖窗口（400ms）内关闭页面会丢最后一次修改，
// 这里兜底把还没写盘的内容补上。
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => resumeStore.saveToStorage())
}
