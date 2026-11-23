"""采集协调：每个维度出一批页面 → 统一列表 → 按维度编号。

分两段，各自只认注册表：

  采集段  勾了内置来源就只用内置来源（来源适配器 + 抓取适配器），
          否则交给「采集方式」适配器（searxng / deepseek）；
  抓取段  补充网址始终按 fetchMode 取抓取适配器，与采集方式无关。

每维独立配额，不按比例分配；启用内置源后不回落 searxng。
"""

import asyncio
from datetime import date, datetime

from agents.resume.marker.schemas import Brief, ExtraUrl
from agents.resume.marker.schemas.market import (
    PAGES_PER_DIM_DEFAULT,
    PAGES_PER_DIM_MAX,
    pages_key,
)
from agents.resume.marker.tools.adapters import SourceBinding, resolve_sources
from agents.resume.marker.tools.adapters.base import Hit
from agents.resume.marker.tools.collectors import Collector, resolve_collector
from agents.resume.marker.tools.fetch import get_fetcher
from agents.resume.marker.tools.fetch.base import Page, site_of
from agents.resume.marker.utils.common import normalize_url
from agents.resume.marker.utils.dims import evidence_prefixes
from agents.resume.marker.utils.runner import safe_writer
from agents.resume.marker.utils.stage_log import stage_warning

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m", "%Y年%m月%d日")


def _interleave(batches: list[list[Hit]], limit: int) -> list[Hit]:
    """多个内置源并行检索后按轮转交错合并，避免单站点占满名额。"""
    merged: list[Hit] = []
    depth = 0
    while len(merged) < limit:
        added = False
        for batch in batches:
            if depth < len(batch) and len(merged) < limit:
                merged.append(batch[depth])
                added = True
        if not added:
            break
        depth += 1
    return merged


async def _safe_urls(
    binding: SourceBinding,
    queries: list[str],
    brief: Brief,
    limit: int,
) -> list[Hit]:
    try:
        return await binding.source.urls(
            queries,
            limit=limit,
            brief=brief,
            settings=binding.settings,
        )
    except Exception as exc:
        stage_warning("collect", "来源检索失败", source=binding.source.id, error=exc)
        return []


async def _source_hits(
    bindings: list[SourceBinding],
    queries: list[str],
    brief: Brief,
    limit: int,
) -> list[Hit]:
    """内置来源并行检索：一个来源一条检索词，按来源轮转合并。"""
    # 规划按「一个来源一条」输出检索词，条数与来源对齐时各源只拿自己那条；
    # 条数对不上（规划异常或来源被过滤）才整组下发，内容相同不影响结果。
    per_binding = (
        [[query] for query in queries]
        if len(queries) == len(bindings)
        else [queries for _ in bindings]
    )
    batches = await asyncio.gather(
        *(
            _safe_urls(binding, binding_queries, brief, limit)
            for binding, binding_queries in zip(bindings, per_binding)
        )
    )
    return _interleave(list(batches), limit)


async def _collect_dim(
    dim: str,
    queries: list[str],
    brief: Brief,
    limit: int,
    *,
    collector: Collector,
    settings: dict[str, str],
    fetch_mode: str,
) -> tuple[list[Page], str]:
    """一个维度的页面；第二个返回值是整次失败的原因，成功时为空串。

    内置来源优先：勾了就只查这些来源并逐页抓取，不走采集方式。
    否则由采集方式自己决定是「检索 + 抓取」还是「检索直接带正文」。
    """
    if limit <= 0:
        return [], ""
    bindings = resolve_sources(brief.sources, dim)
    try:
        if bindings:
            hits = await _source_hits(bindings, queries, brief, limit)
            if not hits:
                return [], ""
            return await get_fetcher(fetch_mode).fetch_list(hits), ""
        if not queries:
            return [], ""
        pages = await collector.collect(
            queries,
            limit=limit,
            brief=brief,
            settings=settings,
            fetch_mode=fetch_mode,
        )
        return pages, ""
    except Exception as exc:
        # 密钥缺失 / 接口报错：记日志，并把原因带到该维度的采集结果里。
        stage_warning("collect", "采集失败", dim=dim, collector=collector.id, error=exc)
        return [], (str(exc)[:120] or "采集失败")


def _extra_hits(items: list[ExtraUrl] | None, limit: int) -> list[Hit]:
    """用户补充网址：带 user_tag，供前端显示「补充」标记与备注。"""
    hits: list[Hit] = []
    for item in items or []:
        url = (item.url or "").strip()
        if not url:
            continue
        hits.append(Hit(url=url, user_tag={"direction": item.direction, "note": item.note}))
        if len(hits) >= limit:
            break
    return hits


def _too_old(published: str, since: date | None) -> bool:
    """有明确发布时间且早于时间窗口的页面丢弃；解析不出时间的保留。"""
    if since is None or not published:
        return False
    raw = published.strip()
    for fmt in _DATE_FORMATS:
        for text in (raw, raw[:10]):
            try:
                return datetime.strptime(text, fmt).date() < since
            except ValueError:
                continue
    return False


def _dim_pages(dim: str, pages: dict[str, int] | None) -> int:
    """该维度的页数：jobs / trend 各用各的，动态方向统一用 other。"""
    try:
        value = int((pages or {}).get(pages_key(dim), PAGES_PER_DIM_DEFAULT))
    except (TypeError, ValueError):
        value = PAGES_PER_DIM_DEFAULT
    return max(1, min(PAGES_PER_DIM_MAX, value))


def _coverage(count: int, target: int) -> str:
    if count <= 0:
        return "none"
    return "full" if count >= max(1, target) else "partial"


async def collect_market(
    groups: list[dict],
    *,
    brief: Brief,
    pages_per_dim: dict[str, int] | None = None,
    urls_per_dim: int = 12,
    fetch_mode: str | None = None,
    extra_urls_by_dim: dict[str, list[ExtraUrl]] | None = None,
    since: date | None = None,
) -> dict:
    """所有维度统一采集，返回 `{pages, collected}`。"""
    writer = safe_writer()
    urls_per_dim = max(0, int(urls_per_dim))
    extras = extra_urls_by_dim or {}
    prefixes = evidence_prefixes(groups)
    fetcher = get_fetcher(fetch_mode or "get")
    collector, collector_settings = resolve_collector(brief.collector)

    # 1. 每个维度各自采集；内置来源优先，否则交给采集方式适配器。
    dims = [str(group.get("id") or "") for group in groups if group.get("id")]
    queries_by_dim = {
        str(group.get("id")): group.get("queries") or [] for group in groups if group.get("id")
    }
    dim_limits = {dim: _dim_pages(dim, pages_per_dim) for dim in dims}
    grouped = await asyncio.gather(
        *(
            _collect_dim(
                dim,
                queries_by_dim.get(dim) or [],
                brief,
                dim_limits[dim],
                collector=collector,
                settings=collector_settings,
                fetch_mode=fetch_mode or "get",
            )
            for dim in dims
        )
    )

    # 2. 补充网址单独抓取：它们不在检索结果里，任何采集方式都要过一遍抓取适配器。
    extra_entries = [
        (dim, hit)
        for dim in dims
        for hit in _extra_hits(extras.get(dim), urls_per_dim)
    ]
    extra_pages = (
        await fetcher.fetch_list([hit for _, hit in extra_entries]) if extra_entries else []
    )

    # 3. 合成一个全局列表：补充网址在前，同一页只保留第一次出现的维度。
    entries: list[tuple[str, Page, Hit | None]] = []
    seen: set[str] = set()
    for (dim, hit), page in zip(extra_entries, extra_pages):
        key = normalize_url(page.url or hit.url)
        if not key or key in seen:
            continue
        seen.add(key)
        entries.append((dim, page, hit))
    dim_errors: dict[str, str] = {}
    for dim, (dim_pages_list, error) in zip(dims, grouped):
        if error:
            dim_errors[dim] = error
        for page in dim_pages_list:
            key = normalize_url(page.url)
            if not key or key in seen:
                continue
            seen.add(key)
            entries.append((dim, page, None))

    # 4. 失败的页面记原因并跳过；成功的按维度编号。
    counters: dict[str, int] = {}
    buckets: dict[str, list[dict]] = {dim: [] for dim in dims}
    planned: dict[str, int] = {dim: 0 for dim in dims}
    published: dict[str, int] = {dim: 0 for dim in dims}
    by_site: dict[str, dict[str, dict]] = {dim: {} for dim in dims}
    skipped: dict[str, dict[str, list[str]]] = {dim: {} for dim in dims}

    for dim, _page, _hit in entries:
        planned[dim] = planned.get(dim, 0) + 1

    for dim, page, hit in entries:
        site = page.site or site_of(page.url) or "未知站点"
        stat = by_site.setdefault(dim, {}).setdefault(site, {"got": 0, "total": 0})
        stat["total"] += 1

        if not page.ok:
            skipped.setdefault(dim, {}).setdefault(site, []).append(page.error)
            continue
        if _too_old(page.published or (hit.published if hit else ""), since):
            skipped.setdefault(dim, {}).setdefault(site, []).append("早于时间窗口")
            continue

        counters[dim] = counters.get(dim, 0) + 1
        stat["got"] += 1
        page_published = page.published or (hit.published if hit else "")
        if page_published:
            published[dim] = published.get(dim, 0) + 1
        buckets.setdefault(dim, []).append(
            {
                "evidence_id": f"{prefixes.get(dim, 'E')}{counters[dim]}",
                "kind": dim,
                "url": page.url or hit.url,
                "title": page.title or (hit.title if hit else "") or page.url,
                "text": page.text,
                "site": site,
                "published": page_published,
                "user_tag": hit.user_tag if hit else None,
            }
        )

    # 5. 按维度汇总并上报：站点进度、跳过原因、维度结果。
    pages: list[dict] = []
    collected: dict[str, dict] = {}
    for dim in dims:
        for site, stat in by_site.get(dim, {}).items():
            writer(
                {
                    "type": "collect.chunk",
                    "group": dim,
                    "site": site,
                    "got": stat["got"],
                    "total": stat["total"],
                }
            )
        # 按站点汇总失败页：total / got 用该站点自己的计划与实际，别用整个维度的配额，
        # 否则前端会把「0/2 页失败」显示成「0/12 页」。
        for site, reasons in skipped.get(dim, {}).items():
            stat = by_site.get(dim, {}).get(site, {"got": 0, "total": 0})
            writer(
                {
                    "type": "collect.skip",
                    "group": dim,
                    "site": site,
                    "total": stat["total"],
                    "got": stat["got"],
                    "skipped": len(reasons),
                    "reason": "、".join(dict.fromkeys(reasons)),
                }
            )
        # 整次采集失败（缺密钥 / 接口报错）：没有页面可挂在站点上，单独报一条。
        if dim_errors.get(dim):
            writer(
                {
                    "type": "collect.skip",
                    "group": dim,
                    "site": collector.label,
                    "total": 1,
                    "got": 0,
                    "skipped": 1,
                    "reason": dim_errors[dim],
                }
            )

        dim_pages = buckets.get(dim) or []
        pages.extend(dim_pages)
        collected[dim] = {
            "pages": dim_pages,
            "coverage": _coverage(len(dim_pages), dim_limits[dim]),
            "sample_size": len(dim_pages),
        }
        # 勾了内置源却 0 页：不回落 searxng，把原因直接告诉前端。
        builtin = bool(resolve_sources(brief.sources, dim))
        reason = dim_errors.get(dim) or (
            "内置来源没有返回可抓取的页面" if builtin and not dim_pages else ""
        )
        writer(
            {
                "type": "collect.done",
                "group": dim,
                "total": len(dim_pages),
                "planned": planned.get(dim, 0),
                "published": published.get(dim, 0),
                "reason": reason,
            }
        )

    return {"pages": pages, "collected": collected}
