"""SearXNG 采集：先用 SearXNG 搜出 URL，再按抓取方式逐页取正文。

与内置来源的关系：内置来源（腾讯 / 字节 / 全网招聘等）由 collect.py 优先处理，
只有没勾内置来源的维度才走这里，所以这里直接用 searxng 来源适配器。
"""

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import get_source
from agents.resume.marker.tools.collectors import register
from agents.resume.marker.tools.collectors.base import Collector
from agents.resume.marker.tools.fetch import get_fetcher
from agents.resume.marker.tools.fetch.base import Page
from agents.resume.marker.utils.stage_log import stage_info

_SEARXNG_SOURCE = "searxng"


class SearxngCollector(Collector):
    id = "searxng"
    label = "SearXNG"
    aliases = ("search",)

    async def collect(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str],
        fetch_mode: str = "get",
    ) -> list[Page]:
        if limit <= 0 or not queries:
            return []
        source = get_source(_SEARXNG_SOURCE)
        if source is None:
            return []
        hits = await source.urls(queries, limit=limit, brief=brief, settings=None)
        if not hits:
            return []
        pages = await get_fetcher(fetch_mode).fetch_list(hits)
        stage_info(
            "collect",
            "采集完成",
            collector=self.id,
            fetch=fetch_mode,
            hits=len(hits),
            pages=sum(1 for page in pages if page.ok),
        )
        return pages


register(SearxngCollector())
