"""Agent 3 · 策略总结：把市场结果（可选叠加简历画像）变成定位、差距与行动优先级。

没有简历时只给市场层面的建议，`gaps` 必须为空。
"""

import uuid
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
    safe_writer,
)
from agents.resume.marker.schemas import Brief, StrategyResult
from agents.resume.marker.utils.common import clean_text, filter_evidence, merge_coverage
from agents.resume.marker.utils.profile import verified_locations as profile_verified_locations
from agents.resume.marker.utils.stage_log import stage_exception, stage_warning
from agents.resume.optimize.utils.checkpointer import get_checkpointer

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "strategy" / "strategy.md").read_text(encoding="utf-8")


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=StrategyResult,
        middleware=[DropInvalidToolCallsMiddleware()],
        checkpointer=get_checkpointer(),
    )


def _fallback() -> dict:
    return {
        "positioning": {},
        "gaps": [],
        "priorities": [],
        "writing_tips": [],
        "risks": [],
        "coverage": "none",
        "notes": "",
    }


def _verified_locations(profile: dict | None) -> set[str]:
    return profile_verified_locations(profile)


def _clean_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in values:
        text = clean_text(str(item))
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _positioning_has_content(result: StrategyResult) -> bool:
    positioning = result.positioning
    return bool(
        positioning.career_positioning
        or positioning.market_level
        or positioning.job_match
        or positioning.competitive_advantages
        or positioning.competitive_disadvantages
    )


def _normalize(
    result: StrategyResult,
    *,
    has_resume: bool,
    valid_ids: set[str],
    profile: dict | None,
    market_coverage: str,
) -> StrategyResult:
    locations = _verified_locations(profile)

    positioning = result.positioning
    positioning.career_positioning = clean_text(positioning.career_positioning)
    positioning.market_level = clean_text(positioning.market_level)
    positioning.job_match = clean_text(positioning.job_match)
    positioning.competitive_advantages = _clean_list(positioning.competitive_advantages)
    positioning.competitive_disadvantages = _clean_list(positioning.competitive_disadvantages)

    # 差距 / 写法提示 / 风险都必须能指回来源；指不回就整条丢弃。
    kept_gaps = []
    for gap in result.gaps:
        gap.requirement = clean_text(gap.requirement)
        gap.current_level = clean_text(gap.current_level)
        gap.gap_analysis = clean_text(gap.gap_analysis)
        gap.improvement_direction = clean_text(gap.improvement_direction)
        gap.evidence_ids = _clean_list(filter_evidence(gap.evidence_ids, valid_ids))
        if not gap.evidence_ids:
            continue
        gap.resume_locations = [item for item in _clean_list(gap.resume_locations) if item in locations]
        if not (gap.requirement or gap.current_level or gap.gap_analysis or gap.improvement_direction):
            continue
        kept_gaps.append(gap)
    result.gaps = kept_gaps if has_resume else []

    priorities = []
    for item in sorted(result.priorities, key=lambda priority: priority.rank or 10**6):
        item.task = clean_text(item.task)
        item.reason = clean_text(item.reason)
        item.expected_outcome = clean_text(item.expected_outcome)
        item.related_gaps = _clean_list(item.related_gaps)
        if not item.task:
            continue
        item.rank = len(priorities) + 1
        priorities.append(item)
    result.priorities = priorities

    kept_tips = []
    for tip in result.writing_tips:
        tip.resume_location = clean_text(tip.resume_location)
        tip.problem = clean_text(tip.problem)
        tip.optimization = clean_text(tip.optimization)
        tip.reference_requirement = clean_text(tip.reference_requirement)
        tip.suggested_keywords = _clean_list(tip.suggested_keywords)
        tip.evidence_ids = _clean_list(filter_evidence(tip.evidence_ids, valid_ids))
        if not tip.evidence_ids:
            continue
        if not (
            tip.resume_location
            or tip.problem
            or tip.optimization
            or tip.reference_requirement
            or tip.suggested_keywords
        ):
            continue
        kept_tips.append(tip)
    result.writing_tips = kept_tips

    kept_risks = []
    for risk in result.risks:
        risk.risk_type = clean_text(risk.risk_type)
        risk.risk = clean_text(risk.risk)
        risk.impact = clean_text(risk.impact)
        risk.response = clean_text(risk.response)
        risk.evidence_ids = _clean_list(filter_evidence(risk.evidence_ids, valid_ids))
        if not risk.evidence_ids:
            continue
        if not (risk.risk_type or risk.risk or risk.impact or risk.response):
            continue
        kept_risks.append(risk)
    result.risks = kept_risks

    result.coverage = merge_coverage(result.coverage, market_coverage)
    result.notes = clean_text(result.notes)
    return result


def _items(result: StrategyResult) -> list[dict]:
    """右侧面板按「定位 + 四类建议」逐块下发，每块携带完整结构化数据。"""
    items: list[dict] = []
    if _positioning_has_content(result) or result.notes:
        items.append(
            {
                "id": "strategy:positioning",
                "key": "strategy:positioning",
                "kind": "fact",
                "label": "竞争力定位",
                "text": result.positioning.career_positioning,
                "data": {
                    "positioning": result.positioning.model_dump(),
                    "coverage": result.coverage,
                    "notes": result.notes,
                },
            }
        )

    sections = (
        ("gaps", "能力差距", result.gaps),
        ("priorities", "改进优先级", result.priorities),
        ("writing", "简历优化建议", result.writing_tips),
        ("risks", "求职风险", result.risks),
    )
    for key, label, entries in sections:
        if not entries:
            continue
        items.append(
            {
                "id": f"strategy:{key}",
                "key": f"strategy:{key}",
                "kind": "fact",
                "label": label,
                "text": "",
                "data": {"items": [entry.model_dump() for entry in entries]},
            }
        )
    return items


async def run(
    llm,
    brief: Brief,
    market: dict,
    profile: dict | None,
    valid_ids: set[str],
    run_id: str | None = None,
) -> dict:
    """跑策略总结 agent，返回结构化策略。"""
    writer = safe_writer()
    writer({"type": "node.enter", "node": "strategy", "label": "策略总结"})

    has_resume = bool(brief.has_resume and profile)
    market_payload = {
        "coverage": market.get("coverage"),
        "sample_size": market.get("sample_size"),
        "jobs": market.get("jobs"),
        "trend": market.get("trend"),
        "aspects": market.get("aspects"),
        "synthesis": market.get("synthesis"),
    }
    message = (
        f"<brief>\n{brief.model_dump_json(indent=2)}\n</brief>\n\n"
        f"<market>\n{market_payload}\n</market>"
    )
    if has_resume:
        message += f"\n\n<resume>\n{profile}\n</resume>"

    writer({"type": "agent_start", "agent": "strategy", "label": "策略总结 agent"})
    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"{run_id or uuid.uuid4().hex}:strategy"}}
    try:
        structured = await run_structured(agent, _SYSTEM_PROMPT, message, config, stage="strategy")
    except Exception:
        stage_exception("strategy", "模型调用失败")
        structured = None

    if structured is None:
        stage_warning("strategy", "未返回结构化结果，使用兜底策略")
        result = StrategyResult.model_validate(_fallback())
    else:
        try:
            result = StrategyResult.model_validate(structured)
        except Exception as exc:
            stage_warning("strategy", "结果校验失败，使用兜底策略", error=exc)
            result = StrategyResult.model_validate(_fallback())

    result = _normalize(
        result,
        has_resume=has_resume,
        valid_ids=valid_ids,
        profile=profile,
        market_coverage=str(market.get("coverage") or "none"),
    )

    items = _items(result)
    for start in range(0, len(items), 4):
        writer({"type": "strategy.chunk", "items": items[start:start + 4]})
    writer(
        {
            "type": "strategy.done",
            "count": len(items),
            "coverage": result.coverage,
            "gaps": len(result.gaps),
        }
    )
    writer({"type": "agent_end", "agent": "strategy", "label": "策略总结 agent"})
    writer(
        {
            "type": "node.exit",
            "node": "strategy",
            "state": "done",
            "text": f"{len(result.gaps)} 项差距 · {len(result.priorities)} 条优先级",
        }
    )
    return {"result": result.model_dump(), "coverage": result.coverage}
