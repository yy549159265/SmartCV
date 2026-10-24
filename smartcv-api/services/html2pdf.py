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
  - 国内装浏览器很慢，可走 npmmirror（它镜像了 playwright 的 cft 路径）：
        PowerShell: $env:PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"
        cmd / bash:  set / export PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
        playwright install chromium
  - Chromium 实例懒加载、全程复用（首次启动约 1~2 秒，之后每次请求几百毫秒）。
"""

import asyncio
import os
import shutil
from pathlib import Path

_playwright = None
_browser = None
_init_lock = asyncio.Lock()

# Playwright 的 Node driver 用系统 TEMP 建 artifacts 目录。Windows 上 %TEMP%
# 是 Medium 完整性，而 PyCharm AI Debugger 之类的沙箱会用 Low 完整性令牌启动
# 服务，Low 进程无法在 Medium 目录下 mkdir，Chromium 启动就会报
# "EPERM: operation not permitted, mkdtemp ...playwright-artifacts-XXXXXX"。
# 项目目录可写，把 driver 的 TEMP 指到这里，既绕开完整性限制，也不污染系统临时目录。
_TMP_ROOT = Path(__file__).resolve().parent.parent / ".runtime" / "playwright"


def _driver_tmp_dir() -> Path | None:
    """给当前进程准备独立的 Playwright 临时目录；不可写则返回 None。"""
    path = _TMP_ROOT / str(os.getpid())
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return path
    except OSError:
        return None


# 防呆：别让超大 HTML 打爆后端内存
_MAX_HTML_SIZE = 2 * 1024 * 1024  # 2MB


async def _get_browser():
    """懒启动：第一次调用才拉 Chromium，之后复用同一实例（多请求并发安全）。"""
    global _playwright, _browser
    if _browser is None:
        async with _init_lock:
            if _browser is None:
                from playwright.async_api import async_playwright

                tmp_dir = _driver_tmp_dir()
                # Node driver 在 start() 时复制当前进程环境，之后一直用自己的 TEMP，
                # 所以只需在 start() 前后临时改环境变量，避免影响其它组件。
                old_env = {key: os.environ.get(key) for key in ("TEMP", "TMP")}
                if tmp_dir is not None:
                    os.environ["TEMP"] = str(tmp_dir)
                    os.environ["TMP"] = str(tmp_dir)
                try:
                    _playwright = await async_playwright().start()
                finally:
                    for key, value in old_env.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value

                try:
                    _browser = await _playwright.chromium.launch()
                except Exception:
                    # 启动失败时把 driver 收掉，避免下次重试又漏一个 node 进程
                    await close_browser()
                    raise
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
        # 清理本次进程的临时目录；Chromium 可能还占着文件，失败就算了
        shutil.rmtree(_TMP_ROOT / str(os.getpid()), ignore_errors=True)


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
            # 前端在 HTML 里注入了 @page { size: 794px 1123px; margin: 0 }，
            # 用 CSS 声明的纸面大小，而不是 Chromium 对 A4 的浮点换算（793.7 × 1122.5），
            # 物理纸面才能和前端预览的 A4 画布完全一致，避免整页块被 Chromium 硬拆成两页。
            prefer_css_page_size=True,
        )
        return pdf
    finally:
        await page.close()
