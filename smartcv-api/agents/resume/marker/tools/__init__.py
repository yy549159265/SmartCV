"""市场洞察的可复用能力：来源适配器、抓取适配器、采集方式适配器、采集协调。

依赖方向：tools → schemas / utils；tools 不 import 任何 agent。
"""

from agents.resume.marker.tools.adapters import (
    Hit,
    Source,
    SourceBinding,
    get_source,
    resolve_sources,
)
from agents.resume.marker.tools.collect import collect_market
from agents.resume.marker.tools.collectors import Collector, get_collector, resolve_collector
from agents.resume.marker.tools.fetch import (
    Fetcher,
    Page,
    close_fetchers,
    get_fetcher,
    list_fetchers,
)

__all__ = [
    "Collector",
    "Fetcher",
    "Hit",
    "Page",
    "Source",
    "SourceBinding",
    "close_fetchers",
    "collect_market",
    "get_collector",
    "get_fetcher",
    "get_source",
    "list_fetchers",
    "resolve_collector",
    "resolve_sources",
]
