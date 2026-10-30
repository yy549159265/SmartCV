"""优化对话流水线：LangGraph 编排 + SSE 流式入口。

流转过程（每个 agent 是独立模块，见 diagnose_agent / optimize_agent / summarize_agent）：

  convert    （代码）    把前端 Section[] 拍平成「每行带位置编号」的标记文本
  diagnose   （诊断 agent）标记文本 + JD(可选) + 用户问题 → 结构化诊断项
             （位置 / 原文片段 / 原因 / 依据 / 修改方向）
  optimize   （优化 agent）标记文本 + 诊断 → 先 review_diagnosis 逐条审查，再对通过项
            调用 patch_content(index, text) 就地替换文字；JSON 结构/样式/图片不被破坏
  summarize  （主 agent）诊断 + 改动清单 → 给用户的简短修改说明（逐 token 流式）

事件通道：图内所有事件（status / agent_start / delta / tool_call / tool_result /
agent_end）都经 get_stream_writer() 发成 LangGraph custom 事件，本模块用
astream(stream_mode=["updates","custom"]) 统一收取并转发成 SSE（单一生产者，
事件顺序与图内执行一致）。最终改好的 resume JSON + summary + diagnosis 发成
resume 事件，前端据此重绘。

图用 SQLite checkpointer（thread_id = agent 会话 id）编译，状态持久化到 sqlite。
"""

import logging
import uuid
from typing import Annotated, Callable, Awaitable

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.config import get_stream_writer
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agents.optimize import diagnose_agent, optimize_agent, summarize_agent
from agents.optimize.utils.checkpointer import get_checkpointer
from agents.optimize.utils.markdown import describe_location, resume_to_markdown
from agents.optimize.utils.tools import OptimizeStore
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")


def _last_summary(messages: list[AnyMessage] | None) -> str:
    """取最近一条 AI 消息的正文，也就是上一轮的 summary；没有就返回空串。"""
    for message in reversed(messages or []):
        if isinstance(message, AIMessage):
            return (message.content or "").strip()
    return ""


class ChatState(TypedDict):
    # 跨轮上下文：每轮的「用户问题」和「总结」按序追加（add_messages），不覆盖
    messages: Annotated[list[AnyMessage], add_messages]
    resume_sections: list[dict]
    markdown: str
    # 结构化诊断项：位置 + 原文片段 + 原因 + 依据 + 修改方向
    diagnosis: list[dict]
    summary: str
    result_json: list[dict]


async def run_chat_stream(
    provider: ProviderConfig,
    resume_sections: list[dict],
    jd: str,
    question: str,
    emit: Callable[[dict], Awaitable[None]],
    session_id: str | None = None,
    llm=None,
) -> dict:
    """跑完整条流水线；所有事件经 emit 发出去，返回最终 {resume, summary, diagnosis}。

    llm 参数仅供测试注入（None 时用 choose_llm(provider) 构造）。
    """
    if not resume_sections:
        await emit({"type": "error", "message": "简历是空的，请先在「编辑简历」页添加内容"})
        return {"resume": resume_sections, "summary": "", "diagnosis": []}

    llm = llm or choose_llm(provider)
    # 浅拷贝一层：优化 agent 的 patch 工具在这个副本上就地改，不污染上层入参
    store = OptimizeStore([dict(s) for s in resume_sections])

    async def convert_node(state: ChatState) -> dict:
        # convert 是纯代码阶段（非 agent），也发 status 事件让前端展示「正在解析 → 完成」
        writer = get_stream_writer()
        writer({"type": "status", "stage": "convert", "text": "正在解析 JSON 简历，转换为带位置文本…"})
        markdown = resume_to_markdown(store.resume)
        writer({"type": "status", "stage": "convert", "text": "已完成位置标记，准备诊断"})
        return {"markdown": markdown}

    async def diagnose_node(state: ChatState) -> dict:
        # 上一轮的总结（改了/没改哪些位置）作为本轮诊断的上下文
        history = _last_summary(state.get("messages"))
        diagnosis = await diagnose_agent.run(
            llm, state["markdown"], jd, question, session_id, history
        )
        return {"diagnosis": diagnosis}

    async def optimize_node(state: ChatState) -> dict:
        await optimize_agent.run(
            llm, store, state["markdown"], jd, state["diagnosis"], question, session_id
        )
        return {"result_json": store.resume}

    async def summarize_node(state: ChatState) -> dict:
        locations = [describe_location(store.resume, item) for item in state["diagnosis"]]
        summary = await summarize_agent.run(
            llm, state["diagnosis"], store.patches, store.reviews, locations, session_id
        )
        # summary 同时写进 messages，下一轮诊断从这里取
        return {"summary": summary, "messages": [AIMessage(content=summary)]}

    graph = StateGraph(ChatState)
    graph.add_node("convert", convert_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("optimize", optimize_node)
    graph.add_node("summarize", summarize_node)
    graph.add_edge(START, "convert")
    graph.add_edge("convert", "diagnose")
    graph.add_edge("diagnose", "optimize")
    graph.add_edge("optimize", "summarize")
    graph.add_edge("summarize", END)
    compiled = graph.compile(checkpointer=get_checkpointer())

    state: ChatState = {
        # add_messages 会把本次问题追加到同一 thread 的历史后面，而不是覆盖
        "messages": [HumanMessage(content=question)],
        "resume_sections": resume_sections,
        "markdown": "",
        "diagnosis": [],
        "summary": "",
        "result_json": resume_sections,
    }
    config = {"configurable": {"thread_id": session_id or uuid.uuid4().hex}}
    async for mode, chunk in compiled.astream(state, stream_mode=["updates", "custom"], config=config):
        if mode == "custom":
            await emit(chunk)
        else:
            # updates 是 {node: patch}，把每个节点产出的字段展开合并进 state
            for node_update in chunk.values():
                state.update(node_update)

    result = {
        "resume": store.resume,
        "summary": state.get("summary") or "",
        "diagnosis": state.get("diagnosis") or [],
    }
    await emit({"type": "resume", **result})
    await emit({"type": "done"})
    logger.info(
        "chat 完成：%d 处修改，%d 个章节",
        len(store.patches),
        len(store.resume),
    )
    return result