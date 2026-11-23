"""跨源合成：把各维度抽取结果合并，发现矛盾、归纳优先级。

只做合并同类项；不重新读网页、不新增事实。维度数量由用户选择决定，
这里不假设一定存在某个固定维度组合。
"""

import json
import uuid
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
    safe_writer,
)
from agents.resume.marker.schemas import Brief, SynthesisResult
from agents.resume.marker.utils.common import filter_evidence, merge_coverage
from agents.resume.marker.utils.stage_log import stage_exception, stage_warning
from agents.resume.optimize.utils.checkpointer import get_checkpointer

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "synthesis" / "synthesis.md").read_text(encoding="utf-8")


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=SynthesisResult,
        middleware=[DropInvalidToolCallsMiddleware()],
        checkpointer=get_checkpointer(),
    )


def _empty() -> dict:
    return {"items": [], "contradictions": [], "coverage": "none", "sample_size": 0, "notes": ""}


def _collect_owner(value: object, dim: str, owner: dict[str, str]) -> None:
    """把每个证据编号映射回它所属的维度；自定义维度用 E1/E2 前缀也能区分。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if (key == "evidence_ids" or key.endswith("_evidence_ids")) and isinstance(item, list):
                for eid in item:
                    owner.setdefault(str(eid), dim)
            else:
                _collect_owner(item, dim, owner)
    elif isinstance(value, list):
        for item in value:
            _collect_owner(item, dim, owner)


def _evidence_owner(results: dict[str, dict]) -> dict[str, str]:
    owner: dict[str, str] = {}
    for dim, result in results.items():
        _collect_owner(result, dim, owner)
    return owner


def _coverage(results: dict[str, dict]) -> str:
    with_pages = sum(
        1 for result in results.values() if int(result.get("sample_size") or 0) > 0
    )
    if with_pages >= 2:
        return "full"
    if with_pages == 1:
        return "partial"
    return "none"


async def run(
    llm,
    brief: Brief,
    results: dict[str, dict],
    labels: dict[str, str],
    valid_ids: set[str],
    run_id: str | None = None,
) -> dict:
    writer = safe_writer()
    writer({"type": "node.enter", "node": "synthesis", "label": "跨源合成"})

    base_coverage = _coverage(results)
    sample_size = sum(int(result.get("sample_size") or 0) for result in results.values())
    if base_coverage == "none":
        writer({"type": "extract.chunk", "dim": "synthesis", "items": []})
        writer({"type": "extract.done", "dim": "synthesis", "count": 0, "coverage": "none"})
        writer({"type": "node.exit", "node": "synthesis", "state": "done", "text": "无素材"})
        return {"result": _empty(), "coverage": "none", "sample_size": 0}

    writer({"type": "agent_start", "agent": "synthesis", "label": "跨源合成 agent"})
    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"{run_id or uuid.uuid4().hex}:synthesis"}}
    blocks = "\n".join(
        f'<group id="{dim}" label="{labels.get(dim, dim)}">\n'
        f"{json.dumps(results.get(dim) or {}, ensure_ascii=False)}\n"
        f"</group>"
        for dim in results
    )
    message = (
        f"<brief>\n{brief.model_dump_json(indent=2)}\n</brief>\n\n"
        f"<groups>\n{blocks}\n</groups>"
    )
    try:
        structured = await run_structured(agent, _SYSTEM_PROMPT, message, config, stage="synthesis")
    except Exception:
        stage_exception("synthesis", "模型调用失败")
        structured = None

    if structured is None:
        stage_warning("synthesis", "未返回结构化结果，跳过合成结论")
        result = SynthesisResult.model_validate(_empty())
    else:
        try:
            result = SynthesisResult.model_validate(structured)
        except Exception as exc:
            stage_warning("synthesis", "结果校验失败，跳过合成结论", error=exc)
            result = SynthesisResult.model_validate(_empty())

    owner = _evidence_owner(results)
    kept = []
    for finding in result.items:
        finding.evidence_ids = filter_evidence(finding.evidence_ids, valid_ids)
        # 跨源结论至少要落在两个不同维度上；同一维度两条不算交叉验证。
        dims = {owner[eid] for eid in finding.evidence_ids if eid in owner}
        if len(dims) >= 2:
            kept.append(finding)
    result.items = kept

    kept_conflicts = []
    for conflict in result.contradictions:
        conflict.evidence_ids = filter_evidence(conflict.evidence_ids, valid_ids)
        if conflict.evidence_ids and conflict.text.strip():
            kept_conflicts.append(conflict)
    result.contradictions = kept_conflicts

    result.coverage = merge_coverage(result.coverage, base_coverage)
    result.sample_size = sample_size

    items = [
        {
            "id": finding.id or f"synthesis:{index}",
            "key": finding.id or f"synthesis:{index}",
            "kind": "fact",
            "label": finding.label,
            "text": finding.text,
            "evidence_ids": finding.evidence_ids,
        }
        for index, finding in enumerate(result.items)
    ]
    for index, contradiction in enumerate(result.contradictions):
        key = f"synthesis:conflict:{index}"
        items.append(
            {
                "id": key,
                "key": key,
                "kind": "fact",
                "label": "来源差异",
                "text": contradiction.text,
                "evidence_ids": contradiction.evidence_ids,
            }
        )
    writer({"type": "extract.chunk", "dim": "synthesis", "items": items})
    writer(
        {
            "type": "extract.done",
            "dim": "synthesis",
            "count": len(items),
            "coverage": result.coverage,
        }
    )
    writer({"type": "agent_end", "agent": "synthesis", "label": "跨源合成 agent"})
    writer(
        {
            "type": "node.exit",
            "node": "synthesis",
            "state": "done",
            "text": f"{len(result.items)} 条跨源结论",
        }
    )
    return {
        "result": result.model_dump(),
        "coverage": result.coverage,
        "sample_size": result.sample_size,
    }
