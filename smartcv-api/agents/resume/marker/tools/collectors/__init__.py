"""采集方式注册表：模块自动发现，按「采集方式」取适配器。

新增采集方式：在本目录新建一个文件，定义 Collector 子类，末尾 `register(...)`。
"""

import importlib
import pkgutil

from agents.resume.marker.tools.collectors.base import CollectField, Collector

_COLLECTORS: dict[str, Collector] = {}
_LOADED = False

DEFAULT_COLLECTOR = "searxng"

__all__ = [
    "DEFAULT_COLLECTOR",
    "CollectField",
    "Collector",
    "get_collector",
    "register",
    "resolve_collector",
]


def register(collector: Collector) -> Collector:
    for key in (collector.id, collector.label, *collector.aliases):
        if key:
            _COLLECTORS[key.strip().casefold()] = collector
    return collector


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for info in pkgutil.iter_modules(__path__):
        if info.name != "base" and not info.name.startswith("_"):
            importlib.import_module(f"{__name__}.{info.name}")


def get_collector(name: str) -> Collector | None:
    """按 id / 展示名 / 别名取采集方式；取不到返回 None。"""
    _load()
    key = (name or "").strip()
    if not key:
        return None
    return _COLLECTORS.get(key.casefold())


def resolve_collector(
    selection: dict[str, dict[str, str]] | str | None,
) -> tuple[Collector, dict[str, str]]:
    """从 `{采集方式: 设置}` 里取第一个可用项，返回适配器和它自己的设置。

    selection 正常是 `{方式 id: {设置键: 值}}`；兼容只传一个字符串。
    没有可用项时回退到 SearXNG，保证采集永远有一个默认实现。
    """
    _load()
    if isinstance(selection, str):
        selection = {selection: {}}
    elif not isinstance(selection, dict):
        selection = {}
    for name, settings in selection.items():
        collector = get_collector(str(name))
        if collector is None:
            continue
        clean = {
            str(key).strip(): str(value).strip()
            for key, value in (settings or {}).items()
            if str(key).strip()
        }
        return collector, clean
    fallback = _COLLECTORS[DEFAULT_COLLECTOR]
    return fallback, {}
