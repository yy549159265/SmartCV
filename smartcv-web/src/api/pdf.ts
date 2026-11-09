/**
 * 导出 PDF：把渲染好的 HTML 发给后端，由 Playwright 打印成 PDF。
 */

import { apiErrorMessage } from '@/api/error'
import { apiFetch } from '@/api/http'
import { pageHeight, pageWidth } from '@/composables/usePageSize'
import { downloadBlob } from '@/utils/download'

export function buildResumeHtml(flowEl: HTMLElement): string {
  const contentHtml = flowEl.outerHTML

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
      /* 纸面 = 前端预览的页面画布（宽高 = 用户设置的纸面尺寸，恒为 A4 纵向比例，四边留白 0）。
         后端用 prefer_css_page_size 采用这里的纸面尺寸，避免 Chromium 按浮点 A4 换算，
         让导出的物理页 = 预览页，整页块不会再被硬拆成两页。 */
      @page {
        size: ${pageWidth.value}px ${pageHeight.value}px;
        margin: 0;
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

export async function fetchResumePdf(flowEl: HTMLElement): Promise<Blob> {
  const html = buildResumeHtml(flowEl)

  const res = await apiFetch('/api/resume/pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ html }),
  })
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'PDF 生成失败'))
  return res.blob()
}

export async function exportResumePdf(flowEl: HTMLElement, filename = 'smartcv-resume'): Promise<void> {
  const blob = await fetchResumePdf(flowEl)
  downloadBlob(blob, `${filename}.pdf`)
}
