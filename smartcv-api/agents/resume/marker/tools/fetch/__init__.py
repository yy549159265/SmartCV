"""抓取适配器注册表：模块自动发现，按 fetchMode 取适配器。

新增抓取方式：在本目录新建一个文件，定义 Fetcher 子类，末尾 `register(...)`。
"""

import importlib
import pkgutil

from agents.resume.marker.tools.fetch.base import Fetcher, Page

_FETCHERS: dict[str, Fetcher] = {}
_LOADED = False

__all__ = ["Fetcher", "Page", "close_fetchers", "get_fetcher", "list_fetchers", "register"]


def register(fetcher: Fetcher) -> Fetcher:
    for key in (fetcher.id, *fetcher.aliases):
        if key:
            _FETCHERS[key.strip().casefold()] = fetcher
    return fetcher


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for info in pkgutil.iter_modules(__path__):
        if info.name != "base" and not info.name.startswith("_"):
            importlib.import_module(f"{__name__}.{info.name}")


def get_fetcher(name: str) -> Fetcher:
    """按 fetchMode 取适配器；未注册的名称回退到 get。"""
    _load()
    key = (name or "").strip()
    fetcher = _FETCHERS.get(key.casefold()) if key else None
    if fetcher is not None:
        return fetcher
    for item in set(_FETCHERS.values()):
        if item.label.casefold() == key.casefold():
            return item
    return _FETCHERS["get"]


def list_fetchers() -> list[dict]:
    _load()
    return [
        {"id": item.id, "label": item.label}
        for item in sorted(set(_FETCHERS.values()), key=lambda item: item.id)
    ]


async def close_fetchers() -> None:
    """服务退出时释放抓取适配器持有的连接。"""
    _load()
    for fetcher in set(_FETCHERS.values()):
        closer = getattr(fetcher, "aclose", None)
        if callable(closer):
            await closer()
