"""SearXNG 适配器：所有维度的默认来源。

只负责「检索词 → URL 列表」；请求细节（地址 / 超时 / 并发 / JSON 规整）
在 agents/utils/searxng.py，抓取由抓取适配器负责。
"""

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import register
from agents.resume.marker.tools.adapters.base import Hit, Source
from agents.resume.marker.utils.common import normalize_url
from agents.resume.marker.utils.stage_log import stage_info, stage_warning
from agents.utils.searxng import new_client, search


class SearxngSource(Source):
    id = "searxng"
    label = "SearXNG"
    aliases = ("search",)
    dims = ()  # 所有维度都能用

    async def urls(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str] | None = None,
    ) -> list[Hit]:
        # 聚合搜索直接使用检索词，brief / settings 都不参与。
        if limit <= 0 or not queries:
            return []

        batches: list[list[Hit]] = []
        seen: set[str] = set()
        # 每条检索词都必须真正发出请求：不能「凑够 limit 就提前退出」，
        # 否则前几条命中多的检索词会把后面整条吞掉（10 条检索词只发 8 次请求）。
        # 合并去重放到最后，单条失败不影响其它检索词。
        async with new_client() as client:
            for query in queries:
                try:
                    results = await search(query, client=client)
                except Exception as exc:
                    # 静默跳过会让「程序 0 条、浏览器有数据」完全无法定位，
                    # 至少把异常类型和原因留在日志里。
                    stage_warning(
                        "collect",
                        "检索请求失败",
                        query=query[:60],
                        error=f"{type(exc).__name__}: {exc}"[:160],
                    )
                    continue
                batch: list[Hit] = []
                for item in results:
                    url = item["url"]
                    key = normalize_url(url)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    batch.append(
                        Hit(url=url, title=item["title"], published=item["published"])
                    )
                if batch:
                    batches.append(batch)

        # 各检索词轮流取一条再截断：每条检索词都出力，不让第一条占满名额。
        hits: list[Hit] = []
        depth = 0
        while len(hits) < limit and any(depth < len(batch) for batch in batches):
            for batch in batches:
                if depth < len(batch) and len(hits) < limit:
                    hits.append(batch[depth])
            depth += 1
        stage_info("collect", "检索完成", source="searxng", queries=len(queries), hits=len(hits))
        return hits


register(SearxngSource())
