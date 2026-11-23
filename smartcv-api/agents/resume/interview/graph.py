"""模拟面试的 LangGraph 编排。

图只做 action 分发、检查点读写与事件出口：

    START → dispatch
      answer               → interviewer 节点 → (下一题 END / finish)
      skip                 → 整卡跳过        → (下一题 END / finish)
      skip_followup        → 只跳过当前追问  → 同卡下一条 / 下一题 / finish
      teach / teach_message→ teacher 节点   → END
      return               → 返回原问题     → END
      end                  → finish         → END

每个 action 只执行一个节点再落盘；节点内不拼全量历史，只带当前卡与最近记录。
provider 不写进检查点：图在每次请求时按 provider 编译，状态仍然复用同一个
thread_id 的 sqlite 检查点。
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Awaitable, Callable

from langgraph.constants import START, END
from langgraph.graph import StateGraph

from agents.resume.interview import (
    general_answer_agent,
    interviewer_agent,
    teacher_agent,
)
from agents.resume.interview.schemas import (
    Anchor,
    InterviewState,
    InterviewStateView,
    QuestionCard,
    ResumeProfile,
    SampleAnswer,
    SampleAnswerRequest,
)
from agents.resume.interview.tools.pack import first_pending
from agents.resume.interview.utils import policy
from agents.resume.marker.utils.runner import safe_writer
from agents.utils.checkpointer import get_checkpointer
from agents.utils.usage import collect_usage, current_meter, empty_usage, merge_usage
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_ACTIONS = (
    "answer",
    "skip",
    "skip_followup",
    "reanswer",
    "teach",
    "teach_message",
    "return",
    "end",
    "usage",
)


class InterviewNotFound(RuntimeError):
    """线程不存在 / 已过期 / 不属于当前会话。"""


class SampleAnswerNotFound(RuntimeError):
    """检查点里找不到要生成示例回答的那一轮作答。"""


# --------------------------------------------------------------------------- 状态读取


def _cards(state: dict) -> list[dict]:
    return state.get("cards") or []


def _card_dict(state: dict, card_id: str) -> dict | None:
    return next((card for card in _cards(state) if card.get("id") == card_id), None)


def _current_card(state: dict) -> QuestionCard:
    card = _card_dict(state, state.get("current_card_id") or "")
    if card is None:
        raise RuntimeError("当前问题卡不存在，面试状态可能已损坏")
    return QuestionCard.model_validate(card)


def _anchors(state: dict) -> list[Anchor]:
    return [Anchor.model_validate(item) for item in state.get("anchors") or []]


def _anchor_for(state: dict, card: QuestionCard) -> Anchor | None:
    return next((anchor for anchor in _anchors(state) if anchor.id == card.anchor_id), None)


def _index(state: dict) -> int:
    return len(state.get("done_card_ids") or []) + 1


def _card_index(state: dict, card_id: str) -> int:
    """题卡在整份题包里的序号；重答已完成的卡时进度按原始位置显示。"""
    for index, item in enumerate(_cards(state)):
        if item.get("id") == card_id:
            return index + 1
    return _index(state)


def _state_event(state: dict) -> dict:
    view = policy.state_view(state)
    return {"type": "state", **view.model_dump(by_alias=True)}


def _question_event(
    state: dict,
    card: QuestionCard,
    question: str,
    level: str,
    *,
    dynamic: bool = False,
    resumed: bool = False,
    reanswer: bool = False,
    index: int | None = None,
) -> dict:
    return {
        "type": "question",
        "cardId": card.id,
        "text": question,
        "level": level or "",
        "dynamic": dynamic,
        "mainQuestion": card.main_question,
        "dimension": card.dimension,
        "projectId": card.project_id,
        "followupsUsed": int((state.get("followup_used") or {}).get(card.id, 0)),
        "index": index if index is not None else _index(state),
        "total": len(_cards(state)),
        "resumed": resumed,
        "reanswer": reanswer,
    }


def _emit(writer, event: dict) -> None:
    writer(event)


def _advance_after_skip(w, state: dict, update: dict) -> dict:
    """跳过记录写好后推进到下一张未答卡；没有下一张就准备收尾。"""
    next_card = first_pending(
        [QuestionCard.model_validate(item) for item in _cards(state)],
        set(update.get("done_card_ids") or []),
    )
    if next_card is None:
        update.update(
            finish_pending=True,
            finished_reason="all_done",
            current_card_id="",
            current_question="",
            current_level="",
            current_is_dynamic=False,
            current_followup_id="",
        )
        _emit(w, _state_event({**state, **update}))
        return update

    update.update(
        current_card_id=next_card.id,
        current_question=next_card.main_question,
        current_level="",
        current_is_dynamic=False,
        current_followup_id="",
    )
    merged = {**state, **update}
    _emit(w, _question_event(merged, next_card, next_card.main_question, ""))
    _emit(w, _state_event(merged))
    return update


def _usage_update(state: dict) -> dict:
    """把本轮请求上下文里的 token 用量并入检查点。

    一个 action 只跑一个业务节点，因此计量器里就是本轮增量；没有调用模型时
    返回空更新，不制造无意义的检查点变更。
    """
    meter = current_meter()
    if meter is None:
        return {}
    delta = meter.snapshot()
    if not delta.get("calls"):
        return {}
    return {"usage": merge_usage(state.get("usage"), delta)}


# --------------------------------------------------------------------------- 图


def _build_graph(provider: ProviderConfig | None, usage_delta: dict | None = None):
    """按请求编译图；provider 只活在本轮调用里，不进入检查点。"""

    def writer():
        return safe_writer()

    async def answer_node(state: dict) -> dict:
        w = writer()
        card = _current_card(state)
        question = state.get("current_question") or card.main_question
        level = state.get("current_level") or ""
        answer = state.get("answer") or ""
        if not answer.strip():
            _emit(w, {"type": "error", "message": "回答不能为空", "fatal": False})
            return {}

        _emit(
            w,
            {
                "type": "turn.start",
                "cardId": card.id,
                "index": _index(state),
                "total": len(_cards(state)),
            },
        )
        _emit(w, {"type": "status", "stage": "evaluate", "text": "正在评估回答…"})

        assert provider is not None
        try:
            turn = await interviewer_agent.evaluate(
                provider,
                state,
                card,
                _anchor_for(state, card),
                question,
                level,
                answer,
            )
        except interviewer_agent.InterviewerError as exc:
            _emit(w, {"type": "error", "message": str(exc), "fatal": False})
            return _usage_update(state)

        done = list(state.get("done_card_ids") or [])
        remaining = len(
            [
                item
                for item in _cards(state)
                if item.get("id") not in done and item.get("id") != card.id
            ]
        )
        plan = policy.resolve_turn(
            turn,
            card,
            state,
            remaining_cards=remaining,
            anchors=_anchors(state),
        )

        if state.get("reanswer_pending"):
            source = "reanswer"
        elif level:
            source = "followup"
        else:
            source = "main"

        record = policy.make_record(
            card,
            question=question,
            answer=answer,
            source=source,
            level=level,
            plan=plan,
        )
        records = [*(state.get("records") or []), record.model_dump()]
        digest = [
            *(state.get("progress_digest") or []),
            policy.progress_line(record, card),
        ][-12:]
        _emit(
            w,
            {
                "type": "evaluation",
                "cardId": card.id,
                "leaks": plan.leaks,
                "offTopic": plan.off_topic,
                "feedback": plan.feedback,
                "source": source,
                "level": level or "",
            },
        )

        update: dict = {
            "records": records,
            "progress_digest": digest,
            "consecutive_off_topic": plan.consecutive_off_topic,
            "reanswer_pending": False,
            "action": "",
            "answer": "",
            "message": "",
            **_usage_update(state),
        }

        if plan.kind in ("followup", "dynamic"):
            used = int((state.get("followup_used") or {}).get(card.id, 0)) + 1
            followup_used = dict(state.get("followup_used") or {})
            followup_used[card.id] = used
            update.update(
                followup_used=followup_used,
                current_question=plan.question,
                current_level=plan.level,
                current_is_dynamic=plan.kind == "dynamic",
                current_followup_id=plan.followup_id,
            )
            if plan.kind == "followup":
                update["asked_followups"] = [
                    *(state.get("asked_followups") or []),
                    plan.followup_id,
                ]
            else:
                update["dynamic_count"] = int(state.get("dynamic_count") or 0) + 1
                update["asked_followups"] = list(state.get("asked_followups") or [])
                cards = copy.deepcopy(state.get("cards") or [])
                for item in cards:
                    if item.get("id") != card.id:
                        continue
                    dynamic = policy.dynamic_question(plan, card, source_index=len(records))
                    item["dynamic_questions"] = [
                        *(item.get("dynamic_questions") or []),
                        dynamic.model_dump(),
                    ]
                update["cards"] = cards

            merged = {**state, **update}
            _emit(
                w,
                _question_event(
                    merged,
                    card,
                    plan.question,
                    plan.level,
                    dynamic=plan.kind == "dynamic",
                ),
            )
            _emit(w, _state_event(merged))
        else:
            # next / end：当前卡结束；重答已完成的卡时不要重复写入 done。
            update["done_card_ids"] = done if card.id in done else [*done, card.id]
            update["consecutive_off_topic"] = 0
            update["reanswer_pending"] = False
            next_card = first_pending(
                [QuestionCard.model_validate(item) for item in _cards(state)],
                set(update["done_card_ids"]),
            )

            if plan.kind == "end" or next_card is None:
                update.update(
                    finish_pending=True,
                    finished_reason="all_done",
                    current_card_id="",
                    current_question="",
                    current_level="",
                    current_is_dynamic=False,
                    current_followup_id="",
                )
                _emit(w, _state_event({**state, **update}))
            else:
                update.update(
                    current_card_id=next_card.id,
                    current_question=next_card.main_question,
                    current_level="",
                    current_is_dynamic=False,
                    current_followup_id="",
                )
                merged = {**state, **update}
                _emit(w, _question_event(merged, next_card, next_card.main_question, ""))
                _emit(w, _state_event(merged))

        return update

    async def skip_node(state: dict) -> dict:
        w = writer()
        card = _current_card(state)
        question = state.get("current_question") or card.main_question
        events = copy.deepcopy(state.get("teaching_events") or [])

        if state.get("phase") == "teaching":
            policy.close_teaching(events, "skipped")
            _emit(w, {"type": "teaching.closed", "outcome": "skipped"})

        record = policy.make_record(
            card,
            question=question,
            answer="",
            source="skip",
            level=state.get("current_level") or "",
            plan=None,
            skipped=True,
        )
        done = [*(state.get("done_card_ids") or []), card.id]

        update: dict = {
            "records": [*(state.get("records") or []), record.model_dump()],
            "done_card_ids": done,
            "skipped_cards": [*(state.get("skipped_cards") or []), card.id],
            "teaching_events": events,
            "phase": "interviewing",
            "consecutive_off_topic": 0,
            "reanswer_pending": False,
            "action": "",
            "answer": "",
            "message": "",
        }
        return _advance_after_skip(w, state, update)

    async def skip_followup_node(state: dict) -> dict:
        """只跳过当前追问，保留已答的主问题。

        接着问本卡下一条未问的预设追问；没有剩余追问时才结束本卡，
        进入下一张主问题。整张卡不记入 skipped_cards，主问题仍算已答。
        """
        w = writer()
        card = _current_card(state)
        level = state.get("current_level") or ""
        question = state.get("current_question") or card.main_question
        if not level:
            _emit(
                w,
                {"type": "error", "message": "当前是主问题，请跳过整道题", "fatal": False},
            )
            return {}

        events = copy.deepcopy(state.get("teaching_events") or [])
        if state.get("phase") == "teaching":
            policy.close_teaching(events, "skipped")
            _emit(w, {"type": "teaching.closed", "outcome": "skipped"})

        record = policy.make_record(
            card,
            question=question,
            answer="",
            source="skip",
            level=level,
            plan=None,
            skipped=True,
        )
        # 只往后找：追问链按 L1 → L2 → L3 递进，跳过一条不能退回更浅的追问。
        asked = list(state.get("asked_followups") or [])
        asked_set = set(asked)
        current_id = state.get("current_followup_id") or ""
        index = next(
            (i for i, follow in enumerate(card.follow_ups) if follow.id == current_id),
            -1,
        )
        next_follow = None
        if index >= 0:
            next_follow = next(
                (
                    follow
                    for follow in card.follow_ups[index + 1 :]
                    if follow.id and follow.question.strip() and follow.id not in asked_set
                ),
                None,
            )

        update: dict = {
            "records": [*(state.get("records") or []), record.model_dump()],
            "teaching_events": events,
            "phase": "interviewing",
            "consecutive_off_topic": 0,
            "reanswer_pending": False,
            "action": "",
            "answer": "",
            "message": "",
        }

        if next_follow is None:
            done = list(state.get("done_card_ids") or [])
            if card.id not in done:
                done.append(card.id)
            update["done_card_ids"] = done
            return _advance_after_skip(w, state, update)

        followup_used = dict(state.get("followup_used") or {})
        followup_used[card.id] = int(followup_used.get(card.id, 0)) + 1
        update.update(
            followup_used=followup_used,
            asked_followups=[*asked, next_follow.id],
            current_card_id=card.id,
            current_question=next_follow.question,
            current_level=next_follow.level,
            current_is_dynamic=False,
            current_followup_id=next_follow.id,
        )
        merged = {**state, **update}
        _emit(
            w,
            _question_event(merged, card, next_follow.question, next_follow.level),
        )
        _emit(w, _state_event(merged))
        return update

    async def teach_node(state: dict) -> dict:
        w = writer()
        card = _current_card(state)
        question = state.get("current_question") or card.main_question
        events = copy.deepcopy(state.get("teaching_events") or [])
        event = policy.new_teaching_event(card.id, question).model_dump()
        policy.append_teaching_turn(event, "user", "我不会，请讲解这道题。")
        events.append(event)

        _emit(w, {"type": "teaching.started", "cardId": card.id, "question": question})
        _emit(w, {"type": "status", "stage": "teaching", "text": "正在准备讲解…"})

        assert provider is not None
        try:
            reply = await teacher_agent.stream_reply(
                provider,
                state,
                card,
                _anchor_for(state, card),
                [],
                "我不会，请讲解这道题。",
                lambda item: _async_emit(w, item),
                question=question,
                level=state.get("current_level") or "",
            )
        except teacher_agent.TeacherError as exc:
            _emit(w, {"type": "error", "message": str(exc), "fatal": False})
            return {
                "phase": "teaching",
                "teaching_events": events,
                "action": "",
                "message": "",
                **_usage_update(state),
            }

        policy.append_teaching_turn(event, "teacher", reply)
        _emit(
            w,
            {"type": "teaching.turn", "role": "teacher", "text": reply, "cardId": card.id},
        )
        update = {
            "phase": "teaching",
            "teaching_events": events,
            "action": "",
            "message": "",
            **_usage_update(state),
        }
        _emit(w, _state_event({**state, **update}))
        return update

    async def teach_message_node(state: dict) -> dict:
        w = writer()
        message = (state.get("message") or "").strip()
        if not message:
            _emit(w, {"type": "error", "message": "内容不能为空", "fatal": False})
            return {}

        card = _current_card(state)
        question = state.get("current_question") or card.main_question
        events = copy.deepcopy(state.get("teaching_events") or [])
        event = policy.active_teaching(events)
        if event is None:
            _emit(w, {"type": "error", "message": "教学会话已结束，请返回面试", "fatal": False})
            return {}

        history = list(event.get("turns") or [])
        policy.append_teaching_turn(event, "user", message)
        _emit(
            w,
            {
                "type": "teaching.turn",
                "role": "user",
                "text": message,
                "cardId": card.id,
            },
        )

        assert provider is not None
        try:
            reply = await teacher_agent.stream_reply(
                provider,
                state,
                card,
                _anchor_for(state, card),
                history,
                message,
                lambda item: _async_emit(w, item),
                question=question,
                level=state.get("current_level") or "",
            )
        except teacher_agent.TeacherError as exc:
            _emit(w, {"type": "error", "message": str(exc), "fatal": False})
            return {
                "phase": "teaching",
                "teaching_events": events,
                "action": "",
                "message": "",
                **_usage_update(state),
            }

        policy.append_teaching_turn(event, "teacher", reply)
        _emit(
            w,
            {"type": "teaching.turn", "role": "teacher", "text": reply, "cardId": card.id},
        )
        update = {
            "phase": "teaching",
            "teaching_events": events,
            "action": "",
            "message": "",
            **_usage_update(state),
        }
        _emit(w, _state_event({**state, **update}))
        return update

    async def reanswer_node(state: dict) -> dict:
        """回到最近一次作答的题目，允许用新的回答重答。

        不消耗模型；只把当前题指针拨回上一轮记录，下一轮 answer 会按
        `reanswer_pending` 记作 reanswer。已完成的卡不会重复计入进度。
        """
        w = writer()
        records = list(state.get("records") or [])
        record = next(
            (item for item in reversed(records) if not item.get("skipped")), None
        )
        if record is None:
            _emit(w, {"type": "error", "message": "还没有可以重答的题目", "fatal": False})
            return {}

        card_id = record.get("card_id") or ""
        card_data = _card_dict(state, card_id)
        if card_data is None:
            _emit(
                w,
                {"type": "error", "message": "找不到上一题，请刷新后重试", "fatal": False},
            )
            return {}

        card = QuestionCard.model_validate(card_data)
        question = record.get("question") or card.main_question
        level = record.get("level") or ""
        followup_id = next(
            (follow.id for follow in card.follow_ups if follow.question == question),
            "",
        )
        dynamic = any(
            item.question == question for item in card.dynamic_questions
        )

        update = {
            "phase": "interviewing",
            "current_card_id": card.id,
            "current_question": question,
            "current_level": level,
            "current_is_dynamic": dynamic,
            "current_followup_id": followup_id,
            "reanswer_pending": True,
            "action": "",
            "answer": "",
            "message": "",
        }
        merged = {**state, **update}
        _emit(
            w,
            _question_event(
                merged,
                card,
                question,
                level,
                dynamic=dynamic,
                resumed=True,
                reanswer=True,
                index=_card_index(state, card.id),
            ),
        )
        _emit(w, _state_event(merged))
        return update

    async def return_node(state: dict) -> dict:
        w = writer()
        card = _current_card(state)
        events = copy.deepcopy(state.get("teaching_events") or [])
        policy.close_teaching(events, "returned")
        _emit(w, {"type": "teaching.closed", "outcome": "returned"})

        update = {
            "phase": "interviewing",
            "teaching_events": events,
            "reanswer_pending": True,
            "action": "",
            "message": "",
            "answer": "",
        }
        merged = {**state, **update}
        _emit(
            w,
            _question_event(
                merged,
                card,
                state.get("current_question") or card.main_question,
                state.get("current_level") or "",
                dynamic=bool(state.get("current_is_dynamic")),
                resumed=True,
            ),
        )
        _emit(w, _state_event(merged))
        return update

    async def end_node(state: dict) -> dict:
        w = writer()
        events = copy.deepcopy(state.get("teaching_events") or [])
        if state.get("phase") == "teaching":
            policy.close_teaching(events, "skipped")
            _emit(w, {"type": "teaching.closed", "outcome": "skipped"})
        return {
            "teaching_events": events,
            "phase": "interviewing",
            "finish_pending": True,
            "finished_reason": "user_end",
            "action": "",
            "answer": "",
            "message": "",
        }

    async def finish_node(state: dict) -> dict:
        w = writer()
        summary = policy.build_summary(state)
        update = {
            "phase": "finished",
            "finish_pending": False,
            "finished_reason": state.get("finished_reason") or "user_end",
            "current_card_id": "",
            "current_question": "",
            "current_level": "",
            "current_is_dynamic": False,
            "current_followup_id": "",
            "action": "",
            "answer": "",
            "message": "",
        }
        _emit(w, {"type": "summary", **summary})
        _emit(w, _state_event({**state, **update}))
        return update

    async def usage_node(state: dict) -> dict:
        """只把一次模型调用的用量写回检查点，不推进面试。

        用于 `/sample-answer` 这类只读接口：生成示例回答本身不改变面试进度，
        但消耗的 token 应该计入本场统计。
        """
        usage = (
            merge_usage(state.get("usage"), usage_delta)
            if usage_delta
            else state.get("usage") or empty_usage()
        )
        return {
            "usage": usage,
            "action": "",
            "answer": "",
            "message": "",
        }

    # ------------------------------------------------------------------ 图构建
    # 图的 channel 全部来自 InterviewState；每次请求只跑一个业务节点，节点返回值
    # 合并回检查点，过程事件通过 custom 流实时推给前端。
    graph = StateGraph(InterviewState)

    # ---- 节点：一个 action 对应一个节点 ----
    # answer         评估本轮回答，决定「追问 / 下一题 / 结束」并写回进度
    # skip           跳过整道题，记一条 skipped 记录后推进
    # skip_followup  只跳过当前追问，主问题保留已答，继续本卡追问链
    # reanswer       回到上一题重答，不调用模型
    # teach          开始讲解：写入首条用户消息并让教练回复
    # teach_message  讲解模式内继续追问，教练基于已有对话回复
    # return         结束讲解，回到同一道题重答（下一轮记作 reanswer）
    # end            用户主动结束：关闭未结束的讲解会话，准备收尾
    # finish         汇总记录并写入 finished 状态
    # usage          内部动作：只累计 token，不推进面试
    graph.add_node("answer", answer_node)
    graph.add_node("skip", skip_node)
    graph.add_node("skip_followup", skip_followup_node)
    graph.add_node("reanswer", reanswer_node)
    graph.add_node("teach", teach_node)
    graph.add_node("teach_message", teach_message_node)
    graph.add_node("return", return_node)
    graph.add_node("end", end_node)
    graph.add_node("finish", finish_node)
    graph.add_node("usage", usage_node)

    # ---- 入口：START 按本轮 action 分发 ----
    # 枚举里没有的 action（含空值）一律走 end，按兜底结束处理，避免空跑。
    graph.add_conditional_edges(
        START,
        lambda state: state.get("action") if state.get("action") in _ACTIONS else "end",
        {action: action for action in _ACTIONS},
    )

    # ---- 出题节点可能的两种去向 ----
    # answer / skip / skip_followup 推进后如果没有下一张卡（或面试官判定结束），
    # finish_pending 为真就进 finish；否则本轮到此为止，等用户下一次请求再跑。
    for node in ("answer", "skip", "skip_followup"):
        graph.add_conditional_edges(
            node,
            lambda state: "finish" if state.get("finish_pending") else END,
            {"finish": "finish", END: END},
        )

    # ---- 其余节点都是一次请求一回合，跑完直接结束 ----
    # 讲解的继续追问、返回作答都只影响当前状态，不触发下一题。
    graph.add_edge("reanswer", END)
    graph.add_edge("teach", END)
    graph.add_edge("teach_message", END)
    graph.add_edge("return", END)
    graph.add_edge("usage", END)
    # 结束请求先清理讲解会话，再统一进 finish 生成复盘并置为 finished。
    graph.add_edge("end", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=get_checkpointer("interview"))


async def _async_emit(writer, event: dict) -> None:
    writer(event)


# --------------------------------------------------------------------------- 对外入口


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _owned(values: dict, owner_session: str | None) -> bool:
    owner = values.get("owner_session") or ""
    return not owner or owner == (owner_session or "")


async def load_values(thread_id: str, owner_session: str | None) -> dict | None:
    graph = _build_graph(None)
    snapshot = await graph.aget_state(_config(thread_id))
    values = snapshot.values or {}
    if not values or values.get("thread_id") != thread_id:
        return None
    if not _owned(values, owner_session):
        return None
    return values


async def get_state(thread_id: str, owner_session: str | None) -> InterviewStateView | None:
    values = await load_values(thread_id, owner_session)
    if values is None:
        return None
    return policy.state_view(values)


def _pick_record(records: list[dict], card_id: str, question: str) -> dict | None:
    """优先按题卡 + 问题文本定位最近一轮；文本有差异时退回该卡最近一条。"""
    if card_id:
        same_card = [item for item in records if item.get("card_id") == card_id]
        if not same_card:
            return None
        matched = [item for item in same_card if item.get("question") == question]
        return matched[-1] if matched else same_card[-1]
    if question:
        matched = [item for item in records if item.get("question") == question]
        if matched:
            return matched[-1]
    return records[-1] if records else None


async def sample_answer(
    provider: ProviderConfig,
    values: dict,
    *,
    card_id: str = "",
    question: str = "",
) -> SampleAnswer:
    """按检查点里已记录的一轮作答生成示例回答；只读，不推进面试。

    由前端在评价卡上点击触发，作答、评价与题卡都直接取自检查点，
    不信任前端传来的事实字段，避免示例回答脱离本轮实际内容。
    """
    record = _pick_record(values.get("records") or [], card_id, question)
    target_card = card_id or (record or {}).get("card_id") or ""
    card_data = next(
        (
            item
            for item in values.get("cards") or []
            if item.get("id") == target_card
        ),
        None,
    )
    if record is None or card_data is None:
        raise SampleAnswerNotFound("找不到这一轮的作答记录，请刷新后重试")

    card = QuestionCard.model_validate(card_data)
    req = SampleAnswerRequest(
        profile=ResumeProfile.model_validate(values.get("profile") or {}),
        anchors=[Anchor.model_validate(item) for item in values.get("anchors") or []],
        card=card,
        question=(record.get("question") or question or "").strip()
        or card.main_question,
        level=record.get("level") or None,
        answer=record.get("answer") or "",
        feedback=(record.get("feedback") or "").strip()
        or "补全回答中缺失的关键点",
        leaks=record.get("leaks") or [],
    )
    return await general_answer_agent.run(provider, req, SampleAnswer)


async def record_usage(
    thread_id: str,
    owner_session: str | None,
    usage: dict,
) -> dict | None:
    """把只读接口（如示例回答）的 token 用量写回检查点。

    用内部 `usage` action 走一次图，只更新 usage，不改变题号、记录或阶段；
    返回更新后的累计值，检查点不存在或不属于当前会话时返回 None。
    """
    if not usage or not usage.get("calls"):
        return None
    graph = _build_graph(None, usage_delta=usage)
    config = _config(thread_id)
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    if (
        not values
        or values.get("thread_id") != thread_id
        or not _owned(values, owner_session)
    ):
        return None
    await graph.ainvoke({"action": "usage"}, config)
    return merge_usage(values.get("usage"), usage)


async def create_thread(
    thread_id: str,
    *,
    owner_session: str | None,
    use_mode: str,
    scene: str,
    follow_depth: str,
    focus: str,
    profile: ResumeProfile,
    anchors: list[Anchor],
    cards: list[QuestionCard],
) -> None:
    """出题后写入首张卡与只读上下文，不额外跑模型。"""
    first = policy.first_card(cards)
    if first is None:
        raise RuntimeError("题目为空，无法开始面试")

    initial = {
        "thread_id": thread_id,
        "owner_session": owner_session or "",
        "use_mode": use_mode,
        "scene": scene,
        "follow_depth": follow_depth or "",
        "focus": focus,
        "profile": profile.model_dump(),
        "anchors": [anchor.model_dump() for anchor in anchors],
        "cards": [card.model_dump() for card in cards],
        "phase": "interviewing",
        "current_card_id": first.id,
        "current_question": first.main_question,
        "current_level": "",
        "current_is_dynamic": False,
        "current_followup_id": "",
        "asked_followups": [],
        "followup_used": {},
        "dynamic_count": 0,
        "consecutive_off_topic": 0,
        "reanswer_pending": False,
        "done_card_ids": [],
        "skipped_cards": [],
        "records": [],
        "teaching_events": [],
        "progress_digest": [],
        "usage": empty_usage(),
        "finished_reason": "",
        "started": False,
        "finish_pending": False,
        "action": "",
        "answer": "",
        "message": "",
    }
    graph = _build_graph(None)
    await graph.aupdate_state(_config(thread_id), initial, as_node=START)


async def stream_interview(
    provider: ProviderConfig,
    *,
    thread_id: str,
    action: str,
    answer: str,
    message: str,
    owner_session: str | None,
    emit: Callable[[dict], Awaitable[None]],
) -> None:
    """跑一轮 action，把所有 custom 事件逐条转交 emit。"""
    graph = _build_graph(provider)
    config = _config(thread_id)
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    if not values or values.get("thread_id") != thread_id:
        raise InterviewNotFound("面试不存在或已过期，请重新开始")
    if not _owned(values, owner_session):
        raise InterviewNotFound("面试不存在或已过期，请重新开始")

    policy.validate_action(action, values.get("phase") or "interviewing")
    if not values.get("started"):
        # 新线程的检查点由 thread 接口以 START 为源写入；这里也必须指定 as_node，
        # 否则 langgraph 无法推断更新来源。
        await graph.aupdate_state(config, {"started": True}, as_node=START)
        await emit(
            {
                "type": "interview.started",
                "threadId": thread_id,
                "scene": values.get("scene") or "project",
                "followDepth": policy.follow_depth_of(values),
                "totalCards": len(_cards(values)),
            }
        )

    started = time.perf_counter()
    with collect_usage() as meter:
        async for mode, chunk in graph.astream(
            {"action": action, "answer": answer, "message": message},
            stream_mode=["updates", "custom"],
            config=config,
        ):
            if mode == "custom":
                await emit(chunk)

    delta = meter.snapshot()
    if delta.get("calls"):
        latest = await graph.aget_state(config)
        total = (latest.values or {}).get("usage") or merge_usage(
            values.get("usage"), delta
        )
        await emit({"type": "usage", "usage": delta, "total": total})

    logger.info(
        "interview action: thread=%s action=%s elapsed=%.2fs",
        thread_id,
        action,
        time.perf_counter() - started,
    )
