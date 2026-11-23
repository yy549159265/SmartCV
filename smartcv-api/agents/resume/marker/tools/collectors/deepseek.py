"""DeepSeek 搜索采集：一次请求返回标题、摘要和正文，不再逐页抓取。

接口见 https://api-docs.deepseek.com/zh-cn/guides/search ：

  POST {base}/v1/tools/search
  Authorization: Bearer <API Key>
  {"query": "...", "count": 1~50, "need_content": true}

响应 results[] 里 `content` 是网页正文（need_content=false 时恒为空），
所以这里不调用 Fetch 接口，正文缺失时按 summary → snippet 依次兜底。
"""

import asyncio
import os
import re

import httpx

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.collectors import register
from agents.resume.marker.tools.collectors.base import CollectField, Collector
from agents.resume.marker.tools.fetch.base import Page, site_of
from agents.resume.marker.utils.common import normalize_url
from agents.resume.marker.utils.dims import MAX_PAGE_CHARS
from agents.resume.marker.utils.stage_log import stage_info, stage_warning

_DEFAULT_BASE = "https://api.deepseek.com"
_TIMEOUT = float(os.getenv("DEEPSEEK_SEARCH_TIMEOUT", "40"))
_CONCURRENCY = 4
_COUNT_MAX = 50
_QUERY_MAX_CHARS = 128


def _search_endpoint(base_url: str) -> str:
    """base 可以只写到域名，也可以已经带 /v1。"""
    base = (base_url or _DEFAULT_BASE).strip().rstrip("/")
    return f"{base}/tools/search" if base.endswith("/v1") else f"{base}/v1/tools/search"


def _clean(value: object, limit: int = 0) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if limit else text


def _error_text(resp: httpx.Response) -> str:
    """错误响应是 OpenAI 兼容格式：{"error": {"message": ...}}。"""
    try:
        message = str((resp.json().get("error") or {}).get("message") or "")
    except ValueError:
        message = ""
    return f"HTTP {resp.status_code}{': ' + message if message else ''}"[:160]


def _page(item: dict) -> Page | None:
    url = _clean(item.get("url"), 500)
    if not url:
        return None
    # content 是 Markdown 正文，保留换行；没有正文时依次退回 summary / snippet。
    text = (
        str(item.get("content") or "").strip()
        or str(item.get("summary") or "").strip()
        or str(item.get("snippet") or "").strip()
    )
    return Page(
        url=url,
        title=_clean(item.get("title"), 200) or url,
        text=text[:MAX_PAGE_CHARS],
        site=site_of(url),
        published=_clean(item.get("date"), 10),
    )


class DeepseekCollector(Collector):
    id = "deepseek"
    label = "DeepSeek 搜索"
    aliases = ("deepseek api", "deepseek搜索")
    fields = (
        CollectField(
            key="baseUrl",
            label="Base URL",
            placeholder=_DEFAULT_BASE,
        ),
        CollectField(key="apiKey", label="API Key", placeholder="sk-...", secret=True),
    )

    async def collect(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str],
        fetch_mode: str = "get",
    ) -> list[Page]:
        # fetch_mode 不参与：检索接口已经带回正文。
        if limit <= 0 or not queries:
            return []
        api_key = (settings.get("apiKey") or "").strip()
        if not api_key:
            raise ValueError("缺少 DeepSeek API Key，请在「采集方式」里填写")
        endpoint = _search_endpoint(settings.get("baseUrl") or "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        count = max(1, min(limit, _COUNT_MAX))
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def search(client: httpx.AsyncClient, query: str) -> list[dict]:
            payload = {
                "query": query[:_QUERY_MAX_CHARS],
                "count": count,
                "need_content": True,
            }
            async with semaphore:
                resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(_error_text(resp))
            return [item for item in (resp.json().get("results") or []) if isinstance(item, dict)]

        pages: list[Page] = []
        seen: set[str] = set()
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            results = await asyncio.gather(
                *(search(client, query) for query in queries),
                return_exceptions=True,
            )
        for query, result in zip(queries, results):
            if isinstance(result, BaseException):
                errors.append(str(result)[:120] or "检索失败")
                stage_warning("collect", "DeepSeek 检索失败", query=query[:60], error=str(result)[:120])
                continue
            for item in result:
                page = _page(item)
                if page is None:
                    continue
                key = normalize_url(page.url)
                if not key or key in seen:
                    continue
                seen.add(key)
                pages.append(page)

        if not pages and errors:
            # 全部检索词都失败：抛给采集阶段，前端显示具体原因（权限 / 余额 / 超时）。
            raise RuntimeError(errors[0])
        stage_info(
            "collect",
            "采集完成",
            collector=self.id,
            queries=len(queries),
            pages=len(pages),
        )
        return pages[:limit]


register(DeepseekCollector())
