"""面试的确定性策略：场景校验、追问轮次、动态配额、状态视图。

模型只给候选决策，是否采纳由这里决定。规则出处见 SDD 5.7：

  - 单锚点最多追问 3 轮；
  - 单场动态问题最多 5 条，且必须有触发原因与关联锚点；
  - 当前卡考察点已覆盖 / 连续两次答非所问 → 下一题；
  - `end` 只在没有剩余卡片时生效，用户主动结束走 action=end。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.resume.interview.schemas import (
    Anchor,
    AnswerRecord,
    DynamicQuestion,
    InterviewStateView,
    InterviewerTurn,
    PackRequest,
    QuestionCard,
    ResumeProfile,
    TeachingEvent,
    TeachingTurn,
    ThreadRequest,
    TokenUsage,
    now_iso,
)
from agents.resume.interview.tools.pack import first_pending

MAX_FOLLOWUPS_PER_CARD = 3
MAX_DYNAMIC_PER_INTERVIEW = 5
DYNAMIC_REASONS = ("new_anchor", "contradiction", "metric_anomaly", "shallow")


class PolicyError(ValueError):
    """请求不符合面试规则；路由层转成 400 / 409 / 422。"""


# --------------------------------------------------------------------------- 场景校验


def validate_mode(req: PackRequest) -> None:
    """校验出题场景 + 追问强度 + 选择项。"""
    project_ids = [pid for pid in req.project_ids if pid]
    project_keys = {project.id for project in req.profile.projects}

    if req.scene == "project":
        if len(project_ids) != 1:
            raise PolicyError("项目面试必须且只能选择一个项目")
        if project_ids[0] not in project_keys:
            raise PolicyError("所选项目不在确认后的画像里")
        if req.follow_depth not in ("normal", "deep"):
            raise PolicyError("项目面试必须选择常规或深度追问")
        return

    if req.scene == "comprehensive":
        if req.follow_depth:
            raise PolicyError("综合面试不使用深度追问")
        if req.focus != "balanced":
            raise PolicyError("综合面试不使用考察方向")
        return

    if req.scene == "scenario":
        if req.follow_depth:
            raise PolicyError("排查面试不使用深度追问")
        if req.focus != "balanced":
            raise PolicyError("排查面试不使用考察方向")
        if project_ids:
            raise PolicyError("排查面试不需要选择项目")
        return

    raise PolicyError("出题场景只能是项目面试、综合面试或排查面试")


def validate_thread(req: ThreadRequest) -> None:
    """建场只校验问题卡可答；出题规则已在 /pack 校验过，这里不重新出题。"""
    if req.use_mode != "dialog":
        raise PolicyError("清单自测不创建面试线程")
    if not req.cards:
        raise PolicyError("题目为空，无法开始面试")
    project_ids = {project.id for project in req.profile.projects}
    unknown = sorted(
        {
            card.project_id
            for card in req.cards
            if card.project_id and card.project_id not in project_ids
        }
    )
    if unknown:
        raise PolicyError("题目引用的项目不在当前画像里，请重新生成")
    anchor_ids = {anchor.id for anchor in req.anchors}
    if req.anchors:
        dangling = [
            card.anchor_id
            for card in req.cards
            if card.anchor_id and card.anchor_id not in anchor_ids
        ]
        if dangling:
            raise PolicyError("题目引用的证据锚点不在当前画像里，请重新生成")


def validate_action(action: str, phase: str) -> None:
    if phase == "finished":
        raise PolicyError("本场面试已结束")
    if action in ("answer", "reanswer") and phase != "interviewing":
        raise PolicyError("当前处于教学阶段，请先返回面试再作答")
    if action == "teach" and phase != "interviewing":
        raise PolicyError("当前已经在教学阶段")
    if action in ("teach_message", "return") and phase != "teaching":
        raise PolicyError("当前不在教学阶段")
    if action not in (
        "answer",
        "skip",
        "skip_followup",
        "reanswer",
        "teach",
        "teach_message",
        "return",
        "end",
    ):
        raise PolicyError("未知的 action")


# --------------------------------------------------------------------------- 出题


def first_card(cards: list[QuestionCard]) -> QuestionCard | None:
    return first_pending(cards, set())


def next_card(
    cards: list[QuestionCard], done_ids: list[str], current_id: str = ""
) -> QuestionCard | None:
    done = set(done_ids)
    if current_id:
        done.add(current_id)
    return first_pending(cards, done)


# --------------------------------------------------------------------------- 一轮决策


@dataclass
class TurnPlan:
    leaks: list[str]
    off_topic: bool
    feedback: str
    kind: str  # followup | dynamic | next | end
    question: str = ""
    level: str = ""
    followup_id: str = ""
    dynamic_reason: str = ""
    dynamic_anchor_id: str = ""
    coverage_complete: bool = False
    card_summary: str = ""
    consecutive_off_topic: int = 0
    extras: dict = field(default_factory=dict)


def resolve_turn(
    turn: InterviewerTurn,
    card: QuestionCard,
    state: dict,
    *,
    remaining_cards: int,
    anchors: list[Anchor],
) -> TurnPlan:
    """把面试官的结构化输出收敛成一个确定的下一步。"""
    leaks = [text.strip() for text in turn.leaks if text and text.strip()]
    feedback = (turn.feedback or "").strip()
    off_topic = bool(turn.off_topic)

    used = int((state.get("followup_used") or {}).get(card.id, 0))
    asked = set(state.get("asked_followups") or [])
    dynamic_count = int(state.get("dynamic_count") or 0)
    consecutive = int(state.get("consecutive_off_topic") or 0)
    consecutive = consecutive + 1 if off_topic else 0

    can_follow = used < MAX_FOLLOWUPS_PER_CARD and not turn.coverage_complete and consecutive < 2
    remaining_presets = [f for f in card.follow_ups if f.id not in asked]
    anchor_ids = {a.id for a in anchors}
    dynamic_ok = (
        bool((turn.dynamic_question or "").strip())
        and turn.dynamic_reason in DYNAMIC_REASONS
        and (turn.dynamic_anchor_id in anchor_ids)
        and dynamic_count < MAX_DYNAMIC_PER_INTERVIEW
    )

    plan = TurnPlan(
        leaks=leaks,
        off_topic=off_topic,
        feedback=feedback,
        kind="next",
        coverage_complete=bool(turn.coverage_complete),
        card_summary=(turn.card_summary or "").strip(),
        consecutive_off_topic=consecutive,
    )

    if not can_follow:
        chosen = None
    elif turn.decision == "next_card":
        chosen = None
    elif turn.decision == "end":
        chosen = None
    elif turn.decision == "follow_up":
        chosen = next(
            (f for f in remaining_presets if f.id == turn.followup_id), None
        )
        if chosen is None and remaining_presets:
            chosen = remaining_presets[0]
    else:
        chosen = None

    if chosen is not None:
        plan.kind = "followup"
        plan.question = chosen.question
        plan.level = chosen.level
        plan.followup_id = chosen.id
        return plan

    if turn.decision == "follow_up" and can_follow and not remaining_presets and dynamic_ok:
        plan.kind = "dynamic"
        plan.question = turn.dynamic_question.strip()
        plan.level = turn.dynamic_level if turn.dynamic_level in ("L1", "L2", "L3") else "L2"
        plan.dynamic_reason = turn.dynamic_reason
        plan.dynamic_anchor_id = turn.dynamic_anchor_id
        return plan

    if turn.decision == "end" and remaining_cards <= 0:
        plan.kind = "end"
        return plan

    plan.kind = "next"
    return plan


def dynamic_question(plan: TurnPlan, card: QuestionCard, source_index: int) -> DynamicQuestion:
    order = len(card.dynamic_questions) + 1
    return DynamicQuestion(
        id=f"d{card.id[1:]}_{order}",
        question=plan.question,
        level=plan.level or "L2",
        anchor_id=plan.dynamic_anchor_id,
        reason_type=plan.dynamic_reason or "shallow",
        source_index=source_index,
    )


# --------------------------------------------------------------------------- 状态与汇总


def make_record(
    card: QuestionCard,
    *,
    question: str,
    answer: str,
    source: str,
    level: str,
    plan: TurnPlan | None,
    skipped: bool = False,
) -> AnswerRecord:
    return AnswerRecord(
        card_id=card.id,
        question=question,
        answer=answer,
        source=source,  # type: ignore[arg-type]
        level=level or None,  # type: ignore[arg-type]
        leaks=plan.leaks if plan else [],
        off_topic=plan.off_topic if plan else False,
        feedback=plan.feedback if plan else "",
        skipped=skipped,
    )


def new_teaching_event(card_id: str, question: str) -> TeachingEvent:
    return TeachingEvent(
        card_id=card_id,
        question=question,
        turns=[],
        outcome="active",
        started_at=now_iso(),
    )


def active_teaching(events: list[dict]) -> dict | None:
    for event in reversed(events or []):
        if event.get("outcome") == "active":
            return event
    return None


def close_teaching(events: list[dict], outcome: str) -> list[dict]:
    for event in reversed(events or []):
        if event.get("outcome") == "active":
            event["outcome"] = outcome
            event["ended_at"] = now_iso()
            break
    return events


def append_teaching_turn(event: dict, role: str, content: str) -> None:
    turns = event.setdefault("turns", [])
    turns.append(TeachingTurn(role=role, content=content).model_dump())


def follow_depth_of(state: dict) -> str:
    return str(state.get("follow_depth") or "")


def state_view(state: dict) -> InterviewStateView:
    cards = state.get("cards") or []
    phase = state.get("phase") or "interviewing"
    done = state.get("done_card_ids") or []
    total = len(cards)
    if phase == "finished":
        index = total if total else len(done)
    else:
        index = min(len(done) + 1, total) if total else 0

    records = [AnswerRecord.model_validate(item) for item in state.get("records") or []]
    teaching = [TeachingEvent.model_validate(item) for item in state.get("teaching_events") or []]
    return InterviewStateView(
        thread_id=state.get("thread_id") or "",
        scene=state.get("scene") or "project",  # type: ignore[arg-type]
        follow_depth=follow_depth_of(state) or None,  # type: ignore[arg-type]
        phase=phase,  # type: ignore[arg-type]
        current_card_id=state.get("current_card_id") or "",
        current_question=state.get("current_question") or "",
        current_level=(state.get("current_level") or None),  # type: ignore[arg-type]
        index=index,
        total=total,
        dynamic_count=int(state.get("dynamic_count") or 0),
        followup_used=dict(state.get("followup_used") or {}),
        records=records,
        skipped_cards=list(state.get("skipped_cards") or []),
        teaching=teaching,
        usage=TokenUsage.model_validate(state.get("usage") or {}),
        finished_reason=state.get("finished_reason") or "",
    )


def build_summary(state: dict) -> dict:
    # 检查点里的 records 是 snake_case；summary 是直接推给前端的 SSE 事件，
    # 必须和其它事件一样按别名输出。否则前端拿不到 cardId / createdAt /
    # sampleAnswer，结束收尾时按「卡 + 问题 + 回答」回填示例回答也会全部落空。
    records = [
        AnswerRecord.model_validate(item).model_dump(by_alias=True)
        for item in state.get("records") or []
    ]
    answered = [r for r in records if not r.get("skipped")]
    skipped = [r for r in records if r.get("skipped")]
    usage = TokenUsage.model_validate(state.get("usage") or {})
    return {
        "records": records,
        "dynamicCount": int(state.get("dynamic_count") or 0),
        "teachingCount": len(state.get("teaching_events") or []),
        "answeredCount": len(answered),
        "skippedCount": len(skipped),
        "usage": usage.model_dump(by_alias=True),
        "finishedReason": state.get("finished_reason") or "",
    }


def progress_line(record: AnswerRecord, card: QuestionCard) -> str:
    tags: list[str] = []
    if record.leaks:
        tags.append(f"露馅 {len(record.leaks)} 条")
    if record.off_topic:
        tags.append("答非所问")
    if record.skipped:
        tags.append("跳过")
    suffix = f"（{'、'.join(tags)}）" if tags else ""
    feedback = record.feedback.strip()
    detail = f" · {feedback}" if feedback else ""
    return f"{card.dimension}{detail}{suffix}"


def score_card(cards: list[QuestionCard], card_id: str) -> QuestionCard | None:
    return next((card for card in cards if card.id == card_id), None)


def pick_project_name(profile: ResumeProfile, project_id: str) -> str:
    for project in profile.projects:
        if project.id == project_id:
            return project.name
    return ""


__all__ = [
    "PolicyError",
    "validate_mode",
    "validate_thread",
    "validate_action",
    "first_card",
    "next_card",
    "resolve_turn",
    "dynamic_question",
    "make_record",
    "new_teaching_event",
    "active_teaching",
    "close_teaching",
    "append_teaching_turn",
    "follow_depth_of",
    "state_view",
    "build_summary",
    "progress_line",
    "score_card",
    "pick_project_name",
]
