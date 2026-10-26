"""主 agent（总结）：根据诊断 + 实际改动清单，输出给用户的简短修改说明。

所有事件（agent_start / 逐 token delta / agent_end）都经 get_stream_writer()
发成 LangGraph custom 事件，由外层 optimize_graph 转发成 SSE 推到前端。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer

from agents.optimize.utils.diagnosis import format_diagnosis

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_summarize.md").read_text(encoding="utf-8")


def build_agent(llm):
    return create_agent(model=llm, tools=[])


async def run(
    llm,
    diagnosis: list[dict],
    patches: list[dict],
    reviews: list[dict] | None = None,
    session_id: str | None = None,
) -> str:
    """跑主 agent（总结）：发 agent_start → 逐 token 发 delta(summary) → agent_end，返回修改说明。"""
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "summarize", "label": "摘要 agent"})
    agent = build_agent(llm)
    if patches:
        # 面向用户的清单不带坐标，避免位置编号泄漏进修改说明
        changes = "\n".join(f"- 「{p['old']}」→「{p['new']}」" for p in patches)
    else:
        changes = "（没有实际改动）"
    # 总结面向用户，不带坐标；带上审查结果，模型才知道哪些诊断没改以及原因
    diagnosis_text = format_diagnosis(diagnosis, include_coords=False, reviews=reviews)
    # 数量由代码算好传给模型：LLM 自己数条目会数错（16 条里改了 8 条却写成 7 条）
    reviews = reviews or []
    total = len(diagnosis)
    changed = len(patches)
    skipped = sum(1 for r in reviews if r.get("status") == "skip")
    failed = sum(1 for r in reviews if r.get("status") == "failed")
    unpatched = sum(1 for r in reviews if r.get("status") == "change")
    unreviewed = sum(1 for r in reviews if r.get("status") == "pending")
    stats = (
        f"诊断总数：{total} 处\n"
        f"实际修改：{changed} 处\n"
        f"未修改：{total - changed} 处"
        f"（不需要改 {skipped}、执行失败 {failed}、待执行 {unpatched}、未审查 {unreviewed}）"
    )
    message = (
        f"数量统计（系统已算好，必须原样使用）：\n{stats}\n\n"
        f"诊断结果：\n{diagnosis_text}\n\n"
        f"本次实际改动清单：\n{changes}\n\n"
        f"请用简短中文总结这次优化：改了什么；有诊断没改的话，按处理结果说明原因。"
    )
    answer_parts: list[str] = []
    async for item in agent.astream(
        {"messages": [{"type": "system", "content": _SYSTEM_PROMPT}, {"type": "human", "content": message}]},
        stream_mode=["messages", "custom"],
        config={"recursion_limit": 20, "configurable": {"session_id": session_id}},
    ):
        if not isinstance(item, tuple):
            continue
        mode, chunk = item
        if mode == "custom":
            writer(chunk)
            continue
        # 推理模型的思考在 reasoning_content、答案在 content，分开打 kind 发给前端
        msg = chunk[0]
        kwargs = getattr(msg, "additional_kwargs", {}) or {}
        thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
        content = getattr(msg, "content", "") or ""
        if thinking:
            writer({"type": "delta", "stage": "summary", "text": thinking, "kind": "thinking"})
        if content:
            # 只把回答正文作为 summary 返回，思考过程只流式展示、不落进结果
            answer_parts.append(content)
            writer({"type": "delta", "stage": "summary", "text": content, "kind": "answer"})
    summary = "".join(answer_parts).strip()
    writer({"type": "agent_end", "agent": "summarize", "label": "摘要 agent"})
    logger.info("summarize-agent 输出 %d 字", len(summary))
    return summary
