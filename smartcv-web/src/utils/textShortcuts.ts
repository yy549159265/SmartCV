/**
 * 文本框快捷键（Markdown 加粗）
 *
 * 只操作输入框里的纯文本：Ctrl/Cmd + B 在选区两侧加/去 **，
 * 预览仍由 markdown-it 统一渲染，不涉及任何内容结构或数据逻辑。
 */

const BOLD = '**'
/** 没有选中内容时插入的占位文字，插入后自动选中，直接打字即可覆盖 */
const PLACEHOLDER = '加粗文字'

type TextField = HTMLInputElement | HTMLTextAreaElement

/** 用原生插入替换 [start, end)：走 execCommand 可保留输入框自身的撤销记录 */
function replaceRange(field: TextField, start: number, end: number, text: string): void {
  field.focus()
  field.setSelectionRange(start, end)
  if (document.execCommand('insertText', false, text)) return

  // 兜底：execCommand 不可用时直接改 value，并派发 input 让 v-model 同步
  const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setValue = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  setValue?.call(field, field.value.slice(0, start) + text + field.value.slice(end))
  field.dispatchEvent(new Event('input', { bubbles: true }))
}

/** 切换选中文字的 Markdown 加粗（下一帧恢复选区，避开 v-model 重绘把光标甩到末尾） */
export function toggleBold(field: TextField): void {
  const start = field.selectionStart ?? 0
  const end = field.selectionEnd ?? 0
  const value = field.value
  const selected = value.slice(start, end)

  // 1）选中的就是 **...**：去掉标记
  if (selected.length >= 4 && selected.startsWith(BOLD) && selected.endsWith(BOLD)) {
    const inner = selected.slice(2, -2)
    replaceRange(field, start, end, inner)
    requestAnimationFrame(() => field.setSelectionRange(start, start + inner.length))
    return
  }

  // 2）光标/选区正好在 ** |...| ** 中间：去掉两侧标记
  if (value.slice(start - 2, start) === BOLD && value.slice(end, end + 2) === BOLD) {
    replaceRange(field, start - 2, end + 2, selected)
    requestAnimationFrame(() => field.setSelectionRange(start - 2, start - 2 + selected.length))
    return
  }

  // 3）其余情况：包裹选中内容；没选中就插入占位并选中
  const text = selected || PLACEHOLDER
  replaceRange(field, start, end, BOLD + text + BOLD)
  requestAnimationFrame(() => field.setSelectionRange(start + 2, start + 2 + text.length))
}

/** n-input 的 keydown 处理器：只拦截 Ctrl/Cmd + B，其余按键原样交给输入框 */
export function onMarkdownKeydown(e: KeyboardEvent): void {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return
  if (e.isComposing || e.key.toLowerCase() !== 'b') return
  const field = e.target
  if (!(field instanceof HTMLTextAreaElement) && !(field instanceof HTMLInputElement)) return
  e.preventDefault()
  toggleBold(field)
}
