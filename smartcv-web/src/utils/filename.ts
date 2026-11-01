/**
 * 文件名相关的清洗工具。
 *
 * 备份文件夹里「文件名 = 简历名」，所以用户输入的名字必须变成 Windows /
 * macOS / Linux 都能用的安全文件名。规则和现有导出保持一致：
 *  - 去掉路径分隔符等非法字符；
 *  - 去掉结尾的点和空格（Windows 不允许）；
 *  - 限制长度，避免超过文件系统单个文件名的上限。
 */

/** Windows 不允许出现在文件名里的字符 */
const INVALID_CHARS = /[\\/:*?"<>|]/g

/**
 * 把用户输入的简历名清洗成安全的文件名主干（不含 .json / .pdf）。
 * 空字符串或全是非法字符时回退到 fallback。
 */
export function sanitizeFileTitle(input: string, fallback = '我的简历'): string {
  let title = (input ?? '')
    .trim()
    // 用户可能直接输入 xxx.json，先去掉扩展名，避免出现 xxx.json.json
    .replace(/\.(json|pdf|docx?|txt)$/i, '')
    .replace(INVALID_CHARS, '-')
    .replace(/[\u0000-\u001f]/g, '')
    // Windows 文件名不能以点或空格结尾
    .replace(/[. ]+$/g, '')
    .slice(0, 120)

  if (!title) title = fallback
  return title
}

/** 从 xxx.json 取出简历名（只用于备份文件夹里的 JSON 文件） */
export function fileTitle(fileName: string): string {
  return fileName.replace(/\.json$/i, '')
}
