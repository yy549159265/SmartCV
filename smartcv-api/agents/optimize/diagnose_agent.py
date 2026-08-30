"""诊断 agent：结合简历文本（带位置编号）、可选 JD 和用户问题，输出诊断结论。

所有事件（agent_start / 逐 token delta / agent_end）都经 get_stream_writer()
发成 LangGraph custom 事件，由外层 optimize_graph 转发成 SSE 推到前端。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_diagnose.md").read_text(encoding="utf-8")


def build_agent(llm):
    return create_agent(model=llm, tools=[])


async def run(llm, markdown: str, jd: str, question: str, session_id: str | None = None) -> str:
    """跑诊断 agent：发 agent_start → 逐 token 发 delta(diagnose) → agent_end，返回整段诊断。"""
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "diagnose", "label": "诊断 agent"})
    agent = build_agent(llm)
    jd_text = f"\n\n职位描述（JD）：\n{jd}" if (jd or "").strip() else ""
    message = (
        f"简历内容（Markdown，行首 [s:章节 r:窗口 c:内容 i:子项] 是位置编号，请忽略）：\n{markdown}\n"
        f"{jd_text}\n"
        f"\n用户的修改要求：\n{question}"
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
        # 推理模型把思考放 reasoning_content、答案放 content；两者分开打 kind 发给前端，
        # 前端据此分成「思考过程」和「回答」两块（每个 agent 都可能两者都有）。
        msg = chunk[0]
        kwargs = getattr(msg, "additional_kwargs", {}) or {}
        thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
        content = getattr(msg, "content", "") or ""
        if thinking:
            parts.append(thinking)
            writer({"type": "delta", "stage": "diagnose", "text": thinking, "kind": "thinking"})
        if content:
            parts.append(content)
            writer({"type": "delta", "stage": "diagnose", "text": content, "kind": "answer"})
    diagnosis = "".join(parts).strip()
    writer({"type": "agent_end", "agent": "diagnose", "label": "诊断 agent"})
    logger.info("diagnose-agent 输出 %d 字", len(diagnosis))
    return diagnosis
