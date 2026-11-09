const INVALID_CHARS = /[\\/:*?"<>|]/g

export function sanitizeFileTitle(input: string, fallback = '我的简历'): string {
  let title = (input ?? '')
    .trim()
    .replace(/\.(json|pdf|docx?|txt)$/i, '')
    .replace(INVALID_CHARS, '-')
    .replace(/[\u0000-\u001f]/g, '')
    .replace(/[. ]+$/g, '')
    .slice(0, 120)

  if (!title) title = fallback
  return title
}

export function fileTitle(fileName: string): string {
  return fileName.replace(/\.json$/i, '')
}
