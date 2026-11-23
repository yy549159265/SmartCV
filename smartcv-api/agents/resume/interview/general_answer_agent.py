"""通用示范答案 / 内容编辑 Agent：按传入的实体类选择提示词片段与输出模型。

三类任务共用同一套入口：

  - `ReferenceAnswer`     主问题示范答案（`general/answer.md`）
  - `FollowUpAnswerSet`   追问示范答案（`general/follow_up_answers.md`）
  - `FollowUpDraft`       按用户方向新增一条追问（`general/follow_up_add.md`）
  - `SampleAnswer`        按本轮改进建议生成的简短示例回答（`general/sample_answer.md`）
  - `ContentEditOutput`   通用内容编辑，用于证据锚点（`general/anchor.md`）与追问（`general/follow_up.md`）

`prompts/general/base.md` 是通用模板，`{{role}}` / `{{input}}` / `{{output}}` /
`{{constraints}}` 由各任务的提示词片段填充，`{{schema}}` 由传入实体类的
`model_json_schema(by_alias=True)` 自动生成，保证提示词与结构化输出始终一致。
新增任务只需注册一个实体类 + 一个片段文件，不改调用链。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from pydantic import BaseModel

from agents.resume.interview.schemas import (
    Anchor,
    AnswerRequest,
    ContentEditOutput,
    ContentEditRequest,
    ContentEditResult,
    FollowUp,
    FollowUpAddRequest,
    FollowUpAddResult,
    FollowUpAnswer,
    FollowUpAnswerSet,
    FollowUpAnswersRequest,
    FollowUpDraft,
    QuestionCard,
    ReferenceAnswer,
    ResumeProfile,
    SampleAnswer,
    SampleAnswerRequest,
)
from agents.resume.interview.tools.pack import anchor_payload, profile_payload
from agents.resume.interview.tools.text import unsupported_numbers
from agents.resume.interview.utils.prompts import load_prompt
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
)
from agents.utils.checkpointer import get_checkpointer
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_BASE_PROMPT = load_prompt("general", "base.md")
_SECTION_RE = re.compile(r"^##\s+(角色|输入|输出|约束)\s*$", re.MULTILINE)
_SECTION_KEYS = {"角色": "role", "输入": "input", "输出": "output", "约束": "constraints"}
_PLACEHOLDER_RE = re.compile(r"\{\{(role|input|output|schema|constraints)\}\}")
_SCENE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# 编辑对象 -> 提示词片段；新增编辑对象时加一个场景片段即可。
_EDIT_SCENES = {"anchor": "anchor.md", "follow_up": "follow_up.md"}


class GeneralAgentError(RuntimeError):
    """通用 Agent 没有返回可用结果；路由层转 502。"""


@dataclass(frozen=True)
class _AgentSpec:
    """一个输出实体类对应的提示词片段、调用参数与结果归一化。"""

    prompt: str | Callable[[Any], str]
    temperature: float
    stage: str
    payload: Callable[[Any], str]
    finalize: Callable[[Any, Any], Any]
    empty_message: str
    invalid_message: str
    use_agent: bool = True
    thread_prefix: str = "interview-general"


# --------------------------------------------------------------------------- 提示词


@lru_cache(maxsize=32)
def _prompt_fragments(name: str) -> dict[str, str]:
    """读取片段文件的四个固定分区。

    分区缺失直接报错，避免静默跑错提示词。
    """
    text = load_prompt("general", name)
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        raise ValueError(f"提示词片段缺少分区标题：{name}")

    parts: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = _SECTION_KEYS[match.group(1)]
        parts[key] = text[match.end() : end].strip()

    missing = [key for key in _SECTION_KEYS.values() if not parts.get(key)]
    if missing:
        raise ValueError(f"提示词片段缺少分区：{name} -> {', '.join(missing)}")
    return parts


@lru_cache(maxsize=32)
def _system_prompt(model: type[BaseModel], prompt_file: str) -> str:
    fragments = _prompt_fragments(prompt_file)
    schema = json.dumps(
        model.model_json_schema(by_alias=True), ensure_ascii=False, indent=2
    )
    rendered = _BASE_PROMPT
    for key, value in {
        "role": fragments["role"],
        "input": fragments["input"],
        "output": fragments["output"],
        "schema": schema,
        "constraints": fragments["constraints"],
    }.items():
        rendered = rendered.replace("{{" + key + "}}", value)

    leftover = _PLACEHOLDER_RE.findall(rendered)
    if leftover:
        raise ValueError(
            f"提示词模板存在未替换的占位符：{prompt_file} -> {', '.join(leftover)}"
        )
    return rendered


def _edit_prompt(req: ContentEditRequest) -> str:
    scene = (req.scene or "").strip()
    if scene == "base" or not _SCENE_RE.fullmatch(scene):
        raise ValueError("编辑场景不合法")
    prompt_file = _EDIT_SCENES.get(scene)
    if prompt_file is None:
        raise ValueError(f"不支持的编辑场景：{scene}")
    return prompt_file


# --------------------------------------------------------------------------- 输入载荷


def _relevant_anchors(card: QuestionCard, anchors: list[Anchor]) -> list[dict]:
    """优先给与当前卡直接相关的锚点，避免把整份简历的锚点都塞进提示词。"""
    if card.anchor_id:
        matched = [anchor for anchor in anchors if anchor.id == card.anchor_id]
        if matched:
            return [anchor_payload(anchor) for anchor in matched]
    if card.project_id:
        matched = [anchor for anchor in anchors if anchor.project_id == card.project_id]
        if matched:
            return [anchor_payload(anchor) for anchor in matched]
    return [anchor_payload(anchor) for anchor in anchors]


def _answer_payload(req: AnswerRequest) -> str:
    card = req.card
    payload = {
        "profile": profile_payload(req.profile),
        "anchors": _relevant_anchors(card, req.anchors),
        "card": {
            "mainQuestion": card.main_question,
            "followUps": [
                {
                    "level": follow.level,
                    "question": follow.question,
                    "intent": follow.intent,
                }
                for follow in card.follow_ups
            ],
            "intent": card.intent,
            "dimension": card.dimension,
            "evidenceQuote": card.evidence_quote,
            "coverage": card.coverage,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _target_follow_ups(
    req: FollowUpAnswersRequest,
) -> tuple[list[str], dict[str, Any]]:
    valid = {follow.id: follow for follow in req.card.follow_ups if follow.id}
    targets = (
        [item for item in req.follow_up_ids if item in valid]
        if req.follow_up_ids
        else list(valid)
    )
    if not targets:
        raise GeneralAgentError("这张卡片没有可补答案的追问")
    return targets, valid


def _follow_up_payload(req: FollowUpAnswersRequest) -> str:
    """只把目标追问发给模型，避免它顺手重写整条追问链。"""
    targets, _ = _target_follow_ups(req)

    reference = req.card.reference_answer
    main_answer = (
        {
            "thinking": reference.thinking,
            "answer": reference.answer,
            "keyPoints": reference.key_points,
            "missingInfo": reference.missing_info,
            "assumptions": reference.assumptions,
        }
        if reference.answer.strip()
        else {}
    )

    payload = {
        "profile": profile_payload(req.profile),
        "anchors": _relevant_anchors(req.card, req.anchors),
        "card": {
            "mainQuestion": req.card.main_question,
            "intent": req.card.intent,
            "dimension": req.card.dimension,
            "evidenceQuote": req.card.evidence_quote,
            "referenceAnswer": main_answer,
            "followUps": [
                {
                    "id": follow.id,
                    "level": follow.level,
                    "question": follow.question,
                    "intent": follow.intent,
                }
                for follow in req.card.follow_ups
                if follow.id
            ],
        },
        "targetFollowUpIds": targets,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _follow_up_add_payload(req: FollowUpAddRequest) -> str:
    """只给当前卡相关的画像与锚点，以及完整追问链，避免新问题与已有问题重复。"""
    card = req.card
    payload = {
        "instruction": req.instruction.strip(),
        "profile": profile_payload(req.profile),
        "anchors": _relevant_anchors(card, req.anchors),
        "card": {
            "mainQuestion": card.main_question,
            "intent": card.intent,
            "dimension": card.dimension,
            "evidenceQuote": card.evidence_quote,
            "followUps": [
                {
                    "level": follow.level,
                    "question": follow.question,
                    "intent": follow.intent,
                }
                for follow in card.follow_ups
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _sample_answer_payload(req: SampleAnswerRequest) -> str:
    """只给当前卡相关的画像与锚点，避免为了短答案塞进整份简历。"""
    card = req.card
    payload = {
        "profile": profile_payload(req.profile),
        "anchors": _relevant_anchors(card, req.anchors),
        "card": {
            "mainQuestion": card.main_question,
            "intent": card.intent,
            "dimension": card.dimension,
            "evidenceQuote": card.evidence_quote,
            "coverage": card.coverage,
            "referenceAnswer": card.reference_answer.answer.strip(),
        },
        "question": req.question,
        "level": req.level or "",
        "answer": req.answer,
        "feedback": req.feedback,
        "leaks": req.leaks,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _edit_payload(req: ContentEditRequest) -> str:
    payload = {
        "scene": req.scene,
        "instruction": req.instruction.strip(),
        "content": req.content,
        "context": req.context,
        "lockedFields": req.locked_fields,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- 结果归一化


def _profile_text(profile: ResumeProfile, anchors: list[Anchor]) -> str:
    payload = {
        "profile": profile_payload(profile),
        "anchors": [anchor_payload(anchor) for anchor in anchors],
    }
    return json.dumps(payload, ensure_ascii=False)


def _clean_items(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _clean_answer(answer: ReferenceAnswer, profile_text: str) -> None:
    """清理答案字段，并标记简历里找不到依据的数字。

    参考答案不再区分来源或状态：`missingInfo` 说明简历缺什么，
    `assumptions` 说明示范答案补了什么，`answer` 必须非空。
    """
    answer.thinking = (answer.thinking or "").strip()
    answer.answer = (answer.answer or "").strip()
    answer.key_points = _clean_items(answer.key_points)
    answer.missing_info = _clean_items(answer.missing_info)
    answer.assumptions = _clean_items(answer.assumptions)
    if not answer.answer:
        raise GeneralAgentError("AI 没有返回答案正文，请重试")

    # 答案里出现画像中没有的数字时，把缺口与假设写清楚。
    unsupported = unsupported_numbers(
        "\n".join([answer.answer, *answer.key_points]), profile_text
    )

    if unsupported:
        answer.missing_info = _clean_items(
            [
                f"简历里找不到这些数字的依据：{'、'.join(unsupported)}",
                *answer.missing_info,
            ]
        )
        answer.assumptions = _clean_items(
            [
                "答案中的这些数字为示范假设：" + "、".join(unsupported),
                *answer.assumptions,
            ]
        )
    if answer.missing_info and not answer.assumptions:
        answer.assumptions = ["答案中的具体细节为示范假设，需要按真实经历替换"]


def _finalize_answer(answer: ReferenceAnswer, req: AnswerRequest) -> ReferenceAnswer:
    _clean_answer(answer, _profile_text(req.profile, req.anchors))
    logger.info("interview answer generated: card=%s", req.card.id or "-")
    return answer


def _finalize_follow_ups(
    result: FollowUpAnswerSet, req: FollowUpAnswersRequest
) -> FollowUpAnswerSet:
    """按 `followUp.id` 合并答案；只接受本次要求的 id，且去重。"""
    targets, valid = _target_follow_ups(req)
    allowed = set(targets)
    profile_text = _profile_text(req.profile, req.anchors)

    answers: dict[str, FollowUpAnswer] = {}
    for item in result.answers:
        if item.follow_up_id not in allowed or item.follow_up_id in answers:
            continue
        try:
            _clean_answer(item.answer, profile_text)
        except GeneralAgentError:
            continue
        answers[item.follow_up_id] = item

    if not answers:
        raise GeneralAgentError("AI 没有返回可用的追问答案，请重试")

    logger.info(
        "interview follow-up answers generated: card=%s requested=%d generated=%d",
        req.card.id or "-",
        len(valid),
        len(answers),
    )
    return FollowUpAnswerSet(answers=list(answers.values()))


def _finalize_follow_up_add(
    output: FollowUpDraft, req: FollowUpAddRequest
) -> FollowUpAddResult:
    """补 id、去空白并挡住与现有追问重复的结果。"""
    question = (output.question or "").strip()
    if not question:
        raise GeneralAgentError("AI 没有返回可用的追问，请重试")

    def compact(text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    existing = {compact(follow.question) for follow in req.card.follow_ups}
    if compact(question) in existing:
        raise GeneralAgentError("AI 返回的追问与现有追问重复，请换个方向重试")

    prefix = req.card.id[1:] if req.card.id.startswith("c") else req.card.id or "0"
    follow_up = FollowUp(
        id=f"f{prefix}_{uuid.uuid4().hex[:6]}",
        level=output.level,
        question=question,
        intent=(output.intent or "").strip(),
    )
    summary = (output.summary or "").strip()
    logger.info(
        "interview follow-up added: card=%s level=%s",
        req.card.id or "-",
        follow_up.level,
    )
    return FollowUpAddResult(follow_up=follow_up, summary=summary)


def _finalize_sample_answer(
    output: SampleAnswer, req: SampleAnswerRequest
) -> SampleAnswer:
    text = (output.answer or "").strip()
    if not text:
        raise GeneralAgentError("AI 没有返回示范回答，请重试")
    output.answer = text
    logger.info("interview sample answer generated: card=%s", req.card.id or "-")
    return output


def _merge_content(
    original: dict, edited: object, locked_fields: list[str]
) -> dict:
    """只接受原对象已有的顶层键；锁定字段始终以原值为准。

    这样无论场景提示词怎么写，调用方拿到的实体结构都不会被模型改形，
    id / 原文引用这类证据字段也不会被悄悄替换。
    """
    if not isinstance(edited, dict):
        raise GeneralAgentError("AI 没有返回可用的修改结果，请重试")

    merged = {
        key: edited[key] if key in edited else value
        for key, value in original.items()
    }
    for key in locked_fields:
        if key in original:
            merged[key] = original[key]
    return merged


def _finalize_edit(
    output: ContentEditOutput, req: ContentEditRequest
) -> ContentEditResult:
    content = _merge_content(req.content, output.content, req.locked_fields)
    summary = output.summary.strip()
    logger.info(
        "content edit: scene=%s locked=%d changed=%s",
        req.scene,
        len(req.locked_fields),
        bool(summary),
    )
    return ContentEditResult(content=content, summary=summary)


# --------------------------------------------------------------------------- 调用


def _build_agent(llm, model: type[BaseModel]):
    return create_agent(
        model=llm,
        tools=[],
        response_format=model,
        middleware=[DropInvalidToolCallsMiddleware(scope="模拟面试")],
        checkpointer=get_checkpointer("interview"),
    )


async def _run_agent(
    provider: ProviderConfig,
    model: type[BaseModel],
    system_prompt: str,
    payload: str,
    spec: _AgentSpec,
) -> BaseModel:
    llm = choose_llm(provider, temperature=spec.temperature, timeout=120, max_retries=1)
    agent = _build_agent(llm, model)
    structured = await run_structured(
        agent,
        system_prompt,
        payload,
        {
            "configurable": {
                "thread_id": f"{spec.thread_prefix}:{uuid.uuid4().hex}"
            }
        },
        stage=spec.stage,
        scope="模拟面试",
    )
    if not structured:
        raise GeneralAgentError(spec.empty_message)

    try:
        return model.model_validate(structured)
    except Exception as exc:  # noqa: BLE001 - 路由统一转 502
        raise GeneralAgentError(
            f"{spec.invalid_message}{str(exc)[:200]}"
        ) from exc


async def _run_plain(
    provider: ProviderConfig,
    model: type[BaseModel],
    system_prompt: str,
    payload: str,
    spec: _AgentSpec,
) -> BaseModel:
    """无工具结构化调用；校验失败时把原因交回模型重试一次。"""
    llm = choose_llm(provider, temperature=spec.temperature, timeout=120, max_retries=1)
    # 默认的 json_schema 会发 response_format=json_schema，DeepSeek 等
    # OpenAI 兼容供应商会直接 400；统一走 json_object，Schema 由系统提示词约束。
    runnable = llm.with_structured_output(model, method="json_mode")

    output: BaseModel | None = None
    last_error = ""
    for attempt in (1, 2):
        message = payload
        if attempt == 2:
            reason = last_error or "字段不完整"
            message = (
                f"{payload}\n\n上一次输出无法通过校验：{reason}。"
                "请严格按系统提示中的 JSON Schema 重新输出。"
            )
        try:
            structured = await run_structured(
                runnable,
                system_prompt,
                message,
                stage=spec.stage,
                scope="模拟面试",
            )
        except Exception as exc:  # noqa: BLE001 - 第二次仍失败再交给路由
            last_error = str(exc)[:300]
            if attempt == 2:
                raise GeneralAgentError(
                    f"{spec.invalid_message}{last_error[:200]}"
                ) from exc
            continue

        if not structured:
            last_error = "没有返回结构化结果"
            continue
        try:
            output = model.model_validate(structured)
        except Exception as exc:  # noqa: BLE001 - 校验原因回传给模型重试
            last_error = str(exc)[:300]
            continue
        break

    if output is None:
        raise GeneralAgentError(spec.empty_message)
    return output


_SPECS: dict[type[BaseModel], _AgentSpec] = {
    ReferenceAnswer: _AgentSpec(
        prompt="answer.md",
        temperature=0.6,
        stage="interview-answer",
        payload=_answer_payload,
        finalize=_finalize_answer,
        empty_message="AI 没有返回可用答案，请重试",
        invalid_message="AI 答案格式不正确：",
        thread_prefix="interview-answer",
    ),
    FollowUpAnswerSet: _AgentSpec(
        prompt="follow_up_answers.md",
        temperature=0.6,
        stage="interview-follow-ups",
        payload=_follow_up_payload,
        finalize=_finalize_follow_ups,
        empty_message="AI 没有返回追问答案，请重试",
        invalid_message="AI 追问答案格式不正确：",
        thread_prefix="interview-follow-ups",
    ),
    FollowUpDraft: _AgentSpec(
        prompt="follow_up_add.md",
        temperature=0.5,
        stage="interview-follow-up-add",
        payload=_follow_up_add_payload,
        finalize=_finalize_follow_up_add,
        empty_message="AI 没有返回可用的追问，请重试",
        invalid_message="AI 追问格式不正确：",
        use_agent=False,
        thread_prefix="interview-follow-up-add",
    ),
    SampleAnswer: _AgentSpec(
        prompt="sample_answer.md",
        temperature=0.5,
        stage="interview-sample-answer",
        payload=_sample_answer_payload,
        finalize=_finalize_sample_answer,
        empty_message="AI 没有返回示范回答，请重试",
        invalid_message="AI 示范回答格式不正确：",
        use_agent=False,
        thread_prefix="interview-sample-answer",
    ),
    ContentEditOutput: _AgentSpec(
        prompt=_edit_prompt,
        temperature=0.3,
        stage="content-edit",
        payload=_edit_payload,
        finalize=_finalize_edit,
        empty_message="AI 没有返回可用的修改结果，请重试",
        invalid_message="内容修改失败：",
        use_agent=False,
        thread_prefix="interview-edit",
    ),
}


async def run(
    provider: ProviderConfig, req: Any, model: type[BaseModel]
) -> Any:
    """按传入的实体类选提示词片段与结构化输出模型，执行一次调用。

    `model` 同时决定三件事：读哪份片段、给模型看哪份 JSON Schema、
    以及校验返回值时用哪个实体类，三者始终对齐。
    """
    spec = _SPECS.get(model)
    if spec is None:
        raise ValueError(f"不支持的输出实体：{getattr(model, '__name__', model)}")

    prompt_file = spec.prompt(req) if callable(spec.prompt) else spec.prompt
    system_prompt = _system_prompt(model, prompt_file)
    payload = spec.payload(req)

    if spec.use_agent:
        output = await _run_agent(provider, model, system_prompt, payload, spec)
    else:
        output = await _run_plain(provider, model, system_prompt, payload, spec)
    return spec.finalize(output, req)
