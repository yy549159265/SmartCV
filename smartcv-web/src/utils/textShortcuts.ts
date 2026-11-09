const BOLD = '**'
const PLACEHOLDER = '加粗文字'

type TextField = HTMLInputElement | HTMLTextAreaElement

function replaceRange(field: TextField, start: number, end: number, text: string): void {
  field.focus()
  field.setSelectionRange(start, end)
  if (document.execCommand('insertText', false, text)) return

  const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setValue = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  setValue?.call(field, field.value.slice(0, start) + text + field.value.slice(end))
  field.dispatchEvent(new Event('input', { bubbles: true }))
}

export function toggleBold(field: TextField): void {
  const start = field.selectionStart ?? 0
  const end = field.selectionEnd ?? 0
  const value = field.value
  const selected = value.slice(start, end)

  if (selected.length >= 4 && selected.startsWith(BOLD) && selected.endsWith(BOLD)) {
    const inner = selected.slice(2, -2)
    replaceRange(field, start, end, inner)
    requestAnimationFrame(() => field.setSelectionRange(start, start + inner.length))
    return
  }

  if (value.slice(start - 2, start) === BOLD && value.slice(end, end + 2) === BOLD) {
    replaceRange(field, start - 2, end + 2, selected)
    requestAnimationFrame(() => field.setSelectionRange(start - 2, start - 2 + selected.length))
    return
  }

  const text = selected || PLACEHOLDER
  replaceRange(field, start, end, BOLD + text + BOLD)
  requestAnimationFrame(() => field.setSelectionRange(start + 2, start + 2 + text.length))
}

export function onMarkdownKeydown(e: KeyboardEvent): void {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return
  if (e.isComposing || e.key.toLowerCase() !== 'b') return
  const field = e.target
  if (!(field instanceof HTMLTextAreaElement) && !(field instanceof HTMLInputElement)) return
  e.preventDefault()
  toggleBold(field)
}
