"""简历分析 Agent：带坐标简历 → ResumeProfile + Anchor[]。

输入使用 `resume_to_marked_text`，模型只输出引用坐标（refs），不复制原文；
`tools.pack.assign_profile` 按坐标取回文字、逐字核对，核不上的锚点直接丢弃，
避免后续问题引用不存在的经历。
"""

import logging
import uuid

from langchain.agents import create_agent

from agents.resume.interview.schemas import Anchor, ProfileExtraction, ResumeProfile
from agents.resume.interview.tools.pack import assign_profile
from agents.resume.interview.utils.prompts import load_prompt
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
)
from agents.utils.checkpointer import get_checkpointer
from agents.utils.choose_llm import choose_llm
from agents.utils.resume import resume_to_marked_text, resume_to_plain_text
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = load_prompt("profile", "resume.md")


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=ProfileExtraction,
        middleware=[DropInvalidToolCallsMiddleware(scope="模拟面试")],
        checkpointer=get_checkpointer("interview"),
    )


async def run(
    provider: ProviderConfig,
    resume: list[dict],
    *,
    session_id: str | None = None,
) -> tuple[ResumeProfile, list[Anchor], list[str]]:
    """抽取画像；返回 (profile, anchors, warnings)。"""
    plain_text = resume_to_plain_text(resume)
    if not plain_text.strip():
        raise ValueError("简历是空的，请先填写简历内容")
    marked_text = resume_to_marked_text(resume)

    llm = choose_llm(provider, temperature=0.2, timeout=120, max_retries=1)
    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"interview-profile:{uuid.uuid4().hex}"}}

    structured: dict | None = None
    last_error = ""
    for attempt in (1, 2):
        message = marked_text
        if attempt == 2:
            message = (
                f"{marked_text}\n\n上一次输出未通过 schema 校验：{last_error or '字段不完整'}。"
                "请严格按结构化 schema 重新输出；引用只写输入行首的 [s:.. r:.. c:.. i:..] "
                "坐标到 refs，不要复制原文，也不要自创坐标。"
            )
        structured = await run_structured(
            agent,
            _SYSTEM_PROMPT,
            message,
            config,
            stage="interview-profile",
            scope="模拟面试",
        )
        if not structured:
            last_error = "没有返回结构化结果"
            continue
        try:
            extraction = ProfileExtraction.model_validate(structured)
        except Exception as exc:  # noqa: BLE001 - 需要把校验原因回传给模型
            last_error = str(exc)[:400]
            continue
        profile, anchors, warnings = assign_profile(extraction, resume, plain_text)
        logger.info(
            "interview profile: session=%s projects=%d tech=%d anchors=%d",
            session_id or "-",
            len(profile.projects),
            len(profile.tech_stacks),
            len(anchors),
        )
        return profile, anchors, warnings

    raise RuntimeError("简历分析失败：模型未返回有效画像，请重试")
