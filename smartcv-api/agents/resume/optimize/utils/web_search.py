"""诊断 agent 的联网搜索工具（自建 SearXNG）。

为什么只给诊断 agent：
- 诊断需要了解最新的行业术语、岗位要求、公司/产品背景时，可以查外部信息；
- 优化/摘要 agent 只处理简历文字与诊断结果，不需要联网，避免事实被网络内容污染。

搜索源是自建的 SearXNG（见 docker-compose.yml 的 searxng 服务）：
  - 通过 SEARXNG_URL 指定地址（Docker 内为 http://searxng:8080，本地默认 127.0.0.1:8080）；
  - 只接受 JSON 输出，需在 SearXNG 的 settings.yml 里开启 search.formats: json；
  - 同一个 query 缓存 10 分钟，避免模型反复搜同一内容。

事件：
  - tool_call / tool_result：进入通用「工具调用」记录；
  - web_search：带 query + results，前端单独展示在「Web 搜索」折叠区。
"""

import logging
import os
import re

import httpx
from cachetools import TTLCache
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

logger = logging.getLogger("smartcv")

_SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8080").rstrip("/")
# 单次最多返回给模型的结果条数：够用且不让搜索结果撑爆上下文
_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
# 搜索超时：SearXNG 会并发查多个引擎，8 秒足够；超时按失败处理，不拖住整条流水线
_TIMEOUT_SECONDS = float(os.getenv("WEB_SEARCH_TIMEOUT", "8"))
# 单次诊断最多搜几次：和提示词里的「最多 3 次」一致，超了直接拒绝，避免模型反复换关键词
_MAX_CALLS = int(os.getenv("WEB_SEARCH_MAX_CALLS", "3"))
# 同一 query 的结果缓存 10 分钟（诊断里经常重复查同一个名词）
_cache: TTLCache = TTLCache(maxsize=256, ttl=600)


def _clean(text: object, limit: int) -> str:
    """压缩空白并截断，避免 HTML 残留和超长摘要。"""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _parse_results(payload: dict) -> list[dict]:
    """把 SearXNG 的 results 规整成前端/模型都能直接用的小列表。"""
    results: list[dict] = []
    seen: set[str] = set()
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        # 同一 URL 可能在多个引擎里出现，按 URL 去重
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": _clean(item.get("title"), 120) or url,
                "url": url,
                "content": _clean(item.get("content") or item.get("snippet"), 300),
            }
        )
        if len(results) >= _MAX_RESULTS:
            break
    return results


def _search(query: str) -> list[dict]:
    """请求 SearXNG 的 JSON 接口；命中缓存直接返回。"""
    cached = _cache.get(query)
    if cached is not None:
        return cached

    resp = httpx.get(
        f"{_SEARXNG_URL}/search",
        params={"q": query, "format": "json", "language": "zh-CN"},
        timeout=_TIMEOUT_SECONDS,
        # SearXNG 一定是内网/本机地址：不走系统代理。
        # 否则 Windows 注册表里配的代理（如 Clash 的 127.0.0.1:7897）会把请求
        # 也转给代理，内网地址解析不到就是 502。
        trust_env=False,
    )
    resp.raise_for_status()
    results = _parse_results(resp.json())
    _cache[query] = results
    return results


def _format_for_model(query: str, results: list[dict]) -> str:
    """给模型看的搜索结果：标题 + URL + 摘要，足够判断要不要采信。"""
    if not results:
        return f"没有搜索到与「{query}」相关的结果。"
    lines = [f"「{query}」的搜索结果（仅作诊断参考，不得据此编造简历事实）："]
    for index, item in enumerate(results, 1):
        lines.append(f"{index}. {item['title']}\n   {item['url']}\n   {item['content']}")
    return "\n".join(lines)


def _error_text(exc: Exception) -> str:
    """把请求异常翻成一句能指导排查的话（会显示到前端「Web 搜索」里）。"""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 403:
            # SearXNG 未开启 json 输出时，/search?format=json 直接 403
            return (
                "搜索失败：SearXNG 返回 403，通常是没开启 JSON 输出。"
                "确认容器内 /etc/searxng/settings.yml 的 search.formats 包含 json，重启 searxng 后重试。"
            )
        return f"搜索失败：SearXNG 返回 HTTP {code}。"
    if isinstance(exc, httpx.ConnectError):
        return "搜索失败：连不上 SearXNG，确认 searxng 容器已启动，且 SEARXNG_URL 指向它。"
    if isinstance(exc, httpx.TimeoutException):
        return f"搜索失败：SearXNG 超过 {_TIMEOUT_SECONDS:g} 秒没有响应。"
    return f"搜索失败：{exc}"


def make_web_search_tool():
    """创建 web_search 工具（缓存是模块级的，调用次数按工具实例计）。"""
    calls = 0

    @tool
    def web_search(query: str) -> str:
        """联网搜索外部信息。

        只在诊断确实需要简历/JD 之外的公开信息时使用，例如：
        - 核实行业术语、技术名词、公司/产品背景；
        - 了解目标岗位的常见要求或市场现状；
        - 验证简历里提到的外部事实。

        不要用它查找简历改写模板，也不要用搜索结果替换简历事实。
        一次诊断最多调用 3 次；查询词要具体，避免宽泛搜索。

        Args:
            query: 搜索关键词（具体、简短）
        """
        nonlocal calls
        writer = get_stream_writer()
        # 超限时不发 tool_call/web_search 事件：模型收到说明后直接继续诊断
        if calls >= _MAX_CALLS:
            message = f"本次诊断最多搜索 {_MAX_CALLS} 次，已用完；请按简历、JD 和现有回答继续诊断。"
            writer({"type": "tool_result", "tool": "web_search", "result": message, "ok": False})
            return message
        calls += 1
        writer({"type": "tool_call", "tool": "web_search", "args": {"query": query}})

        try:
            results = _search(query)
        except Exception as exc:
            message = _error_text(exc)
            logger.warning("web_search 失败 query=%r: %s", query, exc)
            writer(
                {
                    "type": "web_search",
                    "query": query,
                    "results": [],
                    "error": message,
                }
            )
            writer({"type": "tool_result", "tool": "web_search", "result": message, "ok": False})
            return message

        writer({"type": "web_search", "query": query, "results": results, "error": None})
        writer(
            {
                "type": "tool_result",
                "tool": "web_search",
                "result": f"搜索到 {len(results)} 条结果",
                "ok": True,
            }
        )
        logger.info("web_search query=%r → %d 条", query, len(results))
        return _format_for_model(query, results)

    return web_search
