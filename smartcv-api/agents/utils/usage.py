"""LLM token 用量统计。

各 agent 不需要关心计数：入口用 `collect_usage()` 包一层，`choose_llm` 会把
当前上下文的计量器挂到 ChatOpenAI 的回调上，每次模型调用结束时累加
`usage_metadata`。并发分组（如问题包）共享同一个计量器，调用次数也会累计。

返回给前端统一用 camelCase：inputTokens / outputTokens / totalTokens / calls。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from langchain_core.callbacks import BaseCallbackHandler

_EMPTY: dict[str, int] = {
    "inputTokens": 0,
    "outputTokens": 0,
    "totalTokens": 0,
    "calls": 0,
}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _split_usage(value: Any) -> tuple[int, int, int] | None:
    """从 usage_metadata / token_usage 里取 (输入, 输出, 总计)。"""
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("input_tokens", value.get("prompt_tokens"))
    output_tokens = value.get("output_tokens", value.get("completion_tokens"))
    total_tokens = value.get("total_tokens")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    input_tokens = _int(input_tokens)
    output_tokens = _int(output_tokens)
    total_tokens = _int(total_tokens) or input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def _usage_from_response(response: Any) -> tuple[int, int, int] | None:
    """兼容不同供应商：优先读消息上的 usage_metadata，再读 llm_output。"""
    for batch in getattr(response, "generations", None) or []:
        for generation in batch:
            message = getattr(generation, "message", None)
            usage = _split_usage(getattr(message, "usage_metadata", None))
            if usage:
                return usage
            info = getattr(generation, "generation_info", None) or {}
            usage = _split_usage(info.get("usage_metadata")) or _split_usage(
                info.get("token_usage")
            )
            if usage:
                return usage

    llm_output = getattr(response, "llm_output", None) or {}
    for key in ("token_usage", "usage", "usage_metadata"):
        usage = _split_usage(llm_output.get(key))
        if usage:
            return usage
    return None


class UsageMeter(BaseCallbackHandler):
    """挂在模型回调上的累计器；同一个计量器可以被多个并发调用共享。"""

    def __init__(self) -> None:
        super().__init__()
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.calls = 0

    def add(self, usage: tuple[int, int, int] | None) -> None:
        if not usage:
            return
        input_tokens, output_tokens, total_tokens = usage
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        self.calls += 1

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self.add(_usage_from_response(response))

    def snapshot(self) -> dict[str, int]:
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "calls": self.calls,
        }


_current_meter: ContextVar[UsageMeter | None] = ContextVar(
    "smartcv_usage_meter", default=None
)


@contextmanager
def collect_usage(meter: UsageMeter | None = None) -> Iterator[UsageMeter]:
    """在当前异步上下文内收集 token 用量；退出时恢复上一层计量器。"""
    meter = meter or UsageMeter()
    token = _current_meter.set(meter)
    try:
        yield meter
    finally:
        _current_meter.reset(token)


def current_meter() -> UsageMeter | None:
    return _current_meter.get()


def empty_usage() -> dict[str, int]:
    return dict(_EMPTY)


def merge_usage(base: Any, delta: Any) -> dict[str, int]:
    """把两份 camelCase 计数相加；缺字段按 0 处理。"""
    base = base if isinstance(base, dict) else {}
    delta = delta if isinstance(delta, dict) else {}
    return {
        "inputTokens": _int(base.get("inputTokens")) + _int(delta.get("inputTokens")),
        "outputTokens": _int(base.get("outputTokens")) + _int(delta.get("outputTokens")),
        "totalTokens": _int(base.get("totalTokens")) + _int(delta.get("totalTokens")),
        "calls": _int(base.get("calls")) + _int(delta.get("calls")),
    }


__all__ = [
    "UsageMeter",
    "collect_usage",
    "current_meter",
    "empty_usage",
    "merge_usage",
]
