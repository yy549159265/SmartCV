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

// ===== 撤销 / 重做历史（Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y） =====
// 在每次改动简历前，把"改动前"的快照压入撤销栈：
//   - 结构操作（增删/复制/移动/布局/样式/整章）→ 每次调用一步；
//   - 文字编辑（updateContent / updateSection）→ 按字段分组，
//     同一字段短时间内的连续输入只在开头存一份，打字不会一个字一个字地退。
const HISTORY_TEXT_GROUP_MS = 1200
const HISTORY_STRUCTURAL_ACTIONS = new Set([
  'clearAll',
  'importResume',
  'addSection',
  'removeSection',
  'duplicateSection',
  'moveSection',
  'addRow',
  'addRowFromPreset',
  'insertRowRelative',
  'moveRowByDrop',
  'removeRow',
  'setRowLayout',
  'updateRow',
  'moveRow',
  'addContent',
  'addBlankContent',
  'removeContent',
  'duplicateContent',
  'moveContent',
])
let lastTextEditKey = ''
let lastTextEditAt = 0

resumeStore.$onAction(({ name, args }) => {
  if (HISTORY_STRUCTURAL_ACTIONS.has(name)) {
    resumeStore.pushSnapshot()
    return
  }
  if (name !== 'updateContent' && name !== 'updateSection') return
  // updateContent(sectionId, contentId, patch) → 看 contentId；updateSection(id, patch) → 看 id
  const targetId = String(name === 'updateContent' ? args?.[1] : args?.[0])
  const now = Date.now()
  if (targetId !== lastTextEditKey || now - lastTextEditAt > HISTORY_TEXT_GROUP_MS) {
    resumeStore.pushSnapshot()
  }
  lastTextEditKey = targetId
  lastTextEditAt = now
})

// 页面关闭/刷新前立刻保存一次：防抖窗口（400ms）内关闭页面会丢最后一次修改，
// 这里兜底把还没写盘的内容补上。
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => resumeStore.saveToStorage())

  // Ctrl+Z 撤销 / Ctrl+Shift+Z、Ctrl+Y 重做。
  // 只在确有历史时才拦截，避免影响浏览器在其它输入框里的原生撤销。
  window.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey
    if (!mod) return
    const key = e.key.toLowerCase()
    if (key === 'z') {
      if (e.shiftKey) {
        if (resumeStore.redoStack.length > 0) {
          e.preventDefault()
          resumeStore.redo()
        }
      } else if (resumeStore.undoStack.length > 0) {
        e.preventDefault()
        resumeStore.undo()
      }
      return
    }
    if (key === 'y' && resumeStore.redoStack.length > 0) {
      e.preventDefault()
      resumeStore.redo()
    }
  })
}
