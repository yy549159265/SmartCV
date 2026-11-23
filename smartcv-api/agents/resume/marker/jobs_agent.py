"""Agent 1 · jobs：从招聘页面抽取岗位分布、技术需求、能力需求与任职要求。"""

import re
import uuid
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.utils.dims import MAX_GROUP_CHARS
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
    safe_writer,
)
from agents.resume.marker.schemas import (
    AbilityMatrix,
    AbilityRequirement,
    Brief,
    CountStat,
    JobDistribution,
    JobsResult,
    QualificationMatrix,
    ResearchInfo,
    SalaryMatrix,
    SalaryRange,
    TechnicalMatrix,
    TechnicalRequirement,
)
from agents.resume.marker.utils.common import (
    clean_text,
    filter_evidence,
    format_pages,
    merge_coverage,
    valid_evidence_ids,
)
from agents.resume.marker.utils.stage_log import stage_warning
from agents.resume.optimize.utils.checkpointer import get_checkpointer

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "extract" / "jobs.md").read_text(encoding="utf-8")

# 招聘统计的频次门槛：至少 2 个有效页面提及才纳入；样本少于 3 页时放宽到 1。
_MIN_SAMPLE_FOR_THRESHOLD = 3
_DEFAULT_STATISTICS_NOTE = "频次以有效页面数为分母，同一页面内同一项只统计一次。"

_REQUIREMENT_RANK = {"unknown": 0, "common": 1, "preferred": 2, "must_have": 3}
_IMPORTANCE_RANK = {"low": 1, "medium": 2, "high": 3}
_COVERAGE_TO_INTERNAL = {"complete": "full", "partial": "partial", "insufficient": "none"}
_INTERNAL_TO_COVERAGE = {"full": "complete", "partial": "partial", "none": "insufficient"}

# 提示词已禁止分式；代码再兜一层，把「5/9 页」「3 个/9 个有效页面」改成「5 个页面」。
_FRACTION_RE = re.compile(r"(\d+)\s*(?:个)?\s*/\s*(\d+)\s*(?:个)?\s*(?:有效)?\s*页(?:面)?")


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=JobsResult,
        middleware=[DropInvalidToolCallsMiddleware()],
        checkpointer=get_checkpointer(),
    )


def _empty() -> dict:
    return JobsResult().model_dump()


def _stat_text(value: object) -> str:
    """清理文字字段，并去掉「xxx/xxx 页」这类分式。"""
    return _FRACTION_RE.sub(r"\1 个页面", clean_text(value))


def _min_count(total: int) -> int:
    return 2 if total >= _MIN_SAMPLE_FOR_THRESHOLD else 1


def _clean_stats(
    items: list[CountStat],
    cls: type[CountStat],
    valid: set[str],
    total: int,
    min_count: int,
) -> list[CountStat]:
    """过滤单页噪声、合并同名项、按有效页面数重算占比。"""
    merged: dict[str, dict] = {}
    for item in items:
        data = item.model_dump()
        name = clean_text(data.get("name"))
        if not name:
            continue
        count = int(data.get("count") or 0)
        if total > 0:
            count = min(count, total)
        if count < min_count:
            continue

        evidence = filter_evidence(data.get("evidence_ids") or [], valid)
        key = name.casefold()
        current = merged.get(key)
        if current is None:
            data.update(name=name, count=count, evidence_ids=evidence)
            merged[key] = data
            continue

        current["count"] = max(int(current.get("count") or 0), count)
        current["evidence_ids"] = list(
            dict.fromkeys((current.get("evidence_ids") or []) + evidence)
        )
        for field in ("description", "evidence"):
            if not current.get(field) and data.get(field):
                current[field] = data[field]
        if "requirement_level" in data and _REQUIREMENT_RANK.get(
            str(data.get("requirement_level")), 0
        ) > _REQUIREMENT_RANK.get(str(current.get("requirement_level")), 0):
            current["requirement_level"] = data["requirement_level"]
        if "importance" in data and _IMPORTANCE_RANK.get(
            str(data.get("importance")), 0
        ) > _IMPORTANCE_RANK.get(str(current.get("importance")), 0):
            current["importance"] = data["importance"]

    ordered = sorted(
        merged.values(),
        key=lambda item: (-int(item.get("count") or 0), str(item.get("name"))),
    )
    result: list[CountStat] = []
    for data in ordered:
        count = int(data.get("count") or 0)
        data["percentage"] = round(count / total * 100, 1) if total else 0.0
        result.append(cls.model_validate(data))
    return result


def _clean_salary(matrix: SalaryMatrix | None, valid: set[str], total: int) -> SalaryMatrix | None:
    """薪资区间是事实数据，不做频次门槛；只过滤无上下限的空区间。"""
    if matrix is None:
        return None

    ranges: list[SalaryRange] = []
    for item in matrix.salary_ranges:
        if item.min is None and item.max is None:
            continue
        count = max(int(item.count or 0), 1)
        if total > 0:
            count = min(count, total)
        ranges.append(
            SalaryRange(
                min=item.min,
                max=item.max,
                unit=_stat_text(item.unit) or "CNY/month",
                salary_months=item.salary_months,
                count=count,
                evidence_ids=filter_evidence(item.evidence_ids, valid),
            )
        )
    ranges.sort(key=lambda item: (-item.count, item.min if item.min is not None else 0))

    available = max(int(matrix.available_count or 0), 0)
    if total > 0:
        available = min(available, total)
        unavailable = max(0, total - available)
    else:
        unavailable = max(int(matrix.unavailable_count or 0), 0)

    evidence = _stat_text(matrix.evidence)
    summary = _stat_text(matrix.summary)
    if not ranges and available <= 0 and not evidence and not summary:
        return None

    evidence_ids = filter_evidence(matrix.evidence_ids, valid)
    if not evidence_ids:
        evidence_ids = list(
            dict.fromkeys(eid for item in ranges for eid in item.evidence_ids)
        )
    return SalaryMatrix(
        available_count=available,
        unavailable_count=unavailable,
        salary_ranges=ranges,
        evidence=evidence,
        summary=summary,
        evidence_ids=evidence_ids,
    )


def _normalize(
    result: JobsResult,
    pages: list[dict],
    coverage: str,
    sample_size: int,
    topic: str,
) -> JobsResult:
    """过滤单页噪声、合并重复项、按页面数重算占比，并把样本概况与采集结果对齐。"""
    valid = valid_evidence_ids(pages)
    total = sample_size if sample_size > 0 else len(pages)
    min_count = _min_count(total)

    source = result.job_distribution
    job_types = _clean_stats(source.job_types, CountStat, valid, total, min_count)
    companies = _clean_stats(source.company_distribution, CountStat, valid, total, min_count)
    salary = _clean_salary(source.salary_matrix, valid, total)
    result.job_distribution = JobDistribution(
        job_types=job_types,
        company_distribution=companies,
        salary_matrix=salary,
        summary=_stat_text(source.summary),
    )

    technical = result.technical_matrix
    result.technical_matrix = TechnicalMatrix(
        technologies=_clean_stats(
            technical.technologies, TechnicalRequirement, valid, total, min_count
        ),
        summary=_stat_text(technical.summary),
    )

    ability = result.ability_matrix
    result.ability_matrix = AbilityMatrix(
        abilities=_clean_stats(ability.abilities, AbilityRequirement, valid, total, min_count),
        ability_summary=_stat_text(ability.ability_summary),
    )

    qualification = result.qualification_matrix
    result.qualification_matrix = QualificationMatrix(
        education_requirements=_clean_stats(
            qualification.education_requirements, CountStat, valid, total, min_count
        ),
        experience_requirements=_clean_stats(
            qualification.experience_requirements, CountStat, valid, total, min_count
        ),
        project_requirements=_clean_stats(
            qualification.project_requirements, CountStat, valid, total, min_count
        ),
        other_requirements=_clean_stats(
            qualification.other_requirements, CountStat, valid, total, min_count
        ),
        summary=_stat_text(qualification.summary),
    )

    research = result.research_info
    research.research_topic = clean_text(research.research_topic) or topic
    research.total_pages = total
    research.valid_pages = min(max(int(research.valid_pages or 0), 1), total) if total else 0
    research.invalid_pages = max(0, total - research.valid_pages)
    research.companies = (
        [item.name for item in result.job_distribution.company_distribution]
        or [clean_text(name) for name in research.companies if clean_text(name)]
    )

    internal = _COVERAGE_TO_INTERNAL.get(research.coverage, "none")
    merged = merge_coverage(internal, coverage)
    # 有页面但模型说 insufficient 时仍按 partial 处理，避免报告章节被误判成无素材。
    if research.valid_pages > 0 and merged == "none":
        merged = "partial"
    research.coverage = _INTERNAL_TO_COVERAGE[merged]
    result.research_info = research
    result.coverage = merged
    result.sample_size = total

    quality = result.data_quality
    quality.statistics_note = _stat_text(quality.statistics_note) or _DEFAULT_STATISTICS_NOTE
    quality.limitations = [text for text in (_stat_text(item) for item in quality.limitations) if text]
    quality.unverified_items = [
        text for text in (_stat_text(item) for item in quality.unverified_items) if text
    ]
    result.data_quality = quality
    result.notes = _stat_text(result.notes)
    return result


_COVERAGE_LABEL = {
    "complete": "覆盖较完整",
    "partial": "部分信息缺失",
    "insufficient": "样本不足",
}


def _items(result: JobsResult) -> list[dict]:
    """右侧面板按「样本概况 + 四个矩阵」逐块下发，每块带完整结构化数据。"""
    items: list[dict] = []

    info = result.research_info
    if info.total_pages or info.research_topic or info.companies:
        items.append(
            {
                "id": "jobs:research",
                "key": "jobs:research",
                "kind": "fact",
                "label": "样本概况",
                "text": (
                    f"有效 {info.valid_pages} 个页面 · 企业 {len(info.companies)} 家 · "
                    f"{_COVERAGE_LABEL.get(info.coverage, info.coverage)}"
                ),
                "data": {
                    "research_info": info.model_dump(),
                    "data_quality": result.data_quality.model_dump(),
                },
            }
        )

    distribution = result.job_distribution
    if distribution.job_types or distribution.company_distribution or distribution.salary_matrix:
        items.append(
            {
                "id": "jobs:distribution",
                "key": "jobs:distribution",
                "kind": "fact",
                "label": "岗位分布",
                "text": distribution.summary,
                "data": distribution.model_dump(),
            }
        )

    technical = result.technical_matrix
    if technical.technologies:
        items.append(
            {
                "id": "jobs:technical",
                "key": "jobs:technical",
                "kind": "fact",
                "label": "技术需求",
                "text": technical.summary,
                "data": technical.model_dump(),
            }
        )

    ability = result.ability_matrix
    if ability.abilities:
        items.append(
            {
                "id": "jobs:ability",
                "key": "jobs:ability",
                "kind": "fact",
                "label": "能力需求",
                "text": ability.ability_summary,
                "data": ability.model_dump(),
            }
        )

    qualification = result.qualification_matrix
    if (
        qualification.education_requirements
        or qualification.experience_requirements
        or qualification.project_requirements
        or qualification.other_requirements
    ):
        items.append(
            {
                "id": "jobs:qualification",
                "key": "jobs:qualification",
                "kind": "fact",
                "label": "任职要求",
                "text": qualification.summary,
                "data": qualification.model_dump(),
            }
        )

    return items


async def run(llm, brief: Brief, collected: dict, run_id: str | None = None) -> dict:
    """跑 jobs agent；collected 是采集节点按维度汇总的单桶结果。"""
    writer = safe_writer()
    pages = collected.get("pages") or []
    sample_size = int(collected.get("sample_size") or len(pages))
    writer({"type": "node.enter", "node": "jobs", "label": "招聘矩阵"})

    if not pages:
        writer({"type": "extract.chunk", "dim": "jobs", "items": []})
        writer({"type": "extract.done", "dim": "jobs", "count": 0, "coverage": "none"})
        writer({"type": "node.exit", "node": "jobs", "state": "done", "text": "0 页"})
        return {"result": _empty(), "pages": [], "coverage": "none", "sample_size": 0}

    writer({"type": "agent_start", "agent": "jobs", "label": "招聘矩阵 agent"})
    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"{run_id or uuid.uuid4().hex}:jobs"}}
    message = (
        f"<brief>\n{brief.model_dump_json(indent=2)}\n</brief>\n\n"
        f"<pages>\n{format_pages(pages, MAX_GROUP_CHARS)}\n</pages>"
    )
    structured = await run_structured(agent, _SYSTEM_PROMPT, message, config, stage="jobs")

    if structured is None:
        stage_warning("extract", "未返回结构化结果，使用兜底结果", dim="jobs")
        result = JobsResult.model_validate(_empty())
    else:
        try:
            result = JobsResult.model_validate(structured)
        except Exception as exc:
            stage_warning("extract", "结果校验失败，使用兜底结果", dim="jobs", error=exc)
            result = JobsResult.model_validate(_empty())
        result = _normalize(
            result,
            pages,
            str(collected.get("coverage") or "none"),
            sample_size,
            brief.target_role,
        )

    items = _items(result)
    for start in range(0, len(items), 4):
        writer({"type": "extract.chunk", "dim": "jobs", "items": items[start:start + 4]})
    writer(
        {
            "type": "extract.done",
            "dim": "jobs",
            "count": len(items),
            "coverage": result.coverage,
        }
    )
    writer({"type": "agent_end", "agent": "jobs", "label": "招聘矩阵 agent"})
    writer(
        {
            "type": "node.exit",
            "node": "jobs",
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
