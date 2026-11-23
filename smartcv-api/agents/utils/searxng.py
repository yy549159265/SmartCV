"""SearXNG 公共客户端：三个调用方共用的地址、超时、并发和 JSON 规整。

调用方：
- agents/resume/marker/tools/adapters/searxng.py   市场调研默认检索源
- agents/resume/marker/tools/adapters/aggregate.py 全网招聘
- agents/resume/optimize/tools/web_search.py       诊断 agent 的 web_search

返回统一结构 `{"title", "url", "content", "published"}`，条数由调用方传 `limit`
决定（不传表示全部）。请求失败直接抛 httpx 异常，日志和兜底策略留在调用方。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx
from cachetools import TTLCache

logger = logging.getLogger("smartcv")

# 本机跑 searxng-docker-china-main 时映射在 8088；容器内用 SEARXNG_URL=http://searxng:8080。
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8088").rstrip("/")

# 必须大于 SearXNG 的 outgoing.max_request_timeout（当前 10s），否则客户端先断开，
# 每个检索词都会变成 ReadTimeout。
SEARXNG_TIMEOUT = float(os.getenv("SEARXNG_TIMEOUT", "15"))

# 同时发往 SearXNG 的请求上限：它是单 worker + 4 个执行线程，发再多也只排队。
SEARXNG_CONCURRENCY = max(1, int(os.getenv("SEARXNG_CONCURRENCY", "4")))

# 同一个 query 短时间内重复查没有意义（规划经常给多个维度同一批检索词）。
_CACHE: TTLCache = TTLCache(maxsize=256, ttl=600)

_loop: asyncio.AbstractEventLoop | None = None
_semaphore: asyncio.Semaphore | None = None


def new_client() -> httpx.AsyncClient:
    """一个请求批次的共享客户端（连接复用）；由调用方 `async with` 关闭。

    trust_env=False：不读 HTTP_PROXY 等变量，避免本机代理把 127.0.0.1 的请求带走。
    """
    return httpx.AsyncClient(timeout=SEARXNG_TIMEOUT, trust_env=False)


def _limit() -> asyncio.Semaphore:
    """同一事件循环内共用一个信号量；换循环（测试里的 asyncio.run）时重建。"""
    global _loop, _semaphore
    loop = asyncio.get_running_loop()
    if _loop is not loop or _semaphore is None:
        _loop = loop
        _semaphore = asyncio.Semaphore(SEARXNG_CONCURRENCY)
    return _semaphore


def _clean(value: object, limit: int) -> str:
    """压缩空白并截断，避免 HTML 残留和超长摘要。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _parse(payload: dict, limit: int | None) -> list[dict]:
    """把 SearXNG 的 results 规整成统一结构，按 URL 去重。"""
    results: list[dict] = []
    seen: set[str] = set()
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": _clean(item.get("title"), 120) or url,
                "url": url,
                "content": _clean(item.get("content") or item.get("snippet"), 300),
                # 新闻 / 博客类来源会带发布时间；没有就留空，不当成「刚刚发布」。
                "published": _clean(item.get("publishedDate") or item.get("published"), 40),
            }
        )
        if limit and len(results) >= limit:
            break
    return results


def _unresponsive(payload: dict) -> str:
    """引擎失败原因：200 + 空结果时，这是唯一能看出「为什么没结果」的信息。"""
    down = payload.get("unresponsive_engines") or []
    return "、".join(f"{name}:{reason}" for name, reason in down)[:200] or "-"


def _cached(query: str, limit: int | None) -> list[dict] | None:
    hit = _CACHE.get((query, limit))
    return None if hit is None else list(hit)


def _remember(query: str, limit: int | None, results: list[dict]) -> list[dict]:
    _CACHE[(query, limit)] = results
    return list(results)


async def search(
    query: str,
    *,
    limit: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """查一次 SearXNG；失败抛 httpx 异常。

    client 由调用方复用时传进来（全网招聘一次要查多个站点），
    不传就临时建一个。所有异步请求共用全局并发上限。
    """
    text = query.strip()
    if not text:
        return []
    cached = _cached(text, limit)
    if cached is not None:
        return cached

    async with _limit():
        if client is None:
            async with new_client() as own:
                resp = await own.get(f"{SEARXNG_URL}/search", params=_params(text))
        else:
            resp = await client.get(f"{SEARXNG_URL}/search", params=_params(text))
        resp.raise_for_status()
        payload = resp.json()
        results = _parse(payload, limit)

    if not results:
        logger.warning("SearXNG 检索无结果 query=%r unresponsive=%s", text[:60], _unresponsive(payload))
    return _remember(text, limit, results)


def search_sync(query: str, *, limit: int | None = None) -> list[dict]:
    """同步版本：诊断工具是同步函数，不能 await。"""
    text = query.strip()
    if not text:
        return []
    cached = _cached(text, limit)
    if cached is not None:
        return cached

    resp = httpx.get(
        f"{SEARXNG_URL}/search",
        params=_params(text),
        timeout=SEARXNG_TIMEOUT,
        trust_env=False,
    )
    resp.raise_for_status()
    payload = resp.json()
    results = _parse(payload, limit)
    if not results:
        logger.warning("SearXNG 检索无结果 query=%r unresponsive=%s", text[:60], _unresponsive(payload))
    return _remember(text, limit, results)


def _params(query: str) -> dict[str, str]:
    return {"q": query, "format": "json", "language": "zh-CN"}
