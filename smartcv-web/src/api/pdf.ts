/**
 * 导出 PDF（后端生成）
 *
 * 流程：前端把"渲染好的整份简历 HTML"POST 给后端 /api/resume/pdf，
 * 后端用无头 Chromium（Playwright）打 PDF 直接返回 .pdf 文件，前端触发下载。
 *
 * 为什么发给后端的是 HTML 而不是简历 JSON：
 * 简历排版是前端这套 Vue 组件渲染的（flexbox / markdown / 缩进 / 标签），
 * 直接发渲染好的 HTML，后端只负责"打 PDF"，不存在排版复刻不一致的问题。
 * 图片已是 base64 内联在简历数据里，跟着 HTML 一起走，后端无需联网取图。
 */
import { apiErrorMessage } from '@/api/error'
import { apiFetch } from '@/api/http'

/**
 * 把简历流元素序列化成一份完整 HTML（内联全部样式表）。
 * 入参 flowEl：和预览同宽同边距的连续流容器（OptimizePage 的 .export-flow）。
 */
export function buildResumeHtml(flowEl: HTMLElement): string {
  const contentHtml = flowEl.outerHTML

  // 复制主文档所有样式表：全局样式、Vue 的 scoped 样式都带过去，
  // 后端打印的排版才和预览一致。（部分外部样式表读不了 cssRules，跳过）
  const sheetCss = Array.from(document.styleSheets)
    .map((sheet) => {
      try {
        return Array.from(sheet.cssRules)
          .map((rule) => rule.cssText)
          .join('\n')
      } catch (e) {
        console.warn('Could not copy styles from sheet:', e)
        return ''
      }
    })
    .join('\n')

  return `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>SmartCV 简历</title>
    <style>
      * {
        box-sizing: border-box;
      }
      html, body {
        margin: 0;
        padding: 0;
        background: #fff;
      }
      /* 防呆：不管复制进来什么样式，导出内容必须可见 */
      #print-root, #print-root * {
        visibility: visible !important;
      }
      ${sheetCss}
    </style>
  </head>
  <body>
    <div id="print-root">${contentHtml}</div>
  </body>
</html>`
}

/**
 * 调后端生成 PDF 并触发下载。
 * 后端成功返回 PDF 二进制；失败返回 { code, message, data } JSON（错误取 message）。
 */
export async function exportResumePdf(flowEl: HTMLElement): Promise<void> {
  const html = buildResumeHtml(flowEl)

  const res = await apiFetch('/api/resume/pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ html }),
  })
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'PDF 生成失败'))

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'smartcv-resume.pdf'
  a.click()
  URL.revokeObjectURL(url)
}
