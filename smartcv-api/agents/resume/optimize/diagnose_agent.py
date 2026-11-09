"""诊断 agent：结合简历文本（带位置编号）、可选 JD 和用户问题，输出诊断结论。

信息不足时，agent 会调用 ask_user_question 工具反问：
  - 工具内部 interrupt() 暂停诊断（状态存进 graph 的 checkpointer）；
  - 本模块把问题经 custom 流推给前端，并等待 /api/chat/answer 提交的答案；
  - 拿到答案后用 Command(resume=...) 继续同一个诊断 agent，最后输出诊断结论。

所有事件（agent_start / 逐 token delta / agent_end / ask_question）都经
get_stream_writer() 发成 LangGraph custom 事件，由外层 graph.py 转发成 SSE。
"""

import asyncio
import logging
import uuid
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer
from langgraph.types import Command

from agents.resume.optimize.schemas.diagnosis import DiagnosisResult
from agents.resume.optimize.utils.task import get_chat_task
from agents.resume.optimize.utils.checkpointer import get_checkpointer
from agents.resume.optimize.tools.ask_user import make_ask_tool
from agents.resume.optimize.tools.web_search import make_web_search_tool
from agents.utils.resume import describe_location_detail
from agents.utils.skillmiddleware import SkillMiddleware

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_diagnose.md").read_text(encoding="utf-8")

_REWRITE_MODE_RULES = {
    "standard": (
        "诊断按现有规则进行；`suggestion` 以「保留原句式、只做必要改写」为准，"
        "不要要求整段推倒重写。"
    ),
    "bold": (
        "可以在诊断中指出「表达平淡、句式与目标岗位差距大、信息组织松散」等问题，"
        "`suggestion` 可以要求大幅重写句式、句序和段落内表达，不必保留原句。"
        "但边界不变：不得建议新增或编造事实、数字、经历、技术栈，"
        "也不得建议增删章节 / 调整顺序 / 改动排版——这些改动本次无法执行，不要产出这类诊断。"
    ),
}


def _system_prompt(rewrite_mode: str) -> str:
    """把本次改写强度替换进系统提示词中间的 {rewrite_rules} 占位符。"""
    rewrite_rules = _REWRITE_MODE_RULES.get(
        rewrite_mode, _REWRITE_MODE_RULES["standard"]
    )

    return _SYSTEM_PROMPT.replace("{rewrite_rules}", rewrite_rules)


_ASK_TIMEOUT_SECONDS = 300


def build_agent(llm):

    return create_agent(
        model=llm,
        middleware=[SkillMiddleware(["diagnose", "coordinate"])],
        tools=[make_ask_tool(), make_web_search_tool()],
        response_format=DiagnosisResult,
        checkpointer=get_checkpointer(),
    )


async def _ask_user(session_id: str | None, payload: dict, writer) -> dict:
    """下发 ask_question 事件，等前端提交答案；返回 Command(resume=...) 的值。

    前端不可用 / 超时 / 跳过时返回 cancelled=True，让 agent 按现有信息继续诊断。
    """
    task = get_chat_task(session_id)
    question_id = uuid.uuid4().hex
    meta = {"title": payload.get("title", ""), "questions": len(payload.get("questions") or [])}

    if task is None:
        writer({"type": "tool_call", "tool": "ask_user_question", "args": meta})
        writer({"type": "tool_result", "tool": "ask_user_question", "result": "当前会话不可用，跳过提问"})
        return {"answers": [], "cancelled": True}

    future = task.open_question(question_id)
    writer({"type": "tool_call", "tool": "ask_user_question", "args": meta})
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
        return {"answers": answers, "cancelled": not answers}
    except asyncio.TimeoutError:
        writer({"type": "ask_question_closed", "questionId": question_id, "reason": "timeout"})
        writer({"type": "tool_result", "tool": "ask_user_question", "result": "等待回答超时，按现有信息继续诊断"})
        return {"answers": [], "cancelled": True}
    finally:
        task.clear_question(question_id)


def _diagnosis_items(structured) -> list[dict]:
    """把结构化结果规整成普通 dict 列表（兼容 checkpoint 反序列化出的 dict）。"""
    if structured is None:
        return []
    items = structured.get("items") if isinstance(structured, dict) else getattr(structured, "items", None)
    result: list[dict] = []
    for item in items or []:
        result.append(dict(item) if isinstance(item, dict) else item.model_dump())
    return _merge_same_coordinate(result)


_DISPOSITION_STRENGTH = {"must": 3, "suggest": 2, "insufficient": 1, "keep": 0}


def _stronger_disposition(a: str, b: str) -> str:
    """返回两条档位里更强（更该改）的那一个。缺省按 suggest 处理。"""
    return a if _DISPOSITION_STRENGTH.get(a, 2) >= _DISPOSITION_STRENGTH.get(b, 2) else b


def _merge_same_coordinate(items: list[dict]) -> list[dict]:
    """把指向同一个坐标的多条诊断合并成一条。

    一段文字只能被 patch_content 替换一次：两条诊断落在同一个 [s,r,c,i] 上时，
    第一条改完原文就变了，第二条核对原文必定失败，表现为「重复位置的那条诊断
    直接不执行」。这里按坐标合并，保留第一条的位置与原文片段（quote 必须与当前
    正文一致，不能换），把后面几条的原因 / 依据 / 方向补进同一条，避免丢诊断。

    坐标不全的诊断没有可比的位置，原样保留。
    """
    merged: dict[tuple, dict] = {}
    result: list[dict] = []

    for item in items:
        coords = tuple(item.get(key) for key in ("s", "r", "c", "i"))
        if any(value is None for value in coords):
            result.append(item)
            continue

        base = merged.get(coords)
        if base is None:
            merged[coords] = item
            result.append(item)
            continue

        logger.warning(
            "诊断项坐标重复 %s，已合并：%s", coords, str(item.get("suggestion") or "")[:40]
        )
        for field in ("reason", "evidence", "suggestion", "reference"):
            extra = str(item.get(field) or "").strip()
            if not extra:
                continue
            current = str(base.get(field) or "").strip()
            if extra in current:
                continue
            base[field] = f"{current}；{extra}" if current else extra
        base["disposition"] = _stronger_disposition(
            base.get("disposition") or "suggest", item.get("disposition") or "suggest"
        )

    return result


def _style_notes(structured) -> list[str]:
    """取诊断 agent 从优秀示例里提炼的写作规范（旧结果 / 没选示例时为空）。"""
    if structured is None:
        return []
    notes = (
        structured.get("style_notes")
        if isinstance(structured, dict)
        else getattr(structured, "style_notes", None)
    )
    return [str(note).strip() for note in (notes or []) if str(note).strip()]


async def run(
    llm,
    markdown: str,
    jd: str,
    question: str,
    session_id: str | None = None,
    history: str = "",
    references: str = "",
    reference_items: list[dict] | None = None,
    rewrite_mode: str = "standard",
    resume: list[dict] | None = None,
) -> tuple[list[dict], list[str]]:
    """跑诊断 agent：发 agent_start → 思考流式 delta → diagnosis 事件 → agent_end。

    返回 (结构化诊断项列表, 写作规范列表)。
    history 是上一轮的修改总结（可能为空），用于「重新生成 / 刚才那处」这类追问。
    references 是选中的优秀示例（纯结构 Markdown，不带位置编号）；reference_items
    只用来给前端展示「本次参考了哪几份」，不含正文。
    resume 传入时，给每条诊断附上结构化位置（section / location），前端按章节树状展示。
    """
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "diagnose", "label": "诊断 agent"})
    if reference_items:
        writer({"type": "reference_examples", "items": reference_items})
    writer({"type": "resume_markdown", "text": markdown})
    agent = build_agent(llm)

    jd_block = f"<JD>\n{jd}\n</JD>\n\n" if (jd or "").strip() else ""
    history_block = f"<上一轮>\n{history.strip()}\n</上一轮>\n\n" if (history or "").strip() else ""
    reference_block = (
        f"<优秀示例>\n{references.strip()}\n</优秀示例>\n\n" if (references or "").strip() else ""
    )
    message = (
        f"{history_block}"
        f"<简历>\n{markdown}\n</简历>\n\n"
        f"{jd_block}"
        f"{reference_block}"
        f"<修改要求>\n{question}\n</修改要求>"
    )

    config = {
        "configurable": {
            "session_id": session_id,
            "thread_id": f"{session_id or 'anon'}:diagnose:{uuid.uuid4().hex}",
        },
    }
    payload = {
        "messages": [
            {"type": "system", "content": _system_prompt(rewrite_mode)},
            {"type": "human", "content": message},
        ]
    }

    structured = None
    while True:
        interrupt_value = None
        async for item in agent.astream(
            payload,
            stream_mode=["messages", "custom", "updates"],
            config=config,
        ):
            if not isinstance(item, tuple):
                continue
            mode, chunk = item

            if mode == "custom":
                writer(chunk)
                continue

            if mode == "updates":
                if isinstance(chunk, dict) and chunk.get("__interrupt__"):
                    interrupt_value = chunk["__interrupt__"][0].value
                    continue
                if isinstance(chunk, dict):
                    for value in chunk.values():
                        if isinstance(value, dict) and value.get("structured_response") is not None:
                            structured = value["structured_response"]
                continue

            if mode != "messages":
                continue

            msg = chunk[0]
            if getattr(msg, "type", "") not in ("ai", "AIMessageChunk"):
                continue

            kwargs = getattr(msg, "additional_kwargs", {}) or {}
            thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
            if thinking:
                writer({"type": "delta", "stage": "diagnose", "text": thinking, "kind": "thinking"})

        if interrupt_value is None:
            break

        answers = await _ask_user(session_id, interrupt_value, writer)
        payload = Command(resume=answers)

    if structured is None:
        snapshot = await agent.aget_state(config)
        structured = (snapshot.values or {}).get("structured_response")

    items = _diagnosis_items(structured)
    style_notes = _style_notes(structured)
    if resume is not None:
        for item in items:
            detail = describe_location_detail(resume, item)
            item["section"] = detail["section"]
            item["sectionIndex"] = detail["sectionIndex"]
            item["location"] = detail["within"]
    if not items:
        logger.warning("diagnose-agent 没有返回结构化诊断结果")
    writer({"type": "diagnosis", "count": len(items), "items": items, "styleNotes": style_notes})
    writer({"type": "agent_end", "agent": "diagnose", "label": "诊断 agent"})
    logger.info("diagnose-agent 输出 %d 条诊断、%d 条写作规范", len(items), len(style_notes))
    return items, style_notes
