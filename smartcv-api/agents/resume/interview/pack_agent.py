"""问题生成 Agent：按分组并发生成问题卡，合并后只做数据加工。

分组规则见 `tools.pack.group_specs`：
  - 项目面试：所选项目一个组；
  - 综合面试：动机 / 规划 / 薪资 / 稳定性 / 真实性五个主题组；
  - 排查面试：故障排查 / 性能优化 / 方案设计三个题型组。

对话与清单共用同一份题包，只在第 4 步决定怎么消费；分组规则与题量都不受
方式影响。每种场景各加载一份场景提示词，项目面试再追加考察方向提示词
（未选方向时为均衡模式 balanced），并用维度占比做一次软提示。排查面试在
同一份场景提示词里按 `task.theme` 区分故障排查、性能优化与方案设计。

每组一次结构化调用，组间最多并发 3 个。追问链与露馅信号的硬性要求写在
`QuestionCard` 字段约束里，由结构化输出直接校验，不再额外做卡片校验。
出题阶段只产问题，不产参考答案；`prepare_cards` 会强制清空答案字段。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from langchain.agents import create_agent

from agents.resume.interview.schemas import (
    Anchor,
    PackGroupResult,
    PackRequest,
    QuestionCard,
    ResumeProfile,
)
from agents.resume.interview.tools.pack import (
    assign_ids,
    dedupe_cards,
    focus_gap,
    group_specs,
    prepare_cards,
    primary_techs,
    profile_payload,
)
from agents.resume.interview.utils.prompts import load_prompt
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
)
from agents.utils.checkpointer import get_checkpointer
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_CARDS_PROMPT = load_prompt("pack", "cards.md")
# 场景提示词：项目面试与综合面试各一份，按 `task.scene` 加载。
_SCENE_PROMPTS = {
    "project": load_prompt("pack", "scene", "project.md"),
    "comprehensive": load_prompt("pack", "scene", "comprehensive.md"),
    "scenario": load_prompt("pack", "scene", "scenario.md"),
}
# 考察方向只属于项目面试；balanced 是未选择方向时的默认值。
_FOCUS_PROMPTS = {
    "balanced": load_prompt("pack", "focus", "balanced.md"),
    "business": load_prompt("pack", "focus", "business.md"),
    "tech": load_prompt("pack", "focus", "tech.md"),
    "architecture": load_prompt("pack", "focus", "architecture.md"),
    "review": load_prompt("pack", "focus", "review.md"),
}
_MAX_CONCURRENCY = 3


class PackError(RuntimeError):
    """没有可生成的分组，或所有分组都没有返回可用问题卡；路由层转 502。"""

    def __init__(self, message: str, public_message: str = "") -> None:
        super().__init__(message)
        self.public_message = public_message or message


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        response_format=PackGroupResult,
        middleware=[DropInvalidToolCallsMiddleware(scope="模拟面试")],
        checkpointer=get_checkpointer("interview"),
    )


def _corpus(profile: ResumeProfile, anchors: list[Anchor]) -> str:
    """证据语料：只来自用户确认后的画像与锚点，不碰原始简历。"""
    parts: list[str] = [profile.direction, profile.intro]
    for item in profile.tech_stacks:
        parts.extend([item.name, item.quote])
    for project in profile.projects:
        parts.extend(
            [
                project.name,
                project.intro,
                project.role,
                *project.tech_stack,
                *project.highlights,
            ]
        )
    parts.extend(anchor.quote for anchor in anchors)
    return "\n".join(part for part in parts if part)


def _scene_prompt(req: PackRequest) -> str:
    """按场景加载提示词；综合面试与排查面试都不追加考察方向。"""
    return _SCENE_PROMPTS[req.scene]


def _system_prompt(spec: dict, req: PackRequest) -> str:
    parts = [_CARDS_PROMPT, _scene_prompt(req)]
    if spec["kind"] == "project":
        parts.append(_FOCUS_PROMPTS[req.focus])
    return "\n\n".join(parts)


def _payload(spec: dict, req: PackRequest, profile: ResumeProfile) -> str:
    task = {
        "groupKey": spec["key"],
        "kind": spec["kind"],
        "label": spec["label"],
        "scene": req.scene,
        "focus": req.focus,
        "follow_depth": req.follow_depth or "none",
        "theme": spec["theme"],
        "project": spec["project"],
        "tech": spec["tech"],
    }
    if req.scene == "scenario":
        task["primaryTechs"] = primary_techs(profile)
    payload = {
        "profile": profile_payload(profile),
        "anchors": spec["anchors"],
        "task": task,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def _group_cards(
    agent,
    spec: dict,
    req: PackRequest,
    profile: ResumeProfile,
    anchors: list[Anchor],
    corpus: str,
    semaphore: asyncio.Semaphore,
) -> tuple[list[QuestionCard], list[str]]:
    """跑一个分组；追问链与露馅信号由 QuestionCard 的字段约束保证。"""
    warnings: list[str] = []
    config = {
        "configurable": {"thread_id": f"interview-pack:{uuid.uuid4().hex}"}
    }

    async with semaphore:
        structured = await run_structured(
            agent,
            _system_prompt(spec, req),
            _payload(spec, req, profile),
            config,
            stage=f"interview-pack:{spec['kind']}",
            scope="模拟面试",
        )

    if not structured:
        warnings.append(f"「{spec['label']}」未返回结构化结果")
        return [], warnings
    try:
        result = PackGroupResult.model_validate(structured)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"「{spec['label']}」结果校验失败：{str(exc)[:120]}")
        return [], warnings

    cards = prepare_cards(
        result.cards,
        scene=req.scene,
        profile=profile,
        anchors=anchors,
        resume_text=corpus,
    )
    problem = focus_gap(cards, req.focus) if cards else ""
    if problem:
        warnings.append(f"「{spec['label']}」{problem}")
    return cards, warnings


async def generate(
    provider: ProviderConfig, req: PackRequest
) -> tuple[list[QuestionCard], list[str]]:
    profile = req.profile
    anchors = req.anchors
    specs = group_specs(req, profile, anchors)
    if not specs:
        raise PackError("没有可生成问题的分组")

    corpus = _corpus(profile, anchors)
    llm = choose_llm(provider, temperature=0.5, timeout=180, max_retries=1)
    agent = build_agent(llm)
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    warnings: list[str] = []

    results = await asyncio.gather(
        *(
            _group_cards(agent, spec, req, profile, anchors, corpus, semaphore)
            for spec in specs
        ),
        return_exceptions=True,
    )

    all_cards: list[QuestionCard] = []
    for spec, result in zip(specs, results):
        if isinstance(result, Exception):
            logger.exception("问题包分组失败：%s", spec["key"], exc_info=result)
            warnings.append(f"「{spec['label']}」生成失败：{str(result)[:160]}")
            continue
        cards, group_warnings = result
        warnings.extend(group_warnings)
        all_cards.extend(cards)

    if not all_cards:
        raise PackError("问题包生成失败：所有分组都没有返回可用问题卡")

    cards = dedupe_cards(all_cards)
    cards = assign_ids(cards)

    logger.info(
        "interview cards: scene=%s focus=%s follow_depth=%s groups=%d cards=%d warnings=%d",
        req.scene,
        req.focus,
        req.follow_depth or "-",
        len(specs),
        len(cards),
        len(warnings),
    )
    return cards, list(warnings)
