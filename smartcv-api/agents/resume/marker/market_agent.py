"""市场调研节点：采集一次，随后按维度并行抽取，最后汇总为市场结果。

与图的分工：

  collect   所有维度统一检索、全局 URL 去重、按维度编号；采集结束即发 node.exit。
  extract   每个维度一个节点（普通函数，由图用 Send 动态分发），只读 kind=自己 的页面。
  synthesis 所有 extract 完成后做跨源合成（graph 节点直接调用 synthesis_agent）。

采集与抽取严格分开：collect 全部结束后才开始 extract，前端才能看到
「采集完成 → 并行抽取」，而不是某个 agent 先跑完、采集还在转。
"""

import asyncio
from pathlib import Path

from agents.resume.marker.aspect_agent import run as run_aspect
from agents.resume.marker.jobs_agent import run as run_jobs
from agents.resume.marker.synthesis_agent import run as run_synthesis
from agents.resume.marker.tools.collect import collect_market
from agents.resume.marker.trend_agent import run as run_trend
from agents.resume.marker.utils.dims import FIXED_DIMS, dim_label
from agents.resume.marker.utils.runner import run_structured, safe_writer
from agents.resume.marker.utils.common import normalize_url, time_window_start
from agents.resume.marker.utils.stage_log import stage_exception, stage_info, stage_warning
from agents.resume.marker.schemas import Brief, ExtraUrl, SourceSelection

_FIXED_RUNNERS = {
    "jobs": run_jobs,
    "trend": run_trend,
}
_MAX_SOURCES = 36
# 网址判定是采集前的一次小判断，卡住时宁可回退也不要拖慢整轮采集。
_ROUTE_TIMEOUT = 45.0

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "collect"
_ASSIGN_SYSTEM = (_PROMPT_DIR / "assign.md").read_text(encoding="utf-8")


def _aggregate_coverage(collected: dict[str, dict]) -> str:
    """整体覆盖度：所有维度全 full 才 full；有页面但不满是 partial；全空是 none。"""
    values = [str(item.get("coverage") or "none") for item in collected.values()]
    if all(value == "none" for value in values):
        return "none"
    if all(value == "full" for value in values):
        return "full"
    return "partial"


def _merge_sources(pages: list[dict]) -> list[dict]:
    """来源按 url 去重；同一页只展示一次。"""
    seen: set[str] = set()
    sources: list[dict] = []
    for page in pages:
        url = str(page.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "id": page.get("evidence_id"),
                "title": page.get("title") or url,
                "url": url,
                "site": page.get("site") or "未知站点",
                "published": page.get("published") or "",
            }
        )
        if len(sources) >= _MAX_SOURCES:
            break
    return sources


def _assign_extra_urls_sync(
    brief: Brief,
    groups: list[dict],
    limit: int,
) -> dict[str, list[ExtraUrl]]:
    """模型不可用 / 调用失败时的兜底：按标签方向归组，原顺序取前 N 条。

    固定方向（jobs / trend）本来就有标签；direction=other 归到第一个维度。
    """
    dims = [str(group.get("id") or "") for group in groups]
    first = dims[0] if dims else ""
    by_dim: dict[str, list[ExtraUrl]] = {}
    seen: set[str] = set()
    for item in brief.extra_urls:
        url = (item.url or "").strip()
        key = normalize_url(url)
        if not key or key in seen:
            continue
        target = item.direction if item.direction in dims else first
        if not target:
            continue
        seen.add(key)
        bucket = by_dim.setdefault(target, [])
        if len(bucket) < limit:
            bucket.append(item)
    return by_dim


async def _assign_extra_urls(
    llm,
    brief: Brief,
    groups: list[dict],
    limit: int,
) -> dict[str, list[ExtraUrl]]:
    """一次调用判定所有补充网址：归到哪个维度、是否与本轮目标意向相关。

    显式标了 jobs / trend 的网址只做相关性判定，不允许改维度；只有
    direction=other 允许模型分配到动态维度。每个维度最多保留 limit 条，
    模型判定为无关的直接丢弃，不按顺序补齐——补齐等于没有筛选。
    模型不可用、超时或结果不合法时回退 `_assign_extra_urls_sync`。
    """
    if not brief.extra_urls:
        return {}

    dims = [str(group.get("id") or "") for group in groups]
    if not dims:
        return {}
    fallback = _assign_extra_urls_sync(brief, groups, limit)
    if llm is None:
        return fallback

    labels = {dim: str(group.get("label") or dim) for dim, group in zip(dims, groups)}
    dims_text = "\n".join(f"- {dim}（{labels.get(dim, dim)}）" for dim in dims)
    urls_text = "\n".join(
        f"- url: {(item.url or '').strip()}\n"
        f"  方向: {item.direction or 'other'}\n"
        f"  备注: {(item.note or '').strip() or '未填'}"
        for item in brief.extra_urls
        if (item.url or "").strip()
    )
    message = (
        f"<target>\n{_select_brief_text(brief, '、'.join(dims))}\n</target>\n\n"
        f"<dimensions>\n{dims_text}\n</dimensions>\n\n"
        f"<limit>{limit}</limit>\n\n<urls>\n{urls_text}\n</urls>"
    )

    try:
        structured = await asyncio.wait_for(
            run_structured(
                llm.with_structured_output(SourceSelection, method="json_mode"),
                _ASSIGN_SYSTEM,
                message,
                stage="assign",
            ),
            timeout=_ROUTE_TIMEOUT,
        )
        selection = SourceSelection.model_validate(structured) if structured else None
    except Exception as exc:
        stage_warning("collect", "补充网址判定失败，回退按标签归组", error=exc)
        return fallback
    if selection is None:
        return fallback

    pending = {
        (item.url or "").strip(): item
        for item in brief.extra_urls
        if (item.url or "").strip()
    }
    by_normalized = {normalize_url(url): url for url in pending if normalize_url(url)}
    result: dict[str, list[ExtraUrl]] = {}
    seen: set[str] = set()
    for item in selection.selections:
        key = str(item.url or "").strip()
        url = key if key in pending else by_normalized.get(normalize_url(key))
        if not url or url in seen or not item.keep:
            continue
        source = pending[url]
        # 固定方向只能由用户决定：模型写别的维度一律按原标签归属。
        if source.direction in FIXED_DIMS:
            dim = source.direction
        else:
            dim = item.dim if item.dim in dims else ""
        if dim not in dims:
            continue
        bucket = result.setdefault(dim, [])
        if len(bucket) >= limit:
            continue
        seen.add(url)
        bucket.append(source)
    stage_info(
        "collect",
        "补充网址判定",
        total=len(pending),
        kept=sum(len(urls) for urls in result.values()),
    )
    return result


def _select_brief_text(brief: Brief, dim: str) -> str:
    """告诉筛选模型「本轮要调研什么」，备注之外再给一层判断依据。"""
    return "\n".join(
        [
            f"- 目标岗位：{brief.target_role or '未指定'}",
            f"- 城市：{brief.location}",
            f"- 年限：{brief.experience or '不限'}",
            f"- 用户希望 AI 回答：{brief.direction or '未指定'}",
            f"- 调研方面：{dim_label(dim, brief.aspect_labels)}",
        ]
    )



async def collect(
    brief: Brief,
    groups: list[dict],
    *,
    run_id: str | None = None,
    pages_per_dim: dict[str, int] | None = None,
    urls_per_dim: int | None = None,
    fetch_mode: str | None = None,
    llm=None,
) -> dict:
    """采集节点：所有维度统一检索 + 去重 + 编号。"""
    writer = safe_writer()
    writer({"type": "node.enter", "node": "collect", "label": "采集页面"})

    per_dim = max(1, int(urls_per_dim or 12))
    # 一次调用判完所有补充网址的归属与取舍；模型不可用时按标签归组。
    extra_urls_by_dim = await _assign_extra_urls(llm, brief, groups, per_dim)

    result = await collect_market(
        groups,
        brief=brief,
        pages_per_dim=pages_per_dim,
        urls_per_dim=per_dim,
        fetch_mode=fetch_mode,
        extra_urls_by_dim=extra_urls_by_dim,
        # 有明确发布时间的页面，早于本次时间窗口的直接丢弃，避免把旧行情当成当前行情。
        since=time_window_start(brief.time_window),
    )
    pages = result["pages"]
    collected = result["collected"]
    valid_ids = {str(page.get("evidence_id")) for page in pages if page.get("evidence_id")}
    coverage = _aggregate_coverage(collected)
    sample_size = sum(int(item.get("sample_size") or 0) for item in collected.values())
    sources = _merge_sources(pages)
    # 证据编号 → 页面链接：前端用它把面板里的 J1/T2/S3 变成可点击来源。
    writer(
        {
            "type": "sources.index",
            "items": [
                {
                    "id": str(page.get("evidence_id")),
                    "title": page.get("title") or page.get("url"),
                    "url": page.get("url"),
                    "site": page.get("site") or "",
                    "published": page.get("published") or "",
                    # 前端采集面板按维度分组、按站点展开页面明细。
                    "kind": str(page.get("kind") or ""),
                    # 用户补充网址的 {direction, note}；普通搜索页为 null。
                    "userTag": page.get("user_tag"),
                }
                for page in pages
                if page.get("evidence_id") and page.get("url")
            ],
        }
    )
    writer(
        {
            "type": "node.exit",
            "node": "collect",
            "state": "done",
            "text": f"{sample_size} 页 · {len(sources)} 个来源 · {coverage}",
        }
    )
    return {
        "collected": collected,
        "pages": pages,
        "valid_ids": sorted(valid_ids),
        "sources": sources,
        "coverage": coverage,
        "sample_size": sample_size,
    }


async def extract(
    llm,
    brief: Brief,
    dim: str,
    collected: dict,
    *,
    run_id: str | None = None,
) -> dict:
    """单个维度的抽取节点；固定维度走专用 schema，其余走通用方面 agent。"""
    writer = safe_writer()
    label = dim_label(dim, brief.aspect_labels)
    runner = _FIXED_RUNNERS.get(dim)
    try:
        if runner is not None:
            result = await runner(llm, brief, collected, run_id=f"{run_id}:{dim}")
        else:
            result = await run_aspect(llm, brief, dim, label, collected, run_id=f"{run_id}:{dim}")
        return {"facts": {dim: result}}
    except Exception as exc:
        stage_exception("extract", "抽取失败", dim=dim)
        writer({"type": "error", "node": dim, "message": str(exc), "fatal": False})
        writer({"type": "extract.chunk", "dim": dim, "items": []})
        writer({"type": "extract.done", "dim": dim, "count": 0, "coverage": "none"})
        writer({"type": "node.exit", "node": dim, "state": "error", "text": "抽取失败"})
        return {
            "facts": {
                dim: {
                    "result": {
                        "coverage": "none",
                        "sample_size": 0,
                        "notes": "",
                    },
                    "pages": collected.get("pages") or [],
                    "coverage": "none",
                    "sample_size": 0,
                }
            }
        }


async def synthesize(
    llm,
    brief: Brief,
    dims: list[str],
    facts: dict[str, dict],
    valid_ids: set[str],
    *,
    run_id: str | None = None,
) -> dict:
    """跨源合成：只接收各维度的结构化结果，不重新读页面。"""
    results = {
        dim: (facts.get(dim) or {}).get("result") or {}
        for dim in dims
    }
    return await run_synthesis(
        llm,
        brief,
        results,
        {dim: dim_label(dim, brief.aspect_labels) for dim in dims},
        valid_ids,
        run_id=f"{run_id}:synthesis" if run_id else None,
    )


def build_market(
    brief: Brief,
    dims: list[str],
    facts: dict[str, dict],
    *,
    synthesis: dict,
    pages: list[dict],
    sources: list[dict],
    coverage: str,
    sample_size: int,
    valid_ids: set[str],
) -> dict:
    """把图状态整理成报告 / 质检共用的一份市场结果。"""
    groups = {
        dim: (((facts.get(dim) or {}).get("result")) or {})
        for dim in dims
    }
    aspects = [
        {
            "id": dim,
            "label": dim_label(dim, brief.aspect_labels),
            "result": groups[dim],
            "coverage": (facts.get(dim) or {}).get("coverage") or "none",
            "sample_size": int((facts.get(dim) or {}).get("sample_size") or 0),
        }
        for dim in dims
        if dim not in FIXED_DIMS
    ]
    return {
        "dims": dims,
        "dims_meta": [{"id": dim, "label": dim_label(dim, brief.aspect_labels)} for dim in dims],
        "groups": groups,
        "jobs": groups.get("jobs") or {},
        "trend": groups.get("trend") or {},
        "aspects": aspects,
        "synthesis": synthesis.get("result") or {},
        "pages": pages,
        "valid_ids": sorted(valid_ids),
        "sources": sources,
        "coverage": coverage,
        "sample_size": sample_size,
    }
