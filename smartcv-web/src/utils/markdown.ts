/**
 * Markdown 渲染工具
 * 用 markdown-it 把文本转成 HTML 字符串，配合 v-html 显示；
 * 代码块高亮交给 highlight.js。
 *
 * 注意安全：html: false 表示不解析原始 HTML 标签（大模型/用户输入不可信），
 * 所有输出都会被 markdown-it 转义，避免 XSS。
 */
import MarkdownIt from 'markdown-it'
// 只引入"常用语言包"（约 35 种主流语言），比完整版小很多；
// 简历场景（js/ts/python/java 等）都覆盖，未收录的语言会走"只转义不高亮"的兜底。
import hljs from 'highlight.js/lib/common'

const md = new MarkdownIt({
  html: false, // 不解析内嵌 HTML，防 XSS
  breaks: true, // 单个换行符也转成 <br>，更符合中文输入习惯
  linkify: true, // 自动把网址变成链接
  highlight(str: string, lang: string): string {
    // 代码块高亮：语言支持时用 highlight.js，否则只转义显示
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang, ignoreIllegals: true }).value}</code></pre>`
      } catch {
        /* 高亮失败就走下面的兜底 */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

/** 把 Markdown 文本渲染成 HTML 字符串（配合 v-html 使用） */
export function renderMarkdown(text?: unknown): string {
  // 防御：只接受字符串（数据异常时返回空串，避免整个应用崩溃）
  if (typeof text !== 'string' || !text) return ''
  return md.render(text)
}
