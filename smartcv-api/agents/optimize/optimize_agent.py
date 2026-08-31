"""优化 agent：按诊断结论反复调用 patch_content 工具，就地替换简历文字。

跑完直接读 store.resume 就是改好的整份简历 JSON，结构/样式/图片不被破坏。

所有事件（agent_start / 逐 token delta / 工具 tool_call·tool_result / agent_end）
都经 get_stream_writer() 发成 LangGraph custom 事件，由外层图转发成 SSE。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer

from agents.utils.skillmiddleware import SkillMiddleware
from agents.optimize.tools import OptimizeStore, make_patch_tools

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_optimize.md").read_text(encoding="utf-8")


async def run(
    llm,
    store: OptimizeStore,
    markdown: str,
    jd: str,
    diagnosis: str,
    question: str,
    session_id: str | None = None,
) -> str:
    """跑优化 agent（工具会就地改 store.resume）。

    返回 agent 的收尾语（一般为空）；真实结果在 store.resume 里。
    """
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "optimize", "label": "优化 agent"})
    agent = create_agent(
        model=llm,
        middleware=[SkillMiddleware(["optimize"])],
        tools=make_patch_tools(store),
    )
    jd_text = f"\n\n职位描述（JD，作参考）：\n{jd}" if (jd or "").strip() else ""
    message = (
        f"当前简历（带位置编号）：\n{markdown}\n"
        f"{jd_text}\n"
        f"\n诊断结果：\n{diagnosis}\n"
        f"\n用户的修改要求：\n{question}\n\n"
        f"请按诊断逐条修改。"
    )
    # 用 astream 驱动（工具调用也走事件循环）：messages 模式逐 token 流式发
    # 思考过程，custom 模式把工具的 tool_call/tool_result 事件转发出去；
    # 改动都在 patch_content 里完成，跑完直接读 store.resume。
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
            writer({"type": "delta", "stage": "optimize", "text": thinking, "kind": "thinking"})
        if content:
            writer({"type": "delta", "stage": "optimize", "text": content, "kind": "answer"})
    writer({"type": "agent_end", "agent": "optimize", "label": "优化 agent"})
    logger.info("optimize-agent 完成 %d 处修改", len(store.patches))
    return ""
