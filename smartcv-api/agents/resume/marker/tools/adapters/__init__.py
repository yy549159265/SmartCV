"""来源适配器注册表：模块自动发现，按前端标签取适配器。

新增来源：在本目录新建一个文件，定义 Source 子类，末尾 `register(...)`。
"""

import importlib
import pkgutil

from agents.resume.marker.tools.adapters.base import Hit, Source, SourceBinding

_SOURCES: dict[str, Source] = {}
_LOADED = False

__all__ = ["Hit", "Source", "SourceBinding", "get_source", "register", "resolve_sources"]


def register(source: Source) -> Source:
    for key in (source.id, *source.aliases):
        if key:
            _SOURCES[key.strip().casefold()] = source
    return source


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for info in pkgutil.iter_modules(__path__):
        if info.name != "base" and not info.name.startswith("_"):
            importlib.import_module(f"{__name__}.{info.name}")


def get_source(name: str) -> Source | None:
    """按 id / 别名 / 展示名取适配器；取不到返回 None。"""
    _load()
    key = (name or "").strip()
    if not key:
        return None
    source = _SOURCES.get(key.casefold())
    if source is not None:
        return source
    for item in set(_SOURCES.values()):
        if item.label.casefold() == key.casefold():
            return item
    return None


def resolve_sources(
    selection: dict[str, dict[str, str]] | list[str] | None,
    dim: str,
) -> list[SourceBinding]:
    """前端勾选且适用于当前维度的内置源，连同各自的动态参数返回；没有就返回空列表。

    selection 正常是 `{来源: {设置键: 值}}`；兼容旧的字符串数组，视为没有参数。
    """
    _load()
    if not selection:
        return []
    if isinstance(selection, (list, tuple, set)):
        selection = {str(item).strip(): {} for item in selection if str(item or "").strip()}
    if not isinstance(selection, dict):
        return []

    found: list[SourceBinding] = []
    seen: set[str] = set()
    for name, settings in selection.items():
        source = get_source(str(name))
        if source is None or source.id in seen:
            continue
        if source.dims and dim not in source.dims:
            continue
        seen.add(source.id)
        found.append(SourceBinding(source=source, settings=dict(settings or {})))
    return found
