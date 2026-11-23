"""全网招聘适配器：用 SearXNG 聚合多个招聘网站的公开岗位页。

输入：检索词列表 + 条数上限 + 本次简报 + 来源设置
输出：Hit 列表（url / title / published）

不区分社招 / 校招，也没有来源私有设置，settings 一律忽略。
规划给 jobs 的每条检索词内容相同（一个来源一条），所以只取第一条，拼上
城市和「招聘」作为基础检索词。

只发一次 `关键词 城市 招聘` 时结果会被单一站点（多数是猎聘）占满，所以
按 `_JOB_SITES` 逐个站点各查一次：检索词后追加「中文品牌名 + 域名」，
再按站点轮转取数，各平台都能出力。不用 `site:` 操作符——360 系引擎不认它，
带 site: 的查询经常直接返回空结果。结果仍按域名白名单筛一遍，避免通用
网页混进来；全部站点都查不到时回退到基础检索词。
"""

import asyncio
import re

import httpx

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import register
from agents.resume.marker.tools.adapters.base import Hit, Source
from agents.resume.marker.utils.common import normalize_url
from agents.resume.marker.utils.stage_log import stage_info, stage_warning
from agents.utils.searxng import new_client, search

# 同时查询的站点数：SearXNG 只有 4 个执行槽位，一次发 8 个会让后面的请求
# 在服务端排队，排队时间算进客户端 timeout，成批 ReadTimeout。一次 2 个
# 时每个请求都不排队，代价是 8 个站点分 4 批返回。
_SITE_CONCURRENCY = 2

# 招聘站域名白名单：既按站点逐个检索，也用于结果过滤。
_JOB_SITES = (
    "zhipin.com",
    "liepin.com",
    "zhaopin.com",
    "51job.com",
    "lagou.com",
    "nowcoder.com",
    "jobui.com",
    "maimai.cn",
)

# 站点 → 检索词里追加的中文品牌名。360 系引擎不认 site:（常直接返回空），
# 用「品牌名 + 域名」才能让每个站点都出自己家的岗位。
_JOB_BRANDS = {
    "zhipin.com": "BOSS直聘",
    "liepin.com": "猎聘",
    "zhaopin.com": "智联招聘",
    "51job.com": "前程无忧",
    "lagou.com": "拉勾",
    "nowcoder.com": "牛客",
    "jobui.com": "职友集",
    "maimai.cn": "脉脉",
}


def _clean(value: object, limit: int = 0) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if limit else text


def _search_query(keyword: str, city: str) -> str:
    """检索词 + 城市 + 招聘；城市为空时不加。"""
    parts = [_clean(keyword), _clean(city), "招聘"]
    return " ".join(part for part in parts if part)


def _host(url: str) -> str:
    return _clean(url).split("://", 1)[-1].split("/", 1)[0].casefold()


def _matches_site(url: str, site: str) -> bool:
    host = _host(url)
    return bool(site) and (host == site or host.endswith("." + site))


def _is_job_url(url: str) -> bool:
    return any(_matches_site(url, site) for site in _JOB_SITES)


def _interleave(batches: list[list[Hit]], limit: int) -> list[Hit]:
    """各站点轮流取一条，避免排在前面的站点占满名额。"""
    hits: list[Hit] = []
    depth = 0
    while len(hits) < limit and any(depth < len(batch) for batch in batches):
        for batch in batches:
            if depth < len(batch) and len(hits) < limit:
                hits.append(batch[depth])
        depth += 1
    return hits


async def _fetch(client: httpx.AsyncClient, query: str) -> list[dict]:
    """查一次 SearXNG；单次失败只记日志，不拖垮其它站点。"""
    try:
        return await search(query, client=client)
    except Exception as exc:
        stage_warning(
            "collect",
            "全网招聘检索失败",
            query=query[:80],
            error=f"{type(exc).__name__}: {exc}"[:160],
        )
        return []


def _to_batches(groups: list[list[dict]], sites: list[str]) -> list[list[Hit]]:
    """逐组过滤成招聘站链接，跨组去重后只保留非空的组。

    sites 与 groups 一一对应：每组优先只保留该站点的结果，这样轮转取数时
    每个站点都能出力；该站点一条都没有时才保留组内其它招聘站链接。
    """
    batches: list[list[Hit]] = []
    seen: set[str] = set()
    for results, site in zip(groups, sites):
        primary: list[Hit] = []
        secondary: list[Hit] = []
        local: set[str] = set()
        for item in results:
            url = _clean(item.get("url"), 500)
            if not _is_job_url(url):
                continue
            key = normalize_url(url)
            if not key or key in local:
                continue
            local.add(key)
            hit = Hit(
                url=url,
                title=_clean(item.get("title"), 120) or url,
                published=_clean(item.get("published"), 40),
            )
            (primary if _matches_site(url, site) else secondary).append(hit)
        # 跨组去重放在「选定这批之后」：被丢弃的次级结果不影响其它站点。
        batch: list[Hit] = []
        for hit in primary or secondary:
            key = normalize_url(hit.url)
            if not key or key in seen:
                continue
            seen.add(key)
            batch.append(hit)
        if batch:
            batches.append(batch)
    return batches


class AggregateSource(Source):
    id = "aggregate"
    label = "全网招聘"
    aliases = ("aggregate", "聚合", "聚合招聘", "BOSS直聘", "boss")
    dims = ("jobs",)  # 招聘站只服务 jobs 维度

    async def urls(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str] | None = None,
    ) -> list[Hit]:
        if limit <= 0 or not queries:
            return []

        # 规划给 jobs 的每条检索词内容相同，只取第一条，避免重复请求同一个查询。
        keyword = _clean(queries[0])
        if not keyword:
            return []
        base = _search_query(keyword, brief.city)
        # 单个 `关键词 城市 招聘` 的结果几乎被猎聘占满，所以按站点各查一次，
        # 每个站点都能贡献条目，最终结果不会只有一家。
        site_queries = [f"{base} {_JOB_BRANDS[site]} {site}" for site in _JOB_SITES]
        stage_info("collect", "全网招聘检索", query=base, sites=len(site_queries))

        semaphore = asyncio.Semaphore(_SITE_CONCURRENCY)
        async with new_client() as client:

            async def bounded(query: str) -> list[dict]:
                async with semaphore:
                    return await _fetch(client, query)

            groups = list(await asyncio.gather(*(bounded(query) for query in site_queries)))
            batches = _to_batches(groups, list(_JOB_SITES))
            if not batches:
                # 站点检索词全部落空时，退回不带站点限定的基础检索词。
                batches = _to_batches([await _fetch(client, base)], [""])

        hits = _interleave(batches, limit)
        stage_info("collect", "全网招聘命中", count=len(hits), sites=len(batches), query=base)
        return hits


register(AggregateSource())
