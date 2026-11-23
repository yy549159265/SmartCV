"""Agent 运行器：统一处理 astream 事件、interrupt 恢复、结构化结果提取。

各 agent 只负责 build_agent / 提示词 / 业务归一化；这里负责和 LangGraph 的交互，
避免每个 agent 重复写一遍 messages / custom / updates 的循环。
"""

import json
import re
import time
from typing import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.utils.json import parse_partial_json
from langgraph.config import get_stream_writer
from langgraph.types import Command

from agents.resume.marker.utils.stage_log import DEFAULT_SCOPE, stage_info, stage_warning

InterruptHandler = Callable[[dict], Awaitable[dict]]


class DropInvalidToolCallsMiddleware(AgentMiddleware):
    """移除只有无效 tool_call 的 AI 消息，避免模型重试时把坏调用发回接口。

    DeepSeek 偶尔会生成解析不了的 tool_call 参数（JSON 语法错误）。没有客户端
    工具时，create_agent 会拿同一段历史重试；langchain-openai 会把
    invalid_tool_calls 一并序列化成 tool_calls 发回去，却没有对应的 tool 消息，
    接口直接 400「must be followed by tool messages」。请求前把这些消息摘掉，
    重试就从干净历史开始。
    """

    # 模型连着几次都给出解析不了的参数时别再无限重试，直接失败让上层走兜底。
    _MAX_RETRIES = 3

    def __init__(self, scope: str = DEFAULT_SCOPE) -> None:
        super().__init__()
        self._retries = 0
        self._scope = scope

    def _clean(self, request):
        kept = []
        dropped = 0
        for message in request.messages:
            if not isinstance(message, AIMessage) or not message.invalid_tool_calls:
                kept.append(message)
                continue
            content = message.content
            has_text = bool(content.strip()) if isinstance(content, str) else bool(content)
            if message.tool_calls or has_text:
                kept.append(message.model_copy(update={"invalid_tool_calls": []}))
            else:
                dropped += 1
                for call in message.invalid_tool_calls:
                    raw_args = call.get("args")
                    stage_warning(
                        "runner",
                        "丢弃无法解析的 tool_call",
                        scope=self._scope,
                        name=call.get("name") or "-",
                        chars=len(raw_args) if isinstance(raw_args, str) else 0,
                        # LangChain 在流式路径里固定把 error 置空，光看它排不出原因，
                        # 因此带上参数尾部：多余括号 / 截断 / 未转义引号都能直接认出来。
                        tail=repr(raw_args[-120:]) if isinstance(raw_args, str) else "-",
                    )
        if dropped:
            self._retries += 1
            if self._retries > self._MAX_RETRIES:
                raise RuntimeError("模型连续多次输出的结构化 tool_call 参数无法解析，已停止重试")
        else:
            self._retries = 0
        return request.override(messages=kept)

    def wrap_model_call(self, request, handler):
        return handler(self._clean(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._clean(request))


def safe_writer() -> Callable[[dict], None]:
    """取当前图的 custom 写入口；不在图里（单测/脚本）时退化成空函数。"""
    try:
        return get_stream_writer()
    except Exception:
        return lambda _event: None


def to_dict(value: object) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return None


def _messages(system_prompt: str, user_message: str) -> dict:
    return {
        "messages": [
            {"type": "system", "content": system_prompt},
            {"type": "human", "content": user_message},
        ]
    }


def _extract_structured(chunk: dict) -> object | None:
    if chunk.get("structured_response") is not None:
        return chunk["structured_response"]
    for value in chunk.values():
        if isinstance(value, dict) and value.get("structured_response") is not None:
            return value["structured_response"]
    return None


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# 结构化输出失败、重试一次时给模型的纠正说明。
_RETRY_HINT = (
    "你上一次的结构化输出参数不是合法 JSON。请重新调用结构化输出工具，"
    "只输出符合 schema 的参数；字符串里的换行必须转义为 \\n，不要输出工具之外的内容。"
)


def _json_candidates(raw: str) -> list[str]:
    """原文本身 + 最外层花括号包住的那一段（模型前后常带解释文字）。"""
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        return [raw, raw[start : end + 1]]
    return [raw]


def _decode_first_value(candidate: str) -> object | None:
    """先只吃第一个完整 JSON 值，失败再按「可能被截断」补全尾部。

    DeepSeek 偶尔在参数末尾多吐一个 `}`（`{...}}`），json.loads 判成
    Extra data 整条丢弃；raw_decode 只解析到第一个对象结束，正好绕过这种尾巴。
    截断的参数 raw_decode 会失败，再用 parse_partial_json 补齐未闭合的括号。
    """
    start = candidate.find("{")
    if start < 0:
        return None
    body = candidate[start:]
    try:
        return json.JSONDecoder(strict=False).raw_decode(body)[0]
    except (json.JSONDecodeError, ValueError):
        return parse_partial_json(body)


def _loads_json(text: str) -> dict | None:
    """解析模型原文里的 JSON；容忍代码块、前后说明、未转义换行和多余尾括号。

    strict=False 是关键：DeepSeek 把长文本写进参数时经常把换行原样塞进
    JSON 字符串，默认的严格解析会直接判成语法错误。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    for candidate in _json_candidates(raw):
        try:
            value = json.loads(candidate, strict=False)
        except (json.JSONDecodeError, ValueError):
            value = _decode_first_value(candidate)
        if isinstance(value, dict):
            return value
    return None


def _message_text(message) -> str:
    content = getattr(message, "content", "")
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
    return str(content or "")


def _last_ai_message(values: dict):
    for message in reversed(values.get("messages") or []):
        if getattr(message, "type", "") == "ai":
            return message
    return None


def _recover_structured(values: dict) -> dict | None:
    """structured_response 缺失时，从模型最后一条输出里捞回原始 JSON。

    模型有时不调用结构化输出工具，而是按提示词直接吐出 JSON 正文；
    这时状态里没有 structured_response，但正文往往是一份完整 JSON。
    """
    message = _last_ai_message(values)
    if message is None:
        return None
    parsed = _loads_json(_message_text(message))
    if parsed is not None:
        return parsed
    # 工具调用参数被解析成 invalid 时，原始参数串里有时仍是完整 JSON。
    for call in getattr(message, "invalid_tool_calls", []) or []:
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            parsed = _loads_json(args)
            if parsed is not None:
                return parsed
    return None


def _log_missing_structured(stage: str, values: dict, scope: str) -> None:
    """结构化结果缺失时打出模型尾部输出，便于判断是截断还是格式不符。"""
    messages = values.get("messages") or []
    message = _last_ai_message(values)
    if message is None:
        stage_warning(stage, "缺少结构化结果", scope=scope, messages=len(messages))
        return
    meta = getattr(message, "response_metadata", {}) or {}
    text = _message_text(message)
    invalid = getattr(message, "invalid_tool_calls", []) or []
    stage_warning(
        stage,
        "缺少结构化结果",
        scope=scope,
        finish_reason=meta.get("finish_reason") or meta.get("stop_reason") or "-",
        chars=len(text),
        invalid_calls=len(invalid),
        tail=repr(text[-200:]),
    )


async def run_structured(
    agent,
    system_prompt: str,
    user_message: str,
    config: dict | None = None,
    *,
    on_interrupt: InterruptHandler | None = None,
    stage: str = "agent",
    scope: str = DEFAULT_SCOPE,
) -> dict | None:
    """跑结构化 agent，返回 model_dump 后的 dict。

    agent 也可以是 `llm.with_structured_output(...)` 的普通 runnable：它没有
    LangGraph 状态和 interrupt，直接 ainvoke 一次即可。
    on_interrupt 用于需要反问的图 agent（planner）：收到 interrupt 后由它负责
    发 `ask_question`、等前端答案，返回 `Command(resume=...)` 要用的值。
    scope 是日志里的业务域，模拟面试等非市场调研流程必须显式传入。
    """
    if not hasattr(agent, "aget_state"):
        started = time.perf_counter()
        stage_info(stage, "模型调用开始", scope=scope, input_chars=len(user_message))
        structured = await agent.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_message)],
            config=config,
        )
        stage_info(
            stage,
            "模型调用结束",
            scope=scope,
            elapsed=f"{time.perf_counter() - started:.2f}s",
            structured=structured is not None,
        )
        return to_dict(structured)

    writer = safe_writer()
    payload: dict | Command = _messages(system_prompt, user_message)
    structured: object | None = None
    retried = False
    attempt = 0

    while True:
        attempt += 1
        interrupt_value = None
        started = time.perf_counter()
        stage_info(
            stage,
            "模型调用开始",
            scope=scope,
            attempt=attempt,
            input_chars=len(user_message) if attempt == 1 else len(_RETRY_HINT),
        )
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

            if mode == "updates" and isinstance(chunk, dict):
                if chunk.get("__interrupt__"):
                    interrupt_value = chunk["__interrupt__"][0].value
                    continue
                found = _extract_structured(chunk)
                if found is not None:
                    structured = found
                continue

            if mode != "messages":
                continue

            msg = chunk[0]
            if getattr(msg, "type", "") not in ("ai", "AIMessageChunk"):
                continue
            kwargs = getattr(msg, "additional_kwargs", {}) or {}
            thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
            if thinking:
                writer({"type": "delta", "stage": stage, "text": thinking, "kind": "thinking"})

        stage_info(
            stage,
            "模型调用结束",
            scope=scope,
            attempt=attempt,
            elapsed=f"{time.perf_counter() - started:.2f}s",
            structured=structured is not None,
            interrupt=interrupt_value is not None,
        )

        if interrupt_value is None:
            if structured is None and not retried:
                values = (await agent.aget_state(config)).values or {}
                structured = values.get("structured_response") or _recover_structured(values)
                if structured is not None and values.get("structured_response") is None:
                    stage_info(stage, "结构化结果已恢复", scope=scope, source="模型输出")
                message = _last_ai_message(values)
                # 参数坏到连恢复都做不了，就让模型按纠正说明重试一次；
                # 中间件会在下一次模型调用前把这条无效消息摘掉。
                if structured is None and getattr(message, "invalid_tool_calls", None):
                    retried = True
                    stage_warning(stage, "结构化参数无法解析，重试一次", scope=scope)
                    payload = {"messages": [{"type": "human", "content": _RETRY_HINT}]}
                    continue
            break

        if on_interrupt is None:
            stage_warning(stage, "收到 interrupt 但没有处理器，按跳过处理", scope=scope)
            payload = Command(resume={"answers": [], "cancelled": True})
            continue
        payload = Command(resume=await on_interrupt(interrupt_value))

    if structured is None:
        snapshot = await agent.aget_state(config)
        values = snapshot.values or {}
        structured = values.get("structured_response")
        if structured is None:
            structured = _recover_structured(values)
            if structured is not None:
                stage_info(stage, "结构化结果已恢复", scope=scope, source="模型正文")
            else:
                _log_missing_structured(stage, values, scope)

    return to_dict(structured)


async def run_stream(
    agent,
    system_prompt: str,
    user_message: str,
    config: dict,
    *,
    stage: str = "compose",
    section: str | None = None,
) -> str:
    """跑流式 agent，逐 token 发 delta，返回完整正文。"""
    writer = safe_writer()
    parts: list[str] = []

    async for item in agent.astream(
        _messages(system_prompt, user_message),
        stream_mode=["messages", "custom"],
        config=config,
    ):
        if not isinstance(item, tuple):
            continue
        mode, chunk = item
        if mode == "custom":
            writer(chunk)
            continue

        msg = chunk[0]
        kwargs = getattr(msg, "additional_kwargs", {}) or {}
        thinking = kwargs.get("reasoning_content") or kwargs.get("reasoning") or ""
        content = getattr(msg, "content", "") or ""
        if thinking:
            writer({"type": "delta", "stage": stage, "text": thinking, "kind": "thinking", "section": section})
        if content:
            parts.append(content)
            writer({"type": "delta", "stage": stage, "text": content, "kind": "answer", "section": section})

    return "".join(parts).strip()
