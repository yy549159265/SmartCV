"""规划 agent：先反问补齐 brief 与调研方面，再为每个维度生成检索词。

反问由模型通过 `ask_user_question` 工具发起（interrupt 暂停规划），问题与选项
结合岗位 / 简历生成，不在代码里写死。两轮反问是流程硬约束：

  1. 岗位 / 城市 / 年限缺失时先问用户，信息没补齐不进入生成；
  2. brief 齐了以后必须再问一次「想重点调研哪些方面」，答案按列表保存，
     当前前端单选，后续多选无需改协议。这一轮是调研的触发条件：用户没选
     任何方面时不能拿城市 / 年限凑检索计划，补问一次仍为空就结束本轮。

答案经 /api/market/answer 交回任务通道；模型拿到答案后一次结构化调用输出
固定维度（jobs / trend）与动态维度的检索词。模型漏问时由代码兜底补问。
"""

import asyncio
import json
import re
import uuid
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.tools.ask_user import make_ask_tool
from agents.resume.marker.utils.dims import ASPECT_HINTS, DIM_MAX_QUERIES, FIXED_DIMS, dim_label, report_sections
from agents.resume.marker.utils.runner import run_structured, safe_writer
from agents.resume.marker.schemas import Brief, PlanResult
from agents.resume.marker.utils.task import MarketTask
from agents.resume.marker.utils.stage_log import stage_exception, stage_warning
from agents.resume.marker.utils.common import (
    dim_ids,
    fallback_groups,
    strip_city,
    time_window_label,
    time_window_range,
)
from agents.resume.optimize.utils.checkpointer import get_checkpointer

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "plan" / "planner.md").read_text(encoding="utf-8")
_ASK_TIMEOUT_SECONDS = 240

_MISSING_OPTIONS = {
    "target_role": ("前端工程师", "后端工程师", "算法工程师"),
    "city": ("上海", "北京", "深圳"),
    "experience": ("1 年以内", "1-3 年", "3-5 年"),
}
_OPTION_DESC = {
    "target_role": "也可以选「其他」直接填写具体岗位",
    "city": "也可以填「不限」或其他城市",
    "experience": "按累计工作年限选择",
}
_PLACEHOLDERS = {"", "不限", "不限城市", "跳过", "其他"}
_NO_ASPECT_REASON = "未选择调研重点，已停止本轮调研"


def build_agent(llm):
    """规划 agent 自带反问工具；两轮反问由模型发起，代码只做兜底。"""
    return create_agent(
        model=llm,
        tools=[make_ask_tool()],
        response_format=PlanResult,
        checkpointer=get_checkpointer(),
    )


async def _ask_user(task: MarketTask | None, payload: dict, writer) -> list[dict]:
    """发 ask_question 事件并等前端答案；没有任务通道时按跳过处理。"""
    if task is None:
        writer({"type": "tool_result", "tool": "ask_user_question", "result": "当前会话不可用，跳过提问"})
        return []

    question_id = uuid.uuid4().hex
    future = task.open_question(question_id)
    writer(
        {
            "type": "tool_call",
            "tool": "ask_user_question",
            "args": {"title": payload.get("title", ""), "questions": len(payload.get("questions") or [])},
        }
    )
    writer(
        {
            "type": "ask_question",
            "questionId": question_id,
            "timeoutSeconds": _ASK_TIMEOUT_SECONDS,
            **payload,
        }
    )
    try:
        answers = await asyncio.wait_for(future, timeout=_ASK_TIMEOUT_SECONDS)
        writer(
            {
                "type": "tool_result",
                "tool": "ask_user_question",
                "result": f"用户已回答 {len(answers)} 个问题" if answers else "用户跳过提问",
            }
        )
        return answers if isinstance(answers, list) else []
    except asyncio.TimeoutError:
        writer({"type": "ask_question_closed", "questionId": question_id, "reason": "timeout"})
        writer({"type": "tool_result", "tool": "ask_user_question", "result": "等待回答超时，按现有信息继续"})
        return []
    finally:
        task.clear_question(question_id)


def _question(qid: str, header: str, question: str, options: tuple[str, ...], *, multi: bool = False) -> dict:
    return {
        "id": qid,
        "header": header,
        "question": question,
        "multiSelect": multi,
        "options": [{"label": label, "description": _OPTION_DESC.get(qid, "")} for label in options],
        "allowCustom": True,
    }


def _pick_value(answer: dict) -> str:
    custom = str(answer.get("custom") or "").strip()
    if custom:
        return custom
    selected = [str(item).strip() for item in answer.get("selected") or [] if str(item).strip()]
    value = selected[0] if selected else ""
    return "" if value in _PLACEHOLDERS else value


async def _ask_missing(brief: Brief, task: MarketTask | None, writer) -> Brief:
    """兜底：模型没有发起第一轮反问时，代码补齐岗位 / 城市 / 年限。"""
    questions: list[dict] = []
    if not brief.target_role.strip():
        questions.append(_question("target_role", "目标岗位", "你这次主要想投什么方向 / 岗位？", _MISSING_OPTIONS["target_role"]))
    if not brief.city.strip():
        questions.append(_question("city", "求职城市", "你计划在哪个城市求职？", _MISSING_OPTIONS["city"]))
    if not brief.experience.strip():
        questions.append(_question("experience", "工作年限", "你的累计工作年限大概是？", _MISSING_OPTIONS["experience"]))
    if not questions:
        return brief

    answers = await _ask_user(task, {"title": "先补齐调研信息", "questions": questions}, writer)
    updates: dict[str, str] = {}
    for answer in answers:
        key = str(answer.get("id") or "")
        if key in ("target_role", "city", "experience"):
            value = _pick_value(answer)
            if value:
                updates[key] = value
    return brief.model_copy(update=updates) if updates else brief


def _resolve_aspect(text: str) -> tuple[str, str]:
    """把用户选的方面转成（维度 id, 展示名）。

    只有固定维度有保留 id；其余一律按用户写的文字生成，不做关键词归类，
    也不存在「面试 / 薪资 / 公司」这类预置 id。
    """
    text = text.strip()
    if text in FIXED_DIMS:
        return text, dim_label(text)
    slug = re.sub(r"[^0-9a-zA-Z]+", "-", text).strip("-").lower()
    return (slug or text), text


def _normalize_aspects(values: list[str], labels_in: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """把模型回填的 aspects 归一成维度 id，并带上展示名。"""
    aspects: list[str] = []
    labels: dict[str, str] = {}
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        aspect_id, aspect_label = _resolve_aspect(text)
        if aspect_id in aspects:
            continue
        aspects.append(aspect_id)
        labels[aspect_id] = str(labels_in.get(aspect_id) or labels_in.get(text) or aspect_label).strip()
    return aspects, labels


_BASIC_QUESTION_IDS = {"target_role", "city", "experience"}
_BASIC_QUESTION_HEADERS = {"目标岗位", "岗位", "求职城市", "城市", "工作年限", "年限"}


def _is_aspect_question(question: dict) -> bool:
    """区分第二轮「调研方面」和第一轮基本信息，避免把城市 / 年限当成维度。"""
    question_id = str(question.get("id") or "").strip().lower()
    header = str(question.get("header") or "").strip()
    if question_id in _BASIC_QUESTION_IDS or header in _BASIC_QUESTION_HEADERS:
        return False
    if question_id in {"aspects", "aspect", "focus", "research_focus"}:
        return True
    if bool(question.get("multiSelect")):
        return True
    text = f"{header} {question.get('question') or ''}"
    return "调研" in text


def _has_aspect_question(asked: list[dict]) -> bool:
    """本次反问里是否出现过「调研方面」这一轮。"""
    return any(
        _is_aspect_question(question)
        for item in asked
        for question in item.get("questions") or []
    )


def _collect_asked_aspects(asked: list[dict]) -> tuple[list[str], dict[str, str]]:
    """只从「调研方面」的答案里回收动态维度；多轮追问时以最后一次回答为准。

    第一轮的岗位 / 城市 / 年限只是 brief 字段，绝不能当成调研方面。

    模型经常先问「想重点调研哪些方面」，用户答得笼统（如「落地能力」），
    再追问「具体是哪个」，用户答「项目落地」。这两句是同一次选择的细化，
    累加会凭空多出一个维度，所以有答案的最后一轮覆盖前面几轮；
    某一轮整轮跳过（没有答案）时保留上一轮，不让空答案把有效选择清掉。
    """
    aspects: list[str] = []
    labels: dict[str, str] = {}
    for item in asked:
        aspect_questions = {
            str(question.get("id") or ""): question
            for question in item.get("questions") or []
            if _is_aspect_question(question)
        }
        if not aspect_questions:
            continue
        round_aspects: list[str] = []
        round_labels: dict[str, str] = {}
        for answer in item.get("answers") or []:
            answer_id = str(answer.get("id") or "")
            if answer_id and answer_id not in aspect_questions:
                continue
            values = [str(value).strip() for value in answer.get("selected") or [] if str(value).strip()]
            custom = str(answer.get("custom") or "").strip()
            if custom:
                values.append(custom)
            for value in values:
                label = value.split("｜", 1)[0].strip()
                if not label:
                    continue
                aspect_id, aspect_label = _resolve_aspect(label)
                if aspect_id in round_aspects or aspect_id in FIXED_DIMS:
                    continue
                round_aspects.append(aspect_id)
                round_labels[aspect_id] = aspect_label
        if round_aspects:
            aspects, labels = round_aspects, round_labels
    return aspects, labels


def _reconcile_aspects(
    picked_aspects: list[str],
    picked_labels: dict[str, str],
    model_labels: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """以用户实际选择为准，尽量沿用模型给这些方向生成的英文 id。"""
    by_label = {
        str(label).strip(): aspect_id
        for aspect_id, label in model_labels.items()
        if str(label).strip()
    }
    aspects: list[str] = []
    labels: dict[str, str] = {}
    for picked_id in picked_aspects:
        label = picked_labels.get(picked_id) or picked_id
        aspect_id = by_label.get(label) or picked_id
        if aspect_id in aspects:
            continue
        aspects.append(aspect_id)
        labels[aspect_id] = label
    return aspects, labels


async def _ask_aspects(
    brief: Brief,
    task: MarketTask | None,
    writer,
) -> tuple[list[str], dict[str, str]]:
    """补问调研方面：模型漏问、或把三题并轮且用户跳过了这一题时都会走到这里。

    用户填写的 `direction` 是希望 AI 回答的问题；选项只是示例方面，用户点「其他」
    写的内容同样有效。问题文案必须带上用户的问题，避免兜底路径把方向丢掉。
    仍没有答案时返回空，由调用方决定是否结束本轮。
    """
    options = tuple(label for label, _ in ASPECT_HINTS)
    question = "除了岗位和技术栈，还想重点调研哪些方面？"
    direction = (brief.direction or "").strip()
    if direction:
        question = f"你希望 AI 回答：{direction}\n\n为了把这个问题答全，还想重点调研哪些方面？"
    payload = {
        "title": "选择调研重点",
        "questions": [
            _question(
                "aspects",
                "调研方面",
                question,
                options,
                multi=True,
            )
        ],
    }
    answers = await _ask_user(task, payload, writer)
    aspect_answer = next((item for item in answers if str(item.get("id")) == "aspects"), None)
    if not aspect_answer:
        return [], {}

    values: list[str] = [str(item).strip() for item in aspect_answer.get("selected") or [] if str(item).strip()]
    custom = str(aspect_answer.get("custom") or "").strip()
    if custom:
        values.append(custom)
    return _normalize_aspects([value.split("｜", 1)[0] for value in values], {})


def _merge_brief(brief: Brief, patch: dict | None) -> Brief:
    if not patch:
        return brief
    updates = {
        key: str(patch.get(key) or "").strip()
        for key in ("target_role", "city", "experience", "time_window")
        if str(patch.get(key) or "").strip()
    }
    if "time_window" in updates:
        updates["time_window"] = time_window_label(updates["time_window"])
        # 时间窗口改了就同步换算出绝对年月，模型始终拿到算好的区间。
        date_range = time_window_range(updates["time_window"])
        if date_range:
            updates["date_range"] = date_range
    return brief.model_copy(update=updates) if updates else brief


def _normalize_groups(raw_groups: list[dict], brief: Brief, dims: list[str]) -> list[dict]:
    """保证每个维度都有一组、每组 2~6 条去重后的检索词；缺组用兜底。"""
    fallback = {item["id"]: item for item in fallback_groups(brief, dims)}
    by_id: dict[str, dict] = {}
    for group in raw_groups or []:
        group_id = str(group.get("id") or "")
        if group_id not in dims:
            continue
        queries = [str(q).strip() for q in group.get("queries") or [] if str(q).strip()]
        # 只有招聘维度允许带城市；其他维度去掉城市名，避免把全国口径的搜索收窄成同城。
        if group_id != "jobs":
            queries = [strip_city(query, brief.city) for query in queries]
            queries = [query for query in queries if query]
        if not queries:
            continue
        deduped: list[str] = []
        for query in queries:
            if query not in deduped:
                deduped.append(query)
        by_id[group_id] = {
            "id": group_id,
            "label": str(group.get("label") or dim_label(group_id, brief.aspect_labels)),
            "queries": deduped[:DIM_MAX_QUERIES],
        }

    result: list[dict] = []
    for dim in dims:
        # 记录这组词是谁出的：模型生成 or 代码兜底，前端按它打标。
        item = by_id.get(dim)
        source = "ai" if item else "fallback"
        item = item or fallback[dim]
        result.append(
            {
                "id": dim,
                "label": dim_label(dim, brief.aspect_labels),
                "queries": [str(q).strip() for q in item["queries"]][:DIM_MAX_QUERIES],
                "source": source,
            }
        )
    return result


def _message(brief: Brief) -> str:
    fixed = [{"id": dim, "label": dim_label(dim, brief.aspect_labels)} for dim in FIXED_DIMS]
    samples = [{"label": label, "hint": desc} for label, desc in ASPECT_HINTS]
    if (brief.direction or "").strip():
        instruction = (
            "请先按系统提示完成两轮反问：用户已写明希望 AI 回答的内容，第二轮「调研方面」的选项要围绕它生成，"
            "但方面仍由用户选择。再为固定维度和用户选择的每个方面各生成一组检索词；"
            "每个维度的检索词都必须覆盖该问题，不能只生成与问题无关的通用岗位检索词。"
        )
    else:
        instruction = "请先按系统提示完成两轮反问，再为固定维度和用户选择的每个方面各生成一组检索词。"
    return (
        "<brief>\n"
        f"{brief.model_dump_json(indent=2)}\n"
        "</brief>\n\n"
        "<fixed_dims>\n"
        f"{json.dumps(fixed, ensure_ascii=False, indent=2)}\n"
        "</fixed_dims>\n\n"
        "<aspect_samples>\n"
        f"{json.dumps(samples, ensure_ascii=False, indent=2)}\n"
        "</aspect_samples>\n\n"
        f"{instruction}"
    )


async def run(
    llm,
    brief: Brief,
    task: MarketTask | None = None,
    run_id: str | None = None,
) -> dict:
    """跑规划 agent，返回 {brief, groups, dims, notes}。

    用户没选调研重点时返回 {aborted: True, ...}，由 graph 结束本轮。
    """
    writer = safe_writer()
    writer({"type": "agent_start", "agent": "planner", "label": "规划 agent"})

    asked: list[dict] = []

    async def on_interrupt(payload: dict) -> dict:
        """模型调用 ask_user_question 时暂停，把答案作为 resume 值交还模型。"""
        payload = payload if isinstance(payload, dict) else {}
        answers = await _ask_user(task, payload, writer)
        # 同时保留问题结构：只有第二轮的「调研方面」答案能变成动态维度。
        asked.append({"questions": payload.get("questions") or [], "answers": answers})
        return {"answers": answers, "cancelled": not answers}

    agent = build_agent(llm)
    config = {
        "configurable": {
            "session_id": task.session_id if task else None,
            "thread_id": f"{run_id or uuid.uuid4().hex}:planner",
        }
    }

    structured = None
    try:
        structured = await run_structured(
            agent,
            _SYSTEM_PROMPT,
            _message(brief),
            config,
            on_interrupt=on_interrupt,
            stage="planner",
        )
    except Exception as exc:
        stage_exception("plan", "模型调用失败")
        writer({"type": "error", "node": "planner", "message": str(exc), "fatal": False})

    aspects: list[str] = []
    aspect_labels: dict[str, str] = {}
    model_aspect_labels: dict[str, str] = {}
    raw_groups: list[dict] = []
    notes = "计划生成失败，使用默认检索"

    if structured is not None:
        try:
            plan = PlanResult.model_validate(structured)
        except Exception as exc:
            stage_warning("plan", "结果校验失败，改用兜底检索词", error=exc)
            writer({"type": "status", "stage": "planner", "text": "计划生成失败，已使用默认检索词"})
        else:
            brief = _merge_brief(brief, plan.brief.model_dump())
            # 模型给的 aspects 只用于把用户选择映射成英文 id；能不能保留以第二轮答案为准。
            _, model_aspect_labels = _normalize_aspects(plan.aspects, plan.aspect_labels)
            raw_groups = [group.model_dump() for group in plan.groups]
            notes = plan.notes
    else:
        writer({"type": "status", "stage": "planner", "text": "计划生成失败，已使用默认检索词"})

    # 动态维度只能来自第二轮用户实际选择；整轮跳过时保持为空。
    aspect_asked = _has_aspect_question(asked)
    if aspect_asked:
        picked_aspects, picked_labels = _collect_asked_aspects(asked)
        aspects, aspect_labels = _reconcile_aspects(
            picked_aspects, picked_labels, model_aspect_labels
        )

    # 硬约束：模型漏问第一轮时由代码补齐；调研方面必须单独拿到答案。
    if task is not None and not asked:
        brief = await _ask_missing(brief, task, writer)
    if task is not None and not aspects:
        # 模型可能把三题并进同一轮，用户跳过调研方面时 aspect_asked 仍为真，
        # 这里必须再单独问一次，不能直接拿城市 / 年限生成检索计划。
        aspects, aspect_labels = await _ask_aspects(brief, task, writer)

    # 调研方面是唯一的调研触发条件；补问后仍为空就结束本轮，不进入采集。
    if task is not None and not aspects:
        writer({"type": "status", "stage": "planner", "text": _NO_ASPECT_REASON})
        writer({"type": "agent_end", "agent": "planner", "label": "规划 agent"})
        return {
            "aborted": True,
            "brief": brief.model_dump(),
            "groups": [],
            "dims": [],
            "notes": _NO_ASPECT_REASON,
        }

    brief = brief.model_copy(update={"aspects": aspects, "aspect_labels": aspect_labels})
    dims = dim_ids(brief)
    groups = _normalize_groups(raw_groups, brief, dims)

    labels = " / ".join(group["label"] for group in groups)
    # 报告目录跟随本次调研方面，章节数不固定，按实际目录播报。
    chapters = report_sections(brief)
    chapter_titles = " / ".join(title for _, title in chapters)
    window = brief.time_window or "时间不限"
    if brief.date_range:
        window = f"{window}（{brief.date_range}）"
    steps = [
        {
            "key": "采集",
            "text": f"{len(groups)} 个维度 · {sum(len(g['queries']) for g in groups)} 条关键词检索 · {window}",
        },
        {"key": "抽取", "text": f"并行 {len(groups)} 个 agent：{labels}"},
        {"key": "汇总", "text": f"{len(chapters)} 章报告：{chapter_titles}，每章标注来源"},
        {
            "key": "分支",
            "text": "规划完成后，简历画像与采集并行"
            if brief.has_resume
            else f"未提供简历，跳过简历对照，报告共 {len(chapters)} 章",
        },
    ]
    for index, step in enumerate(steps, start=1):
        writer({"type": "plan.step", "index": index, "key": step["key"], "text": step["text"]})

    writer(plan_result_event(groups, brief, notes))
    writer({"type": "agent_end", "agent": "planner", "label": "规划 agent"})
    return {"brief": brief.model_dump(), "groups": groups, "dims": dims, "notes": notes}


def plan_queries(groups: list[dict]) -> list[dict]:
    """把分组检索词拍平成前端逐条落下的清单；kind / label / source 供前端分组展示。"""
    return [
        {
            "q": query,
            "kind": group["id"],
            "label": group["label"],
            "source": group.get("source", "ai"),
        }
        for group in groups
        for query in group["queries"]
    ]


def plan_result_event(groups: list[dict], brief: Brief, notes: str) -> dict:
    """统一的 plan.result 事件；planner 失败走兜底时也要发，前端才能解锁后续节点。"""
    return {
        "type": "plan.result",
        "queries": plan_queries(groups),
        "dims": [{"id": group["id"], "label": group["label"]} for group in groups],
        "budget": {
            "groups": len(groups),
            "maxQueriesPerGroup": DIM_MAX_QUERIES,
            "timeWindow": brief.time_window,
            "dateRange": brief.date_range,
        },
        "notes": notes,
        "brief": brief.model_dump(),
    }
