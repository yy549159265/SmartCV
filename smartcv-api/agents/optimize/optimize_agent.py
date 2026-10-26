"""优化 agent：先逐条审查诊断（review_diagnosis），再对判为 change 的诊断执行替换。

patch_content 只收诊断序号，改哪段文字由诊断决定；因此实际改动严格对应被批准的诊断，
不会出现「诊断说 A、优化改 B」的错位。跑完直接读 store.resume 就是改好的整份简历 JSON。

所有事件（agent_start / 逐 token delta / 工具 tool_call·tool_result / agent_end）
都经 get_stream_writer() 发成 LangGraph custom 事件，由外层图转发成 SSE。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer

from agents.utils.skillmiddleware import SkillMiddleware
from agents.optimize.utils.diagnosis import format_diagnosis
from agents.optimize.utils.tools import OptimizeStore, make_patch_tools

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_optimize.md").read_text(encoding="utf-8")


async def run(
    llm,
    store: OptimizeStore,
    markdown: str,
    jd: str,
    diagnosis: list[dict],
    question: str,
    session_id: str | None = None,
) -> str:
    """跑优化 agent（工具会就地改 store.resume）。

    返回 agent 的收尾语（一般为空）；真实结果在 store.resume 里。
    """
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "optimize", "label": "优化 agent"})

    # 诊断项登记到 store：审查状态、坐标、原文核对都以这份只读副本为准
    store.set_diagnoses(diagnosis)

    agent = create_agent(
        model=llm,
        middleware=[SkillMiddleware(["coordinate", "optimize-review"])],
        tools=make_patch_tools(store),
    )
    jd_block = f"<JD>\n{jd}\n</JD>\n\n" if (jd or "").strip() else ""
    # 优化 agent 用 0 起的「诊断 N」编号，和 review_diagnosis / patch_content 的 index 对齐
    diagnosis_text = format_diagnosis(diagnosis, include_coords=True, zero_based=True)
    # 输入用 <> 标签分隔，和诊断 agent 的输入格式保持一致，避免模型把几段内容混读
    message = (
        f"<简历>\n{markdown}\n</简历>\n\n"
        f"{jd_block}"
        f"<诊断>\n{diagnosis_text}\n</诊断>\n\n"
        f"<修改要求>\n{question}\n</修改要求>\n\n"
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
