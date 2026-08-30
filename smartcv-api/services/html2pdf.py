"""
PDF 生成服务：把"前端渲染好的简历 HTML"用无头 Chromium（Playwright）打成 PDF。

为什么用 Playwright 而不是 WeasyPrint / reportlab：
  - 简历排版是前端 Vue 组件用 flexbox 等现代 CSS 渲染的，WeasyPrint 对 flex 支持弱，
    复刻会失真；Playwright 是真正的 Chromium，排版和浏览器里看到的完全一致。
  - reportlab 要手动逐行画 PDF，简历这种动态排版写起来极其痛苦。

注意：
  - 需要安装 playwright 及浏览器（一次性）：
        pip install playwright
        playwright install chromium
  - 国内装浏览器可能要配镜像：
        set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
  - Chromium 实例懒加载、全程复用（首次启动约 1~2 秒，之后每次请求几百毫秒）。
"""

import asyncio

_playwright = None
_browser = None
_init_lock = asyncio.Lock()

# 防呆：别让超大 HTML 打爆后端内存
_MAX_HTML_SIZE = 2 * 1024 * 1024  # 2MB


async def _get_browser():
    """懒启动：第一次调用才拉 Chromium，之后复用同一实例（多请求并发安全）。"""
    global _playwright, _browser
    if _browser is None:
        async with _init_lock:
            if _browser is None:
                from playwright.async_api import async_playwright

                _playwright = await async_playwright().start()
                _browser = await _playwright.chromium.launch()
    return _browser


async def close_browser():
    """服务关闭时释放 Chromium，避免解释器退出时弹出资源清理告警。"""
    global _playwright, _browser
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None


async def resume_html_to_pdf(html: str) -> bytes:
    """简历 HTML → PDF 二进制。

    - format="A4"：直接按 A4 纸张输出（约 794px 宽，与前端预览一致），
      浏览器自己按 A4 高度自动分页，页数和内容真实排版一致；
    - print_background=True：保留标签底色、色块等背景色；
    - 四边距 0：不要浏览器默认页边距。
    """
    if not html.strip():
        raise ValueError("HTML 内容为空")
    if len(html.encode("utf-8")) > _MAX_HTML_SIZE:
        raise ValueError("HTML 内容过大（超过 2MB）")

    browser = await _get_browser()
    page = await browser.new_page()
    try:
        # set_content 会等文档加载完；图片都是 base64 内联，无外部请求
        await page.set_content(html)
        pdf = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        return pdf
    finally:
        await page.close()
