"""主 agent（总结）：根据诊断 + 实际改动清单，输出给用户的简短修改说明。

所有事件（agent_start / 逐 token delta / agent_end）都经 get_stream_writer()
发成 LangGraph custom 事件，由外层 optimize_graph 转发成 SSE 推到前端。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_main.md").read_text(encoding="utf-8")


def build_agent(llm):
    return create_agent(model=llm, tools=[])


async def run(llm, diagnosis: str, patches: list[dict], session_id: str | None = None) -> str:
    """跑主 agent（总结）：发 agent_start → 逐 token 发 delta(summary) → agent_end，返回修改说明。"""
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "summarize", "label": "摘要 agent"})
    agent = build_agent(llm)
    if patches:
        changes = "\n".join(
            f"- [s:{p['s']} r:{p['r']} c:{p['c']} i:{p['i']}] 「{p['old']}」→「{p['new']}」"
            for p in patches
        )
    else:
        changes = "（没有实际改动）"
    message = (
        f"诊断结果：\n{diagnosis}\n\n"
        f"本次实际改动清单：\n{changes}\n\n"
        f"请用简短中文总结这次优化做了什么。"
    )
    parts: list[str] = []
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
        # 推理模型的思考在 reasoning_content、答案在 content，分开打 kind 发给前端
        msg = chunk[0]
        kwargs = getattr(msg, "additional_kwargs", {}) or {}
        thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
        content = getattr(msg, "content", "") or ""
        if thinking:
            parts.append(thinking)
            writer({"type": "delta", "stage": "summary", "text": thinking, "kind": "thinking"})
        if content:
            parts.append(content)
            writer({"type": "delta", "stage": "summary", "text": content, "kind": "answer"})
    summary = "".join(parts).strip()
    writer({"type": "agent_end", "agent": "summarize", "label": "摘要 agent"})
    logger.info("summarize-agent 输出 %d 字", len(summary))
    return summary
