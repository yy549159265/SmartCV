"""教学导师 Agent：逐 token 讲解当前题，支持连续追问。

不把参考答案整段回贴；参考答案只作为讲解依据。失败只抛异常，
由 graph 报错并保持 phase=teaching，用户可重试或返回。
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from agents.resume.interview.schemas import Anchor, QuestionCard, ResumeProfile
from agents.resume.interview.tools.pack import anchor_payload, profile_payload
from agents.resume.interview.utils.prompts import load_prompt
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

_TEACHER_PROMPT = load_prompt("teaching", "teacher.md")
_MAX_HISTORY = 6


class TeacherError(RuntimeError):
    """讲解失败；保留教学阶段，允许重试。"""


def _context_payload(
    state: dict,
    card: QuestionCard,
    question: str,
    level: str,
    anchor: Anchor | None,
    history: list[dict],
) -> str:
    payload = {
        # 当前实际被问到的问题可能是追问，不等于 card.main_question；
        # 讲解必须围绕它展开，主问题只作为上下文。
        "question": question,
        "level": level,
        "isDynamic": bool(state.get("current_is_dynamic")),
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
            "leakSignals": card.leak_signals,
        },
        "anchor": anchor_payload(anchor, by_alias=True) if anchor else {},
        "profile": (
            profile_payload(ResumeProfile.model_validate(state.get("profile") or {}))
            if state.get("profile")
            else {}
        ),
        "history": history[-_MAX_HISTORY:],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _chunk_text(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return ""


async def stream_reply(
    provider: ProviderConfig,
    state: dict,
    card: QuestionCard,
    anchor: Anchor | None,
    history: list[dict],
    message: str,
    emit,
    *,
    question: str = "",
    level: str = "",
) -> str:
    """流式讲解当前问题，逐 token 发 delta；返回完整回复。

    `question` 是检查点里的 current_question（可能是追问），未传时退回主问题。
    """
    current_question = question or state.get("current_question") or card.main_question
    current_level = level or str(state.get("current_level") or "")
    llm = choose_llm(provider, temperature=0.6, timeout=120, max_retries=1)
    messages = [
        SystemMessage(content=_TEACHER_PROMPT),
        HumanMessage(
            content=(
                f"{_context_payload(state, card, current_question, current_level, anchor, history)}\n\n"
                f"<user>\n{message}\n</user>"
            )
        ),
    ]
    parts: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            text = _chunk_text(chunk)
            if not text:
                continue
            parts.append(text)
            await emit({"type": "delta", "stage": "teaching", "text": text})
    except Exception as exc:  # noqa: BLE001 - 交给图表成 error 事件
        raise TeacherError(str(exc)[:300]) from exc

    reply = "".join(parts).strip()
    if not reply:
        raise TeacherError("导师没有返回内容，请重试")
    return reply
