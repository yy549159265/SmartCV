"""简历解析 agent：合并后的单 Agent 流程。

一个 agent 干两件事：
1. 加载 md2md 技能，把原始解析文本整理成「# 标题 + <start> 标记行」的标准标记文本；
2. 调用唯一的 generate_resume(markdown) 工具，把标记文本直接构造为骨架 JSON。

步骤状态写进 PDF2ResumeStore，供 /api/resume/parse/status 轮询。
"""

import logging
from pathlib import Path

from langchain.agents import create_agent

from agents.md2json.tools import make_section_tools
from agents.md2json.schemas.store import PDF2ResumeStore, Step
from agents.utils.skillmiddleware import SkillMiddleware
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_md2json.md").read_text(encoding="utf-8")



def run_resume_agent(
    provider: ProviderConfig,
    store: PDF2ResumeStore,
    markdown: str,
    session_id: str | None = None,
) -> PDF2ResumeStore:
    """合并后的单 Agent：先整理标记文本，再调用工具构造 JSON。

    结果写在 store.content（Resume | None）上，步骤状态同步进 store.steps。
    """
    llm = choose_llm(provider)

    store.start_step(Step.ORGANIZE)
    agent = create_agent(
        model=llm,
        middleware=[SkillMiddleware(["md2md"])],
        tools=[make_section_tools(store)],
    )
    agent.invoke(
        {
            "messages": [
                {"type": "system", "content": _SYSTEM_PROMPT},
                {"type": "human", "content": markdown},
            ]
        },
        # session_id 通过 configurable 传给 agent，同一会话的多次调用才能串成一条会话；
        # recursion_limit 放宽：整理 + 工具构造一轮 = 模型 + 工具两个节点，加技能加载与重试
        config={
            "recursion_limit": 50,
            "configurable": {"session_id": session_id},
        },
    )

    # 模型没调用工具生成结构（或工具校验失败后没重试成功）时兜底标失败
    if store.content is None and store.error is None:
        store.fail_step(Step.CONVERT, "未生成简历结构")

    logging.info("resume-agent 输出 %d 个章节", len(store.content.sections) if store.content else 0)
    return store
