"""Agent 1 · trend：技术趋势与新技术调研矩阵的抽取。"""

import re
import uuid
from collections import Counter
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.utils.dims import MAX_GROUP_CHARS
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
    safe_writer,
)
from agents.resume.marker.schemas import (
    Brief,
    CategoryDistribution,
    CategoryStat,
    FishboneBranch,
    FishboneTechnology,
    FrameworkEcosystem,
    FrameworkItem,
    ScenarioRanking,
    ScenarioStat,
    ScenarioTrendItem,
    ScenarioTrends,
    TechnologyApplications,
    TechnologyFishbone,
    TechnologyFrequency,
    TechnologyProblem,
    TechnologyTrends,
    TrendOverview,
    TrendResult,
    TrendSignal,
)
from agents.resume.marker.utils.common import (
    clean_text,
    filter_evidence,
    format_pages,
    merge_coverage,
    normalize_skill,
    valid_evidence_ids,
)
from agents.resume.marker.utils.stage_log import stage_warning
from agents.resume.optimize.utils.checkpointer import get_checkpointer

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "extract" / "trend.md").read_text(encoding="utf-8")

# 统计门槛：至少 2 个有效信息源提及才纳入；样本少于 3 页时放宽到 1。
_MIN_SAMPLE_FOR_THRESHOLD = 3
_MAX_MONTHS = 12

_TREND_RANK = {"declining": 0, "stable": 1, "rising": 2, "emerging": 3}
_SCENARIO_TREND_RANK = {"declining": 0, "stable": 1, "rising": 2}

# 技术名常见后缀：合并「RAG」「RAG 检索」「RAG 技术」这类写法。
_TECH_SUFFIXES = (
    "技术栈",
    "技术",
    "框架",
    "工具",
    "平台",
    "协议",
    "模型",
    "引擎",
    "方案",
    "系统",
    "检索",
    "生态",
    "服务",
    "能力",
)
_TECH_ALIASES = {
    "rag检索": "rag",
    "检索增强生成": "rag",
    "retrievalaugmentedgeneration": "rag",
    "agent评估": "agenteval",
    "agent评测": "agenteval",
    "multiagent": "multi-agent",
    "多智能体": "multi-agent",
    "多agent": "multi-agent",
    "mcp协议": "mcp",
}
_CANONICAL_NAMES = {
    "rag": "RAG",
    "agenteval": "Agent Eval",
    "agentobservability": "Agent Observability",
    "contextengineering": "Context Engineering",
    "embedding": "Embedding",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "mcp": "MCP",
    "milvus": "Milvus",
    "multi-agent": "Multi-Agent",
    "toolcalling": "Tool Calling",
}

# 提示词已禁止分式；代码再兜一层，避免「5/9」「3 个/9 个」这类写法进入面板。
_FRACTION_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*(个|篇|条|次)?\s*/\s*(\d{1,3})\s*(个|篇|条|次)?\s*(?:有效)?\s*(信息源|文章|页面|页|来源|资料)?"
)


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=TrendResult,
        middleware=[DropInvalidToolCallsMiddleware()],
        checkpointer=get_checkpointer(),
    )


def _empty() -> dict:
    return TrendResult().model_dump()


def _stat_text(value: object) -> str:
    """清理文字字段，并把「xxx/xxx」分式改写成「xxx」而不是留下斜杠。"""

    def replace(match: re.Match) -> str:
        unit = match.group(4) or match.group(2) or ""
        noun = match.group(5) or ""
        if not unit and not noun:
            return f"{match.group(1)}（共 {match.group(3)}）"
        return f"{match.group(1)} {unit}{noun}".strip()

    return _FRACTION_RE.sub(replace, clean_text(value))


def _min_count(total: int) -> int:
    return 2 if total >= _MIN_SAMPLE_FOR_THRESHOLD else 1


def _tech_key(name: object) -> str:
    """技术名归一：同义词、大小写、空格和常见后缀都收成同一个 key。"""
    key = normalize_skill(name)
    if not key:
        return ""
    changed = True
    while changed:
        changed = False
        for suffix in _TECH_SUFFIXES:
            if key.endswith(suffix) and len(key) > len(suffix) + 1:
                key = key[: -len(suffix)]
                changed = True
                break
    return _TECH_ALIASES.get(key, key)


def _display_name(key: str, names: list[str]) -> str:
    """合并后的展示名：优先标准写法，其次出现次数最多、长度最短的原始写法。"""
    canonical = _CANONICAL_NAMES.get(key)
    if canonical:
        return canonical
    counts = Counter(name for name in names if name)
    if not counts:
        return key
    return sorted(counts, key=lambda name: (-counts[name], len(name), name))[0]


def _text_key(value: object) -> str:
    """分类名归一：忽略空格和大小写，避免同一领域拆成两个分支。"""
    return re.sub(r"\s+", "", clean_text(value)).casefold()


def _month_of(value: object) -> str:
    match = re.match(r"(\d{4})[-/年.](\d{1,2})", str(value or "").strip())
    return f"{match.group(1)}-{int(match.group(2)):02d}" if match else ""


def _clean_months(months: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in months:
        month = _month_of(value)
        if month and month not in cleaned:
            cleaned.append(month)
    cleaned.sort()
    return cleaned[-_MAX_MONTHS:]


def _align_counts(counts: list[int], size: int) -> list[int]:
    values = [max(int(value or 0), 0) for value in (counts or [])][:size]
    return values + [0] * (size - len(values))


def _months_from_pages(pages: list[dict]) -> list[str]:
    months = sorted({_month_of(page.get("published")) for page in pages if _month_of(page.get("published"))})
    return months[-_MAX_MONTHS:]


def _counts_from_evidence(ids: list[str], months: list[str], page_months: dict[str, str]) -> list[int]:
    index = {month: position for position, month in enumerate(months)}
    counts = [0] * len(months)
    for eid in ids:
        position = index.get(page_months.get(eid, ""))
        if position is not None:
            counts[position] += 1
    return counts


def _fallback_ids(name: object, pages: list[dict], limit: int = 8) -> list[str]:
    """模型漏给 evidence_ids 时，按名称回查页面正文，避免整块统计被丢掉。"""
    cleaned = clean_text(name).casefold()
    key = _tech_key(name)
    needles = {cleaned, key} - {""}
    if not needles:
        return []
    found: list[str] = []
    for page in pages:
        eid = str(page.get("evidence_id") or "")
        if not eid:
            continue
        haystack = " ".join(
            str(page.get(field) or "") for field in ("title", "text", "url")
        ).casefold()
        if any(needle in haystack for needle in needles):
            found.append(eid)
        if len(found) >= limit:
            break
    return found


def _clean_frequency(
    frequency: TechnologyFrequency,
    pages: list[dict],
    valid: set[str],
    total_sources: int,
    min_count: int,
) -> TechnologyFrequency:
    """合并相似技术、对齐月份、过滤单条噪声，重算占比。"""
    months = _clean_months(frequency.months)
    page_months = {str(page.get("evidence_id")): _month_of(page.get("published")) for page in pages}
    derived = False
    if not months:
        months = _months_from_pages(pages)
        derived = bool(months)

    records: dict[str, dict] = {}
    for branch in frequency.fishbone.branches:
        category = _stat_text(branch.category) or "其他技术"
        for tech in branch.technologies:
            name = _stat_text(tech.name)
            key = _tech_key(name)
            ids = filter_evidence(tech.evidence_ids, valid) or _fallback_ids(name, pages)
            if not key or not ids:
                continue
            counts = _align_counts(tech.monthly_counts, len(months))
            if derived:
                counts = _counts_from_evidence(ids, months, page_months)
            total = sum(counts) or max(int(tech.total_count or 0), 0)
            if total < min_count:
                continue
            record = records.setdefault(
                key,
                {
                    "names": [],
                    "counts": [0] * len(months),
                    "model_total": 0,
                    "total": 0,
                    "evidence": [],
                    "ids": [],
                    "branches": Counter(),
                },
            )
            record["names"].append(name)
            # 同一页面可能同时出现「RAG」「RAG 检索」两种叫法，月度计数取最大值去重。
            if len(counts) == len(months):
                record["counts"] = [max(left, right) for left, right in zip(record["counts"], counts)]
            record["model_total"] = max(record["model_total"], total, len(ids))
            evidence = _stat_text(tech.evidence)
            if evidence:
                record["evidence"].append(evidence)
            record["ids"] = list(dict.fromkeys(record["ids"] + ids))
            record["branches"][category] += total

    grouped: dict[str, dict] = {}
    for key, record in records.items():
        category = record["branches"].most_common(1)[0][0]
        total = sum(record["counts"]) if any(record["counts"]) else record["model_total"]
        percentage = round(min(total / total_sources * 100, 100), 1) if total_sources else 0.0
        group = grouped.setdefault(_text_key(category), {"name": category, "technologies": []})
        group["technologies"].append(
            FishboneTechnology(
                name=_display_name(key, record["names"]),
                total_count=total,
                monthly_counts=record["counts"],
                percentage=percentage,
                evidence="；".join(dict.fromkeys(record["evidence"])),
                evidence_ids=record["ids"],
            )
        )

    branches: list[FishboneBranch] = []
    for group in grouped.values():
        technologies = group["technologies"]
        technologies.sort(key=lambda item: (-item.total_count, item.name))
        branches.append(FishboneBranch(category=group["name"], technologies=technologies))
    branches.sort(
        key=lambda branch: (-sum(item.total_count for item in branch.technologies), branch.category)
    )

    return TechnologyFrequency(
        time_range=_stat_text(frequency.time_range),
        months=months,
        fishbone=TechnologyFishbone(
            center=_stat_text(frequency.fishbone.center) or "高频技术",
            branches=branches,
        ),
        summary=_stat_text(frequency.summary),
    )


def _branch_stats(branches: list[FishboneBranch]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for branch in branches:
        key = _text_key(branch.category)
        stat = stats.setdefault(key, {"name": branch.category, "technology_count": 0, "mention_count": 0, "ids": []})
        stat["technology_count"] += len(branch.technologies)
        stat["mention_count"] += sum(item.total_count for item in branch.technologies)
        for item in branch.technologies:
            stat["ids"] = list(dict.fromkeys(stat["ids"] + item.evidence_ids))
    return stats


def _clean_categories(
    distribution: CategoryDistribution,
    branches: list[FishboneBranch],
    pages: list[dict],
    valid: set[str],
    min_count: int,
) -> CategoryDistribution:
    """默认沿用模型给的领域划分；能与鱼骨分支对上时，以鱼骨的统计为准。"""
    branch_stats = _branch_stats(branches)
    merged: dict[str, dict] = {}
    for item in distribution.items:
        name = _stat_text(item.name)
        if not name:
            continue
        key = _text_key(name)
        branch = branch_stats.get(key)
        if branch:
            merged[key] = {
                "name": name,
                "technology_count": branch["technology_count"],
                "mention_count": branch["mention_count"],
                "ids": branch["ids"],
            }
            continue
        record = merged.setdefault(
            key,
            {"name": name, "technology_count": 0, "mention_count": 0, "ids": []},
        )
        record["technology_count"] = max(record["technology_count"], int(item.technology_count or 0))
        record["mention_count"] = max(record["mention_count"], int(item.mention_count or 0))
        ids = filter_evidence(item.evidence_ids, valid) or _fallback_ids(name, pages)
        record["ids"] = list(dict.fromkeys(record["ids"] + ids))

    if not merged and branch_stats:
        for stat in branch_stats.values():
            merged[_text_key(stat["name"])] = {
                "name": stat["name"],
                "technology_count": stat["technology_count"],
                "mention_count": stat["mention_count"],
                "ids": stat["ids"],
            }

    kept = [
        record
        for record in merged.values()
        if record["mention_count"] >= min_count or record["technology_count"] >= min_count
    ]
    total_mentions = sum(record["mention_count"] for record in kept)
    items = [
        CategoryStat(
            name=record["name"],
            technology_count=record["technology_count"],
            mention_count=record["mention_count"],
            percentage=round(record["mention_count"] / total_mentions * 100, 1) if total_mentions else 0.0,
            evidence_ids=record["ids"],
        )
        for record in kept
    ]
    items.sort(key=lambda item: (-item.mention_count, item.name))
    return CategoryDistribution(items=items, summary=_stat_text(distribution.summary))


def _clean_frameworks(
    ecosystem: FrameworkEcosystem,
    valid: set[str],
    pages: list[dict],
) -> FrameworkEcosystem:
    merged: dict[str, dict] = {}
    for item in ecosystem.items:
        name = _stat_text(item.name)
        key = _tech_key(name)
        ids = filter_evidence(item.evidence_ids, valid) or _fallback_ids(name, pages)
        if not key or not ids:
            continue
        record = merged.setdefault(
            key,
            {
                "names": [name],
                "type": _stat_text(item.type),
                "category": _stat_text(item.category),
                "description": _stat_text(item.description),
                "related": [],
                "evidence": [],
                "ids": [],
            },
        )
        record["names"].append(name)
        record["type"] = record["type"] or _stat_text(item.type)
        record["category"] = record["category"] or _stat_text(item.category)
        record["description"] = record["description"] or _stat_text(item.description)
        record["related"] = list(
            dict.fromkeys(
                record["related"] + [_stat_text(name) for name in item.related_technologies if _stat_text(name)]
            )
        )
        evidence = _stat_text(item.evidence)
        if evidence:
            record["evidence"].append(evidence)
        record["ids"] = list(dict.fromkeys(record["ids"] + ids))

    items = [
        FrameworkItem(
            name=_display_name(key, record["names"]),
            type=record["type"],
            category=record["category"],
            description=record["description"],
            related_technologies=record["related"],
            evidence="；".join(dict.fromkeys(record["evidence"])),
            evidence_ids=record["ids"],
        )
        for key, record in merged.items()
    ]
    return FrameworkEcosystem(items=items, summary=_stat_text(ecosystem.summary))


def _clean_trends_group(
    trends: TechnologyTrends,
    valid: set[str],
    pages: list[dict],
) -> TechnologyTrends:
    merged: dict[str, dict] = {}
    for item in trends.trends:
        name = _stat_text(item.name)
        key = _tech_key(name)
        ids = filter_evidence(item.evidence_ids, valid) or _fallback_ids(name, pages)
        if not key or not ids:
            continue
        record = merged.setdefault(
            key,
            {
                "names": [name],
                "category": _stat_text(item.category),
                "trend_type": item.trend_type,
                "description": _stat_text(item.description),
                "time_range": _stat_text(item.time_range),
                "changes": [],
                "evidence": [],
                "ids": [],
            },
        )
        record["names"].append(name)
        record["category"] = record["category"] or _stat_text(item.category)
        if _TREND_RANK.get(item.trend_type, 0) > _TREND_RANK.get(record["trend_type"], 0):
            record["trend_type"] = item.trend_type
        record["description"] = record["description"] or _stat_text(item.description)
        record["time_range"] = record["time_range"] or _stat_text(item.time_range)
        record["changes"] = list(
            dict.fromkeys(record["changes"] + [_stat_text(point) for point in item.change_points if _stat_text(point)])
        )
        evidence = _stat_text(item.evidence)
        if evidence:
            record["evidence"].append(evidence)
        record["ids"] = list(dict.fromkeys(record["ids"] + ids))

    signals = [
        TrendSignal(
            name=_display_name(key, record["names"]),
            category=record["category"],
            trend_type=record["trend_type"],
            description=record["description"],
            time_range=record["time_range"],
            change_points=record["changes"],
            evidence="；".join(dict.fromkeys(record["evidence"])),
            evidence_ids=record["ids"],
        )
        for key, record in merged.items()
    ]
    signals.sort(key=lambda item: (-_TREND_RANK.get(item.trend_type, 0), item.name))

    problems: dict[str, dict] = {}
    for item in trends.problems:
        name = _stat_text(item.name)
        key = _tech_key(name)
        ids = filter_evidence(item.evidence_ids, valid) or _fallback_ids(name, pages)
        if not key or not ids:
            continue
        record = problems.setdefault(
            key,
            {
                "names": [name],
                "category": _stat_text(item.category),
                "description": _stat_text(item.description),
                "impact": _stat_text(item.impact),
                "related": [],
                "evidence": [],
                "ids": [],
            },
        )
        record["names"].append(name)
        record["category"] = record["category"] or _stat_text(item.category)
        record["description"] = record["description"] or _stat_text(item.description)
        record["impact"] = record["impact"] or _stat_text(item.impact)
        record["related"] = list(
            dict.fromkeys(
                record["related"] + [_stat_text(name) for name in item.related_technologies if _stat_text(name)]
            )
        )
        evidence = _stat_text(item.evidence)
        if evidence:
            record["evidence"].append(evidence)
        record["ids"] = list(dict.fromkeys(record["ids"] + ids))

    problem_items = [
        TechnologyProblem(
            name=_display_name(key, record["names"]),
            category=record["category"],
            description=record["description"],
            impact=record["impact"],
            related_technologies=record["related"],
            evidence="；".join(dict.fromkeys(record["evidence"])),
            evidence_ids=record["ids"],
        )
        for key, record in problems.items()
    ]
    return TechnologyTrends(
        trends=signals,
        problems=problem_items,
        summary=_stat_text(trends.summary),
    )


def _clean_scenarios(
    ranking: ScenarioRanking,
    valid: set[str],
    pages: list[dict],
    total_sources: int,
    min_count: int,
) -> ScenarioRanking:
    merged: dict[str, dict] = {}
    for item in ranking.items:
        name = _stat_text(item.name)
        key = normalize_skill(name)
        ids = filter_evidence(item.evidence_ids, valid) or _fallback_ids(name, pages)
        if not key or not ids:
            continue
        count = max(int(item.count or 0), len(ids))
        if total_sources:
            count = min(count, total_sources)
        record = merged.setdefault(
            key,
            {
                "name": name,
                "count": 0,
                "related": [],
                "evidence": [],
                "ids": [],
            },
        )
        record["count"] = max(record["count"], count, len(ids))
        record["related"] = list(
            dict.fromkeys(
                record["related"] + [_stat_text(name) for name in item.related_technologies if _stat_text(name)]
            )
        )
        evidence = _stat_text(item.evidence)
        if evidence:
            record["evidence"].append(evidence)
        record["ids"] = list(dict.fromkeys(record["ids"] + ids))

    items = [
        ScenarioStat(
            name=record["name"],
            count=record["count"],
            percentage=round(min(record["count"] / total_sources * 100, 100), 1) if total_sources else 0.0,
            related_technologies=record["related"],
            evidence="；".join(dict.fromkeys(record["evidence"])),
            evidence_ids=record["ids"],
        )
        for record in merged.values()
        if record["count"] >= min_count
    ]
    items.sort(key=lambda item: (-item.count, item.name))
    return ScenarioRanking(items=items, summary=_stat_text(ranking.summary))


def _clean_scenario_trends(
    trends: ScenarioTrends,
    pages: list[dict],
    valid: set[str],
    fallback_months: list[str],
    min_count: int,
) -> ScenarioTrends:
    months = _clean_months(trends.months) or fallback_months
    page_months = {str(page.get("evidence_id")): _month_of(page.get("published")) for page in pages}
    derived = not _clean_months(trends.months) and bool(months)

    merged: dict[str, dict] = {}
    for item in trends.items:
        name = _stat_text(item.name)
        key = normalize_skill(name)
        ids = filter_evidence(item.evidence_ids, valid) or _fallback_ids(name, pages)
        if not key or not ids:
            continue
        counts = _align_counts(item.monthly_counts, len(months))
        if derived:
            counts = _counts_from_evidence(ids, months, page_months)
        record = merged.setdefault(
            key,
            {
                "name": name,
                "counts": [0] * len(months),
                "trend": item.trend,
                "evidence": [],
                "ids": [],
            },
        )
        if len(counts) == len(months):
            record["counts"] = [max(left, right) for left, right in zip(record["counts"], counts)]
        if _SCENARIO_TREND_RANK.get(item.trend, 0) > _SCENARIO_TREND_RANK.get(record["trend"], 0):
            record["trend"] = item.trend
        evidence = _stat_text(item.evidence)
        if evidence:
            record["evidence"].append(evidence)
        record["ids"] = list(dict.fromkeys(record["ids"] + ids))

    items = [
        ScenarioTrendItem(
            name=record["name"],
            monthly_counts=record["counts"],
            trend=record["trend"],
            evidence="；".join(dict.fromkeys(record["evidence"])),
            evidence_ids=record["ids"],
        )
        for record in merged.values()
        if sum(record["counts"]) >= min_count
    ]
    items.sort(key=lambda item: (-sum(item.monthly_counts), -_SCENARIO_TREND_RANK.get(item.trend, 0), item.name))
    return ScenarioTrends(months=months, items=items, summary=_stat_text(trends.summary))


def _clean_applications(
    applications: TechnologyApplications,
    pages: list[dict],
    valid: set[str],
    total_sources: int,
    min_count: int,
    frequency_months: list[str],
) -> TechnologyApplications:
    ranking = _clean_scenarios(
        applications.scenario_ranking, valid, pages, total_sources, min_count
    )
    trends = _clean_scenario_trends(
        applications.scenario_trends, pages, valid, frequency_months, min_count
    )
    scenarios = {item.name for item in ranking.items}
    scenarios.update(item.name for item in trends.items)
    return TechnologyApplications(
        total_scenarios=len(scenarios),
        total_mentions=sum(item.count for item in ranking.items),
        scenario_ranking=ranking,
        scenario_trends=trends,
    )


def _normalize(
    result: TrendResult,
    pages: list[dict],
    coverage: str,
    sample_size: int,
    time_window: str = "",
) -> TrendResult:
    valid = valid_evidence_ids(pages)
    total = sample_size if sample_size > 0 else len(pages)
    min_count = _min_count(total)

    frequency = _clean_frequency(result.technology_frequency, pages, valid, total, min_count)
    categories = _clean_categories(
        result.category_distribution, frequency.fishbone.branches, pages, valid, min_count
    )
    ecosystem = _clean_frameworks(result.framework_ecosystem, valid, pages)
    trends = _clean_trends_group(result.technology_trends, valid, pages)
    applications = _clean_applications(
        result.technology_applications, pages, valid, total, min_count, frequency.months
    )

    technologies = [
        technology
        for branch in frequency.fishbone.branches
        for technology in branch.technologies
    ]
    technologies.sort(key=lambda item: (-item.total_count, item.name))
    total_technologies = len(technologies)
    top_technologies = [item.name for item in technologies[:5]]

    model_overview = result.overview
    derived_high = sum(1 for item in technologies if item.percentage >= 30.0)
    high_frequency_count = min(
        max(int(model_overview.high_frequency_count or 0) or derived_high, 0),
        total_technologies,
    )
    emerging_count = sum(1 for item in trends.trends if item.trend_type == "emerging")
    top_category = (
        frequency.fishbone.branches[0].category
        if frequency.fishbone.branches
        else categories.items[0].name
        if categories.items
        else _stat_text(model_overview.top_category)
    )

    result.overview = TrendOverview(
        total_technologies=total_technologies
        or sum(item.technology_count for item in categories.items)
        or len(model_overview.top_technologies),
        high_frequency_count=high_frequency_count,
        emerging_count=emerging_count,
        application_scenario_count=applications.total_scenarios,
        top_technologies=top_technologies
        or [_stat_text(name) for name in model_overview.top_technologies if _stat_text(name)][:5],
        top_category=top_category,
        time_range=_stat_text(model_overview.time_range)
        or frequency.time_range
        or clean_text(time_window),
        research_summary=_stat_text(model_overview.research_summary),
    )
    result.category_distribution = categories
    result.technology_frequency = frequency
    result.framework_ecosystem = ecosystem
    result.technology_trends = trends
    result.technology_applications = applications

    result.coverage = merge_coverage(result.coverage, coverage)
    result.sample_size = total
    result.notes = _stat_text(result.notes)
    return result


def _items(result: TrendResult) -> list[dict]:
    """右侧面板按「总览 + 五个矩阵块」逐块下发，每块携带完整结构化数据。"""
    items: list[dict] = []
    overview = result.overview

    if overview.research_summary or overview.total_technologies or overview.top_technologies:
        items.append(
            {
                "id": "trend:overview",
                "key": "trend:overview",
                "kind": "fact",
                "label": "技术概览",
                "text": overview.research_summary,
                "data": {"overview": overview.model_dump(), "sample_size": result.sample_size},
            }
        )

    categories = result.category_distribution
    if categories.items:
        items.append(
            {
                "id": "trend:category",
                "key": "trend:category",
                "kind": "fact",
                "label": "技术领域分布",
                "text": categories.summary,
                "data": categories.model_dump(),
            }
        )

    frequency = result.technology_frequency
    if any(branch.technologies for branch in frequency.fishbone.branches):
        items.append(
            {
                "id": "trend:frequency",
                "key": "trend:frequency",
                "kind": "fact",
                "label": "高频技术",
                "text": frequency.summary,
                "data": frequency.model_dump(),
            }
        )

    ecosystem = result.framework_ecosystem
    if ecosystem.items:
        items.append(
            {
                "id": "trend:framework",
                "key": "trend:framework",
                "kind": "fact",
                "label": "技术生态",
                "text": ecosystem.summary,
                "data": ecosystem.model_dump(),
            }
        )

    trends = result.technology_trends
    if trends.trends or trends.problems:
        items.append(
            {
                "id": "trend:trends",
                "key": "trend:trends",
                "kind": "fact",
                "label": "趋势与问题",
                "text": trends.summary,
                "data": trends.model_dump(),
            }
        )

    applications = result.technology_applications
    if applications.scenario_ranking.items or applications.scenario_trends.items:
        items.append(
            {
                "id": "trend:applications",
                "key": "trend:applications",
                "kind": "fact",
                "label": "应用与场景",
                "text": applications.scenario_ranking.summary or applications.scenario_trends.summary,
                "data": applications.model_dump(),
            }
        )

    return items


async def run(llm, brief: Brief, collected: dict, run_id: str | None = None) -> dict:
    """跑 trend agent；collected 是采集节点按维度汇总的单桶结果。"""
    writer = safe_writer()
    pages = collected.get("pages") or []
    sample_size = int(collected.get("sample_size") or len(pages))
    writer({"type": "node.enter", "node": "trend", "label": "技术趋势"})

    if not pages:
        writer({"type": "extract.chunk", "dim": "trend", "items": []})
        writer({"type": "extract.done", "dim": "trend", "count": 0, "coverage": "none"})
        writer({"type": "node.exit", "node": "trend", "state": "done", "text": "0 页"})
        return {"result": _empty(), "pages": [], "coverage": "none", "sample_size": 0}

    writer({"type": "agent_start", "agent": "trend", "label": "技术趋势 agent"})
    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"{run_id or uuid.uuid4().hex}:trend"}}
    message = (
        f"<brief>\n{brief.model_dump_json(indent=2)}\n</brief>\n\n"
        f"<pages>\n{format_pages(pages, MAX_GROUP_CHARS)}\n</pages>"
    )
    structured = await run_structured(agent, _SYSTEM_PROMPT, message, config, stage="trend")

    if structured is None:
        stage_warning("extract", "未返回结构化结果，使用兜底结果", dim="trend")
        result = TrendResult.model_validate(_empty())
    else:
        try:
            result = TrendResult.model_validate(structured)
        except Exception as exc:
            stage_warning("extract", "结果校验失败，使用兜底结果", dim="trend", error=exc)
            result = TrendResult.model_validate(_empty())
        result = _normalize(
            result,
            pages,
            str(collected.get("coverage") or "none"),
            sample_size,
            brief.time_window,
        )

    items = _items(result)
    for start in range(0, len(items), 4):
        writer({"type": "extract.chunk", "dim": "trend", "items": items[start:start + 4]})
    writer(
        {
            "type": "extract.done",
            "dim": "trend",
            "count": len(items),
            "coverage": result.coverage,
        }
    )
    writer({"type": "agent_end", "agent": "trend", "label": "技术趋势 agent"})
    writer(
        {
            "type": "node.exit",
            "node": "trend",
            "state": "done",
            "text": f"{sample_size} 页 · {len(items)} 条",
        }
    )
    return {
        "result": result.model_dump(),
        "pages": pages,
        "coverage": result.coverage,
        "sample_size": sample_size,
    }
