"""诊断 agent 的联网搜索工具（自建 SearXNG）。

为什么只给诊断 agent：
- 诊断需要了解最新的行业术语、岗位要求、公司/产品背景时，可以查外部信息；
- 优化/摘要 agent 只处理简历文字与诊断结果，不需要联网，避免事实被网络内容污染。

搜索引擎的地址、超时、并发、JSON 规整和 10 分钟缓存都在
`agents/utils/searxng.py`，这里只负责工具调用次数、事件输出和异常文案。

事件：
  - tool_call / tool_result：进入通用「工具调用」记录；
  - web_search：带 query + results，前端单独展示在「Web 搜索」折叠区。
"""

import logging
from typing import Annotated

import httpx
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from pydantic import Field

from agents.utils.searxng import SEARXNG_TIMEOUT, search_sync

logger = logging.getLogger("smartcv")

# 每次搜索返回给模型的条数；一次诊断最多调用次数。
_RESULT_LIMIT = 5
_MAX_CALLS = 3


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
            return (
                "搜索失败：SearXNG 返回 403，通常是没开启 JSON 输出。"
                "确认容器内 /etc/searxng/settings.yml 的 search.formats 包含 json，重启 searxng 后重试。"
            )
        return f"搜索失败：SearXNG 返回 HTTP {code}。"
    if isinstance(exc, httpx.ConnectError):
        return "搜索失败：连不上 SearXNG，确认 searxng 容器已启动，且 SEARXNG_URL 指向它。"
    if isinstance(exc, httpx.TimeoutException):
        return f"搜索失败：SearXNG 超过 {SEARXNG_TIMEOUT:g} 秒没有响应。"
    return f"搜索失败：{exc}"


def make_web_search_tool():
    """创建 web_search 工具（调用次数按工具实例计）。"""
    calls = 0

    @tool
    def web_search(
        query: Annotated[str, Field(description="搜索关键词：具体、简短，一次只查一个事实")],
    ) -> str:
        """联网搜索外部信息。

        只在诊断确实需要简历/JD 之外的公开信息时使用，例如：
        - 核实行业术语、技术名词、公司/产品背景；
        - 了解目标岗位的常见要求或市场现状；
        - 验证简历里提到的外部事实。

        不要用它查找简历改写模板，也不要用搜索结果替换简历事实。
        一次诊断最多调用 3 次；查询词要具体，避免宽泛搜索。
        """
        nonlocal calls
        writer = get_stream_writer()
        if calls >= _MAX_CALLS:
            message = f"本次诊断最多搜索 {_MAX_CALLS} 次，已用完；请按简历、JD 和现有回答继续诊断。"
            writer({"type": "tool_result", "tool": "web_search", "result": message, "ok": False})
            return message
        calls += 1
        writer({"type": "tool_call", "tool": "web_search", "args": {"query": query}})

        try:
            results = search_sync(query, limit=_RESULT_LIMIT)
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
