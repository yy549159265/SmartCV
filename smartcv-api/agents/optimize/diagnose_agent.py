"""诊断 agent：结合简历文本（带位置编号）、可选 JD 和用户问题，输出诊断结论。

信息不足时，agent 会调用 ask_user_question 工具反问：
  - 工具内部 interrupt() 暂停诊断（状态存进 graph 的 checkpointer）；
  - 本模块把问题经 custom 流推给前端，并等待 /api/chat/answer 提交的答案；
  - 拿到答案后用 Command(resume=...) 继续同一个诊断 agent，最后输出诊断结论。

所有事件（agent_start / 逐 token delta / agent_end / ask_question）都经
get_stream_writer() 发成 LangGraph custom 事件，由外层 optimize_graph 转发成 SSE。
"""

import asyncio
import logging
import uuid
from pathlib import Path

from langchain.agents import create_agent
from langgraph.config import get_stream_writer
from langgraph.types import Command

from agents.optimize.schemas.diagnosis import DiagnosisResult
from agents.optimize.schemas.task import get_chat_task
from agents.optimize.utils.checkpointer import get_checkpointer
from agents.optimize.utils.tools import make_ask_tool
from agents.optimize.utils.web_search import make_web_search_tool
from agents.utils.skillmiddleware import SkillMiddleware

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_diagnose.md").read_text(encoding="utf-8")

# 等用户回答的最长时间：超时按「未作答」继续诊断，不让整条 SSE 流永远挂着。
# 必须小于 ChatTask 的 10 分钟 TTL，否则任务会先过期、答案接口先失效。
_ASK_TIMEOUT_SECONDS = 300


def build_agent(llm):

    return create_agent(
        model=llm,
        middleware=[SkillMiddleware(["diagnose", "coordinate"])],
        # web_search 只给诊断 agent：优化/摘要不联网，避免网络内容污染简历事实
        tools=[make_ask_tool(), make_web_search_tool()],
        # 诊断结果按实体类输出：位置 + 原因 + 依据 + 方向，不再是一段自由文本
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
        # 没有会话任务（前端没带会话 id / 任务已过期）：不提问，直接让模型继续
        writer({"type": "tool_call", "tool": "ask_user_question", "args": meta})
        writer({"type": "tool_result", "tool": "ask_user_question", "result": "当前会话不可用，跳过提问"})
        return {"answers": [], "cancelled": True}

    # 先登记 future 再发事件：避免极快的前端提交撞上「问题还不存在」
    future = task.open_question(question_id)
    writer({"type": "tool_call", "tool": "ask_user_question", "args": meta})
    # timeoutSeconds 给前端做倒计时（后端从 wait_for 开始计时，和下发时间基本一致）
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
        result.append(item if isinstance(item, dict) else item.model_dump())
    return result


async def run(llm, markdown: str, jd: str, question: str, session_id: str | None = None) -> list[dict]:
    """跑诊断 agent：发 agent_start → 思考流式 delta → diagnosis 事件 → agent_end。

    返回结构化诊断项列表；每项含位置、原文片段、原因、依据和修改方向。
    """
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "diagnose", "label": "诊断 agent"})
    # 把带位置编号的简历文本原样下发：前端「位置诊断」折叠行展开即可看到 agent 的输入
    writer({"type": "resume_markdown", "text": markdown})
    agent = build_agent(llm)

    # 输入按类型分块，每块用 <> 标签包裹（system_prompt_diagnose.md 有对应说明）
    jd_block = f"<JD>\n{jd}\n</JD>\n\n" if (jd or "").strip() else ""
    message = (
        f"<简历>\n{markdown}\n</简历>\n\n"
        f"{jd_block}"
        f"<修改要求>\n{question}\n</修改要求>"
    )

    # 每次诊断用独立 thread：互不串状态；checkpointer 统一由 main.py 的 lifespan 打开
    config = {
        "recursion_limit": 25,
        "configurable": {
            "session_id": session_id,
            "thread_id": f"{session_id or 'anon'}:diagnose:{uuid.uuid4().hex}",
        },
    }
    payload = {
        "messages": [
            {"type": "system", "content": _SYSTEM_PROMPT},
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

            # 中断信息在 updates 流里：{'__interrupt__': (Interrupt(value=...),)}
            if mode == "updates":
                if isinstance(chunk, dict) and chunk.get("__interrupt__"):
                    interrupt_value = chunk["__interrupt__"][0].value
                    continue
                # 结构化输出挂在模型节点的返回值上：{节点名: {"structured_response": ...}}
                if isinstance(chunk, dict):
                    for value in chunk.values():
                        if isinstance(value, dict) and value.get("structured_response") is not None:
                            structured = value["structured_response"]
                continue

            if mode != "messages":
                continue

            # messages 流里推的是 AIMessageChunk（type == "AIMessageChunk"），
            # 不是 AIMessage（type == "ai"）；只认 "ai" 会把所有流式 token 全丢掉。
            # 同时这里还有 ToolMessage/工具 chunk，不能把它们当诊断正文。
            msg = chunk[0]
            if getattr(msg, "type", "") not in ("ai", "AIMessageChunk"):
                continue

            # 只转发思考过程。结构化结果（JSON / 工具参数）不推给前端，
            # 诊断内容在跑完后以 diagnosis 事件一次性下发。
            kwargs = getattr(msg, "additional_kwargs", {}) or {}
            thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
            if thinking:
                writer({"type": "delta", "stage": "diagnose", "text": thinking, "kind": "thinking"})

        if interrupt_value is None:
            break

        answers = await _ask_user(session_id, interrupt_value, writer)
        payload = Command(resume=answers)

    # updates 里没拿到（例如模型没走结构化输出）时，从最终状态兜底
    if structured is None:
        snapshot = await agent.aget_state(config)
        structured = (snapshot.values or {}).get("structured_response")

    items = _diagnosis_items(structured)
    if not items:
        logger.warning("diagnose-agent 没有返回结构化诊断结果")
    writer({"type": "diagnosis", "count": len(items), "items": items})
    writer({"type": "agent_end", "agent": "diagnose", "label": "诊断 agent"})
    logger.info("diagnose-agent 输出 %d 条诊断", len(items))
    return items
