"""主 agent（总结）：根据诊断 + 实际改动清单，输出给用户的简短修改说明。

所有事件（agent_start / 逐 token delta / agent_end）都经 get_stream_writer()
发成 LangGraph custom 事件，由外层 graph.py 转发成 SSE 推到前端。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer

from agents.resume.optimize.utils.diagnosis import format_diagnosis

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_summarize.md").read_text(encoding="utf-8")


def build_agent(llm):
    return create_agent(model=llm, tools=[])


async def run(
    llm,
    diagnosis: list[dict],
    patches: list[dict],
    reviews: list[dict] | None = None,
    locations: list[str] | None = None,
    session_id: str | None = None,
) -> str:
    """跑主 agent（总结）：发 agent_start → 逐 token 发 delta(summary) → agent_end，返回修改说明。

    locations 与 diagnosis 按序对齐，给每条诊断标出「哪一处」，总结按位置逐行列出。
    """
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "summarize", "label": "摘要 agent"})
    agent = build_agent(llm)
    if patches:
        changes = "\n".join(f"- 「{p['old']}」→「{p['new']}」" for p in patches)
    else:
        changes = "（没有实际改动）"
    diagnosis_text = format_diagnosis(
        diagnosis, include_coords=False, reviews=reviews, locations=locations
    )
    reviews = reviews or []
    total = len(diagnosis)
    changed = len(patches)
    skipped = sum(1 for r in reviews if r.get("status") == "skip")
    failed = sum(1 for r in reviews if r.get("status") == "failed")
    unpatched = sum(1 for r in reviews if r.get("status") == "change")
    unreviewed = sum(1 for r in reviews if r.get("status") == "pending")
    _disposition = lambda value: sum(
        1 for d in diagnosis if (d.get("disposition") or "suggest") == value
    )
    stats = (
        f"诊断总数：{total} 处\n"
        f"实际修改：{changed} 处\n"
        f"未修改：{total - changed} 处"
        f"（不需要改 {skipped}、执行失败 {failed}、待执行 {unpatched}、未审查 {unreviewed}）\n"
        f"档位分布：必须修改 {_disposition('must')}、建议修改 {_disposition('suggest')}、"
        f"可以保留 {_disposition('keep')}、信息不足 {_disposition('insufficient')}"
    )
    message = (
        f"数量统计（系统已算好，必须原样使用）：\n{stats}\n\n"
        f"诊断结果：\n{diagnosis_text}\n\n"
        f"本次实际改动清单：\n{changes}\n\n"
        f"请按输出格式逐条列出：哪一处改了、哪一处没改及原因。"
    )
    answer_parts: list[str] = []
    async for item in agent.astream(
        {"messages": [{"type": "system", "content": _SYSTEM_PROMPT}, {"type": "human", "content": message}]},
        stream_mode=["messages", "custom"],
        config={"configurable": {"session_id": session_id}},
    ):
        if not isinstance(item, tuple):
            continue
        mode, chunk = item
        if mode == "custom":
            writer(chunk)
            continue
        msg = chunk[0]
        kwargs = getattr(msg, "additional_kwargs", {}) or {}
        thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
        content = getattr(msg, "content", "") or ""
        if thinking:
            writer({"type": "delta", "stage": "summary", "text": thinking, "kind": "thinking"})
        if content:
            answer_parts.append(content)
            writer({"type": "delta", "stage": "summary", "text": content, "kind": "answer"})
    summary = "".join(answer_parts).strip()
    writer({"type": "agent_end", "agent": "summarize", "label": "摘要 agent"})
    logger.info("summarize-agent 输出 %d 字", len(summary))
    return summary
