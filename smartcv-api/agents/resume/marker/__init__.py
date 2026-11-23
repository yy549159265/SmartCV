"""市场洞察 agent 包入口。

对外只暴露两样东西：启动一次调研（`run_market_stream`）和请求模型（`MarketRequest`）。
`run_market_stream` 用惰性导入，避免只取 schema 时把整条 agent 流水线（提示词、模型）
一起加载，也避免包初始化期间的循环依赖。
"""

from typing import TYPE_CHECKING

from agents.resume.marker.schemas import MarketRequest

if TYPE_CHECKING:  # pragma: no cover
    from agents.resume.marker.graph import run_market_stream

__all__ = ["MarketRequest", "run_market_stream"]


def __getattr__(name: str):
    if name == "run_market_stream":
        from agents.resume.marker.graph import run_market_stream

        return run_market_stream
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
