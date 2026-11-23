"""爬虫抓取：Scrapling 取页面 → 抽正文 → 转 Markdown。

输入：Hit（url / title / published / user_tag）
输出：Page（url / title / text / site / published / error）

与 `get` 的区别是给模型的是正文 Markdown，而不是整页 HTML：
GET 直取会把 <head>、脚本、导航一起塞进正文，模型读到的主要是噪声；
这里先按语义容器（article / main / body）取一块，再转成 Markdown。
Scrapling 的 Fetcher 只做 HTTP 抓取（带浏览器指纹伪装），不执行 JavaScript；
需要等 JS 渲染时把 Fetcher 换成 StealthyFetcher 即可，其余流程不用改。
"""

import os
import re

from agents.resume.marker.tools.adapters.base import Hit
from agents.resume.marker.tools.fetch import register
from agents.resume.marker.tools.fetch.base import Fetcher, Page, site_of
from agents.resume.marker.utils.stage_log import stage_warning

try:
    from markdownify import markdownify as md
    from scrapling.fetchers import AsyncFetcher
except ImportError as exc:  # 依赖缺失时不注册，fetchMode 自动回退到 get
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""

_TIMEOUT = float(os.getenv("CRAWLER_TIMEOUT", "20"))
# 转出来的 Markdown 只用于给模型读，后面还会按维度预算再截；这里只防超大页面占内存。
_MAX_CHARS = int(os.getenv("CRAWLER_MAX_CHARS", "200000"))

# 正文容器优先级：语义标签最干净，没有时退到常见类名，最后整页 body。
_CONTENT_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    ".article",
    ".post",
    ".content",
    "#content",
    "body",
)
_TAG_NOISE = ("script", "style", "noscript", "svg", "iframe")
_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]*\)")


def _extract_content(response) -> str:
    """取正文 HTML：先找最像正文的容器，取不到就退回整页。"""
    for selector in _CONTENT_SELECTORS:
        matches = response.css(selector)
        html = matches.get() if matches else ""
        # 太短的容器多半是摘要 / 相关推荐，继续往下一个选择器找。
        if html and len(html.strip()) >= 200:
            return html
    return response.html_content or ""


def _to_markdown(html: str) -> str:
    """HTML → Markdown；去掉图片和多余空行，减少模型输入里的噪声。"""
    text = md(
        html,
        heading_style="ATX",
        bullets="-",
        code_language="",
        strip=list(_TAG_NOISE),
    )
    text = _IMAGE_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:_MAX_CHARS]


class CrawlerFetcher(Fetcher):
    id = "crawler"
    label = "正文解析"
    aliases = ("scrapling", "playwright")
    concurrency = 3  # 指纹伪装下仍要控速，避免同一站点触发限流

    async def fetch(self, hit: Hit) -> Page:
        url = (hit.url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return Page(url=url, error="unsupported scheme")

        try:
            # retries 是「总尝试次数」，默认 3；失败页（如超时）会拖慢整轮采集，只试一次。
            response = await AsyncFetcher.get(
                url,
                timeout=_TIMEOUT,
                follow_redirects=True,
                retries=1,
            )
        except Exception as exc:
            return Page(url=url, error=f"crawler failed: {exc}"[:60])

        if response.status >= 400:
            return Page(url=url, error=f"http {response.status}")

        try:
            text = _to_markdown(_extract_content(response))
        except Exception as exc:
            stage_warning("collect", "正文转 Markdown 失败", url=url, error=exc)
            return Page(url=url, error=f"markdown failed: {exc}"[:60])

        if not text:
            return Page(url=url, error="empty text")

        final_url = str(response.url or url)
        return Page(
            url=final_url,
            title=hit.title,
            text=text,
            site=site_of(final_url),
            published=hit.published,
        )


if _IMPORT_ERROR:
    stage_warning("collect", "crawler 抓取不可用，回退 GET", error=_IMPORT_ERROR)
else:
    register(CrawlerFetcher())
