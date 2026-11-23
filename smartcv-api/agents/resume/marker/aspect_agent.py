"""动态调研方面 agent：一个用户选择的方面对应一个并行节点。

固定维度 jobs / trend 有专门的 schema；薪资、公司背景、面试流程与自定义方面
共用这里的通用 `AspectResult`，按「概览 + 八个内容块」输出带证据的结构化结果，
供右侧面板与报告复用。
"""

import uuid
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.utils.dims import MAX_GROUP_CHARS
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
    safe_writer,
)
from agents.resume.marker.schemas import AspectResult, Brief
from agents.resume.marker.utils.common import (
    clean_text,
    filter_evidence,
    format_pages,
    valid_evidence_ids,
)
from agents.resume.marker.utils.stage_log import stage_warning
from agents.resume.optimize.utils.checkpointer import get_checkpointer

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "extract" / "aspect.md").read_text(encoding="utf-8")

# 面板与报告共用的八个内容块：短键 / 展示名 / AspectResult 字段名。
_SECTIONS = [
    ("basic", "基本情况", "basic_information"),
    ("core", "核心内容", "core_content"),
    ("directions", "重点方向", "key_directions"),
    ("performance", "具体表现", "specific_performance"),
    ("advantages", "优势与特点", "advantages"),
    ("problems", "存在问题", "problems"),
    ("trends", "发展趋势", "development_trends"),
    ("conclusion", "综合分析", "comprehensive_analysis"),
]
_SECTION_ATTRS = [attr for _, _, attr in _SECTIONS]


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=AspectResult,
        middleware=[DropInvalidToolCallsMiddleware()],
        checkpointer=get_checkpointer(),
    )


def _empty() -> dict:
    return AspectResult().model_dump()


def _has_content(section) -> bool:
    """块里有没有正文；evidence_ids 单独判断，不算内容。"""
    for name in type(section).model_fields:
        if name == "evidence_ids":
            continue
        value = getattr(section, name)
        if isinstance(value, list):
            if value:
                return True
        elif value:
            return True
    return False


def _clean_section(section) -> None:
    """统一去空白、去重；空条目直接丢掉，前端不需要再判空。"""
    for name in type(section).model_fields:
        if name == "evidence_ids":
            continue
        value = getattr(section, name)
        if isinstance(value, list):
            cleaned: list[str] = []
            for item in value:
                text = clean_text(str(item))
                if text and text not in cleaned:
                    cleaned.append(text)
            setattr(section, name, cleaned)
        else:
            setattr(section, name, clean_text(value))


def _normalize(result: AspectResult, valid: set[str]) -> None:
    """清洗各块并校验证据；有内容但证据全部失效的块整块丢弃。"""
    for attr in _SECTION_ATTRS:
        section = getattr(result, attr)
        _clean_section(section)
        section.evidence_ids = filter_evidence(section.evidence_ids, valid)
        if _has_content(section) and not section.evidence_ids:
            setattr(result, attr, type(section)())
    overview = result.overview
    overview.research_scope = clean_text(overview.research_scope)
    overview.research_summary = clean_text(overview.research_summary)
    result.notes = clean_text(result.notes)


def _items(dim: str, result: AspectResult, coverage: str, sample_size: int) -> list[dict]:
    """右侧面板按「概览 + 八个内容块」逐块下发，每块携带完整结构化数据。"""
    items: list[dict] = []
    overview = result.overview
    if overview.research_scope or overview.research_summary:
        items.append(
            {
                "id": f"{dim}:overview",
                "key": f"{dim}:overview",
                "kind": "fact",
                "label": "调研概览",
                "text": overview.research_summary,
                "data": {
                    "overview": overview.model_dump(),
                    "coverage": coverage,
                    "sample_size": sample_size,
                },
            }
        )

    for short_key, label, attr in _SECTIONS:
        section = getattr(result, attr)
        if not _has_content(section):
            continue
        items.append(
            {
                "id": f"{dim}:{short_key}",
                "key": f"{dim}:{short_key}",
                "kind": "fact",
                "label": label,
                "text": section.summary,
                "evidence_ids": section.evidence_ids,
                "data": section.model_dump(),
            }
        )
    return items


async def run(
    llm,
    brief: Brief,
    dim: str,
    label: str,
    collected: dict,
    run_id: str | None = None,
) -> dict:
    """跑一个动态方面 agent；返回结构与固定维度 agent 一致。"""
    writer = safe_writer()
    pages = collected.get("pages") or []
    sample_size = len(pages)
    writer({"type": "node.enter", "node": dim, "label": label})

    if not pages:
        writer({"type": "extract.chunk", "dim": dim, "items": []})
        writer({"type": "extract.done", "dim": dim, "count": 0, "coverage": "none"})
        writer({"type": "node.exit", "node": dim, "state": "done", "text": "0 条资料"})
        return {
            "result": _empty(),
            "pages": [],
            "coverage": "none",
            "sample_size": 0,
        }

    writer({"type": "agent_start", "agent": dim, "label": f"{label} agent"})
    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"{run_id or uuid.uuid4().hex}:{dim}"}}
    message = (
        f"<brief>\n{brief.model_dump_json(indent=2)}\n</brief>\n\n"
        f"<aspect>\nid: {dim}\nlabel: {label}\n</aspect>\n\n"
        f"<pages>\n{format_pages(pages, MAX_GROUP_CHARS)}\n</pages>"
    )
    structured = await run_structured(agent, _SYSTEM_PROMPT, message, config, stage=dim)

    if structured is None:
        stage_warning("extract", "未返回结构化结果，使用兜底结果", dim=dim)
        result = AspectResult.model_validate(_empty())
    else:
        try:
            result = AspectResult.model_validate(structured)
        except Exception as exc:
            stage_warning("extract", "结果校验失败，使用兜底结果", dim=dim, error=exc)
            result = AspectResult.model_validate(_empty())
        _normalize(result, valid_evidence_ids(pages))

    coverage = str(collected.get("coverage") or "none")
    meta = {
        "result": {**result.model_dump(), "coverage": coverage, "sample_size": sample_size},
        "pages": pages,
        "coverage": coverage,
        "sample_size": sample_size,
    }

    items = _items(dim, result, coverage, sample_size)
    for start in range(0, len(items), 4):
        writer({"type": "extract.chunk", "dim": dim, "items": items[start:start + 4]})
    writer(
        {
            "type": "extract.done",
            "dim": dim,
            "count": len(items),
            "coverage": coverage,
        }
    )
    writer({"type": "agent_end", "agent": dim, "label": f"{label} agent"})
    writer(
        {
            "type": "node.exit",
            "node": dim,
            "state": "done",
            "text": f"{sample_size} 条资料 · {len(items)} 块",
        }
    )
    return meta
