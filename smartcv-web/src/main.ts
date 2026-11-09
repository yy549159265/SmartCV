/**
 * 应用入口：Pinia + naive-ui + Motion，并挂上自动保存与撤销/重做。
 *
 * 撤销栈规则：结构操作每次一步；文字编辑按字段 1200ms 内合并（连续打字只存一次）。
 */

import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import { MotionPlugin } from '@vueuse/motion'
import { useDebounceFn } from '@vueuse/core'
import naive from 'naive-ui'

import App from './App.vue'
import { useResumeStore } from '@/stores/resume'
import { useDocumentsStore } from '@/stores/documents'
import './styles/global.css'
import 'highlight.js/styles/github.css'

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)
app.use(naive)
app.use(MotionPlugin)

app.mount('#app')

const resumeStore = useResumeStore(pinia)
const documentsStore = useDocumentsStore(pinia)
const autoSave = useDebounceFn(() => resumeStore.saveToStorage(), 400)
watch(
  () => resumeStore.resume,
  () => {
    autoSave()
    documentsStore.scheduleSave()
  },
  { deep: true },
)

void documentsStore.init()

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
  const targetId = String(name === 'updateContent' ? args?.[1] : args?.[0])
  const now = Date.now()
  if (targetId !== lastTextEditKey || now - lastTextEditAt > HISTORY_TEXT_GROUP_MS) {
    resumeStore.pushSnapshot()
  }
  lastTextEditKey = targetId
  lastTextEditAt = now
})

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    resumeStore.saveToStorage()
    void documentsStore.saveNow({ silent: true })
  })

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
