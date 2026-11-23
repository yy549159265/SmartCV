"""面试官 Agent：一轮回答 → 露馅信号 + 反馈 + 下一步候选决策。

一次结构化调用。只带当前卡、对应锚点、当前问题、最近两条记录与进度摘要，
不重复拼入整份问题包和全部历史；追问 / 动态配额由 `utils.policy.resolve_turn`
兜底，这里只负责给候选。
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from agents.resume.interview.schemas import (
    Anchor,
    InterviewerTurn,
    QuestionCard,
)
from agents.resume.interview.tools.pack import anchor_payload
from agents.resume.interview.utils.policy import follow_depth_of
from agents.resume.interview.utils.prompts import load_prompt
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_INTERVIEWER_PROMPT = load_prompt("interview", "interviewer.md")
_DEEP_PROMPT = load_prompt("interview", "deep.md")
_MAX_ANSWER_CHARS = 1600

_DECISION_ALIASES = {
    "follow_up": "follow_up",
    "followup": "follow_up",
    "followUp": "follow_up",
    "next_card": "next_card",
    "next": "next_card",
    "nextCard": "next_card",
    "end": "end",
    "finish": "end",
    "finished": "end",
}
_REASON_ALIASES = {
    "new_anchor": "new_anchor",
    "newAnchor": "new_anchor",
    "contradiction": "contradiction",
    "metric_anomaly": "metric_anomaly",
    "metricAnomaly": "metric_anomaly",
    "shallow": "shallow",
}


class InterviewerError(RuntimeError):
    """评估失败；路由层以 error 事件收尾，检查点保持原状态。"""


def _system_prompt(follow_depth: str) -> str:
    if follow_depth == "deep":
        return f"{_INTERVIEWER_PROMPT}\n\n{_DEEP_PROMPT}"
    return _INTERVIEWER_PROMPT


def _recent(records: list[dict]) -> list[dict]:
    items: list[dict] = []
    for record in records[-2:]:
        items.append(
            {
                "question": record.get("question") or "",
                "answer": (record.get("answer") or "")[:_MAX_ANSWER_CHARS],
                "leaks": record.get("leaks") or [],
                "feedback": record.get("feedback") or "",
                "skipped": bool(record.get("skipped")),
            }
        )
    return items


def _json_payload(text: str) -> dict | None:
    """从模型输出里取出 JSON 对象；兼容 Markdown 代码块与前后说明文字。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _unwrap_payload(payload: dict) -> dict:
    """有些供应商会把结构化结果再包一层 data / result / output。"""
    for key in ("data", "result", "output"):
        nested = payload.get(key)
        if not isinstance(nested, dict):
            continue
        if any(
            item in nested
            for item in ("decision", "offTopic", "off_topic", "leaks", "feedback")
        ):
            return {**payload, **nested}
    return payload


def _normalize_turn_payload(payload: dict) -> dict:
    """把模型常见的扁平 / 别名输出整理成 InterviewerTurn 能接收的结构。"""
    data = _unwrap_payload(dict(payload))

    decision = data.get("decision")
    if decision is not None:
        normalized = _DECISION_ALIASES.get(str(decision).strip())
        if normalized:
            data["decision"] = normalized
        else:
            data.pop("decision", None)

    if "followUpId" in data and "followupId" not in data:
        data["followupId"] = data.pop("followUpId")

    level = str(data.get("dynamicLevel") or data.get("dynamic_level") or "").strip().upper()
    if level in ("L1", "L2", "L3"):
        data["dynamicLevel"] = level
        data["dynamic_level"] = level

    reason = data.get("dynamicReason", data.get("dynamic_reason"))
    if reason is not None:
        normalized = _REASON_ALIASES.get(str(reason).strip())
        if normalized:
            data["dynamicReason"] = normalized
            data["dynamic_reason"] = normalized
        else:
            data.pop("dynamicReason", None)
            data.pop("dynamic_reason", None)

    return data


def _turn_from_payload(payload: dict) -> InterviewerTurn:
    return InterviewerTurn.model_validate(_normalize_turn_payload(payload))


def _coerce_turn(result: object) -> tuple[InterviewerTurn | None, str]:
    """把 with_structured_output(include_raw=True) 的结果转成 InterviewerTurn。"""
    if isinstance(result, InterviewerTurn):
        return result, ""

    if not isinstance(result, dict):
        return None, "模型没有返回结构化结果"

    error = ""
    raw = result.get("raw")
    content = getattr(raw, "content", "")
    if isinstance(content, str):
        payload = _json_payload(content)
        if payload is not None:
            try:
                return _turn_from_payload(payload), ""
            except Exception as exc:  # noqa: BLE001 - 统一转成重试提示
                error = f"原始输出校验失败：{exc}"

    parsed = result.get("parsed")
    if isinstance(parsed, InterviewerTurn):
        return parsed, ""
    if isinstance(parsed, dict):
        try:
            return _turn_from_payload(parsed), ""
        except Exception as exc:  # noqa: BLE001
            error = error or f"解析结果校验失败：{exc}"

    if not any(key in result for key in ("raw", "parsed", "parsing_error")):
        try:
            return _turn_from_payload(result), ""
        except Exception as exc:  # noqa: BLE001
            error = error or f"输出校验失败：{exc}"

    parsing_error = result.get("parsing_error")
    if parsing_error and not error:
        error = f"结构化解析失败：{parsing_error}"
    return None, error or "模型没有返回结构化结果"


def build_payload(
    state: dict,
    card: QuestionCard,
    anchor: Anchor | None,
    question: str,
    level: str,
    answer: str,
) -> dict:
    cards = state.get("cards") or []
    done = set(state.get("done_card_ids") or [])
    remaining_cards = [
        item for item in cards if item.get("id") not in done and item.get("id") != card.id
    ]
    asked = set(state.get("asked_followups") or [])
    used = int((state.get("followup_used") or {}).get(card.id, 0))
    dynamic_count = int(state.get("dynamic_count") or 0)

    return {
        "scene": state.get("scene") or "project",
        "focus": state.get("focus") or "balanced",
        "follow_depth": follow_depth_of(state) or "normal",
        "card": {
            "id": card.id,
            "projectId": card.project_id,
            "dimension": card.dimension,
            "priority": card.priority,
            "mainQuestion": card.main_question,
            "intent": card.intent,
            "evidenceQuote": card.evidence_quote,
            "coverage": card.coverage,
            "leakSignals": card.leak_signals,
            "followUps": [
                {
                    "id": follow.id,
                    "level": follow.level,
                    "question": follow.question,
                    "intent": follow.intent,
                }
                for follow in card.follow_ups
            ],
        },
        "anchor": anchor_payload(anchor, by_alias=True) if anchor else {},
        "current": {
            "question": question,
            "level": level or "main",
            "isDynamic": bool(state.get("current_is_dynamic")),
        },
        "answer": answer,
        "recent": _recent(state.get("records") or []),
        "digest": (state.get("progress_digest") or [])[-10:],
        "limits": {
            "followupsUsed": used,
            "canFollowUp": used < 3,
            "dynamicLeft": max(0, 5 - dynamic_count),
            "remainingCards": len(remaining_cards),
            "remainingFollowups": [
                {
                    "id": follow.id,
                    "level": follow.level,
                    "question": follow.question,
                }
                for follow in card.follow_ups
                if follow.id not in asked
            ],
        },
    }


async def evaluate(
    provider: ProviderConfig,
    state: dict,
    card: QuestionCard,
    anchor: Anchor | None,
    question: str,
    level: str,
    answer: str,
) -> InterviewerTurn:
    system = _system_prompt(follow_depth_of(state))
    payload = json.dumps(
        build_payload(state, card, anchor, question, level, answer),
        ensure_ascii=False,
        indent=2,
    )
    llm = choose_llm(provider, temperature=0.2, timeout=120, max_retries=1)
    structured = llm.with_structured_output(
        InterviewerTurn,
        method="json_mode",
        include_raw=True,
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=payload),
    ]

    last_error = ""
    for attempt in (1, 2):
        try:
            result = await structured.ainvoke(messages)
            turn, error = _coerce_turn(result)
        except Exception as exc:  # noqa: BLE001 - 供应商超时 / 解析失败都重试一次
            turn, error = None, str(exc)
        if turn is not None:
            return turn

        last_error = (error or "模型没有返回结构化结果")[:300]
        logger.warning("面试官评估失败（第 %d 次）：%s", attempt, last_error)
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=payload),
            HumanMessage(
                content=(
                    "上一次输出未通过 schema 校验："
                    f"{last_error}。请严格按结构化 schema 重新输出，"
                    "decision 只能是 follow_up / next_card / end。"
                )
            ),
        ]

    raise InterviewerError(f"评估失败：{last_error or '请重试'}")
