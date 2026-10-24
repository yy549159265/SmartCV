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

from agents.optimize.schemas.task import get_chat_task
from agents.optimize.utils.checkpointer import get_checkpointer
from agents.optimize.utils.tools import make_ask_tool
from agents.utils.skillmiddleware import SkillMiddleware

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_diagnose.md").read_text(encoding="utf-8")

# 等用户回答的最长时间：超时按「未作答」继续诊断，不让整条 SSE 流永远挂着。
# 必须小于 ChatTask 的 10 分钟 TTL，否则任务会先过期、答案接口先失效。
_ASK_TIMEOUT_SECONDS = 300


def build_agent(llm):
    """诊断 agent：挂反问卷工具，并挂 checkpointer（interrupt 恢复必需）。

    注意：这里的 checkpointer 不能省。诊断 agent 是在 diagnose_node 里用
    `agent.astream()` 单独跑的一次图执行，并不是外层图的 subgraph 节点，
    外层图的 checkpointer 不会自动传给这次独立运行。去掉它以后，
    interrupt 之后执行 `Command(resume=...)` 会直接报
    "Cannot use Command(resume=...) without checkpointer"。
    """
    return create_agent(
        model=llm,
        middleware=[SkillMiddleware(["diagnose"])],
        tools=[make_ask_tool()],
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


async def run(llm, markdown: str, jd: str, question: str, session_id: str | None = None) -> str:
    """跑诊断 agent：发 agent_start → 逐 token 发 delta(diagnose) → agent_end，返回整段诊断。"""
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": "diagnose", "label": "诊断 agent"})
    agent = build_agent(llm)

    jd_text = f"\n\n职位描述（JD）：\n{jd}" if (jd or "").strip() else ""
    message = (
        f"简历内容（Markdown，行首 [s:章节 r:窗口 c:内容 i:子项] 是位置编号，请忽略）：\n{markdown}\n"
        f"{jd_text}\n"
        f"\n用户的修改要求：\n{question}"
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

    parts: list[str] = []
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

            if mode != "messages":
                continue

            # messages 流里推的是 AIMessageChunk（type == "AIMessageChunk"），
            # 不是 AIMessage（type == "ai"）；只认 "ai" 会把所有流式 token 全丢掉。
            # 同时这里还有 ToolMessage/工具 chunk，不能把它们当诊断正文。
            msg = chunk[0]
            if getattr(msg, "type", "") not in ("ai", "AIMessageChunk"):
                continue

            # 推理模型把思考放 reasoning_content、答案放 content；两者分开打 kind 发给前端，
            # 前端据此分成「思考过程」和「回答」两块（每个 agent 都可能两者都有）。
            kwargs = getattr(msg, "additional_kwargs", {}) or {}
            thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
            content = getattr(msg, "content", "") or ""
            if thinking:
                parts.append(thinking)
                writer({"type": "delta", "stage": "diagnose", "text": thinking, "kind": "thinking"})
            if content:
                parts.append(content)
                writer({"type": "delta", "stage": "diagnose", "text": content, "kind": "answer"})

        if interrupt_value is None:
            break

        # 提问前模型的铺垫（"我需要先确认…"）不算诊断结论；清空后只保留
        # 拿到答案之后生成的最终诊断，避免被 optimize agent 当成依据。
        parts.clear()
        answers = await _ask_user(session_id, interrupt_value, writer)
        payload = Command(resume=answers)

    diagnosis = "".join(parts).strip()
    writer({"type": "agent_end", "agent": "diagnose", "label": "诊断 agent"})
    logger.info("diagnose-agent 输出 %d 字", len(diagnosis))
    return diagnosis
