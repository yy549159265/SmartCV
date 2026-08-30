"""简历 JSON ↔ 带位置标记文本 的互转 + 按位置定位/替换。

前端传来的 Section[] 在这里拍平成「每行一段可改文字、行首带位置编号」的文本：

    [s:章节序号 r:窗口序号 c:内容序号 i:子项序号] 文字内容

优化 agent 据此知道每段文字的坐标；改的时候只调 patch_content(s,r,c,i,text)，
按坐标就地替换文字，JSON 的 id / 样式 / 布局 / 图片一律不动 —— 前端重新渲染
时格式不会乱。

各内容类型对应的「可替换文字单元」：
  iconText   → 1 个（text）
  twoColumn  → 每列 1 个（col）
  timeRange  → 1 个（"起 - 止"整段，写回时再拆回 start/end）
  listText   → 每个列表项 1 个（item）
  tag        → 每个标签 1 个（tag）
  image / spacer 没有文字，不参与（不占 c / i 编号）
"""

_PATCHABLE_TYPES = {"iconText", "twoColumn", "timeRange", "listText", "tag"}


def _leaf_windows(section: dict):
    """章节里所有叶子窗口（DFS 顺序；容器窗口不算，它的子窗口才放内容）。"""

    def walk(rows):
        for row in rows:
            if row.get("rows"):
                yield from walk(row["rows"])
            else:
                yield row

    yield from walk(section.get("rows") or [])


def _text_contents(window: dict):
    """窗口内「可改文字」的内容节点（image/spacer 跳过）。"""
    for content in window.get("contents") or []:
        if content.get("type") in _PATCHABLE_TYPES:
            yield content


def iter_text_units(content: dict) -> list[tuple[str, int, str]]:
    """把内容节点拆成若干「可替换的文字单元」：[(类型, 子序号, 文字)]。

    类型：text / col / range / item / tag，写回时用「类型 + 子序号」定位。
    """
    ctype = content.get("type")
    data = content.get("content") or {}
    if ctype == "iconText":
        return [("text", 0, data.get("text") or "")]
    if ctype == "twoColumn":
        return [("col", i, c or "") for i, c in enumerate(data.get("columns") or [])]
    if ctype == "timeRange":
        return [("range", 0, f"{data.get('start', '')} - {data.get('end', '')}")]
    if ctype == "listText":
        return [("item", i, (it or {}).get("text") or "") for i, it in enumerate(data.get("items") or [])]
    if ctype == "tag":
        return [("tag", i, t or "") for i, t in enumerate(data.get("tags") or [])]
    return []


def resume_to_markdown(resume: list[dict]) -> str:
    """把 Section[] 拍平成带位置编号的标记文本（每行一个可替换文字单元）。"""
    lines: list[str] = []
    for s, section in enumerate(resume):
        title = (section.get("title") or "").strip()
        lines.append(f"# {title}")
        for r, window in enumerate(_leaf_windows(section)):
            for c, content in enumerate(_text_contents(window)):
                for i, (_utype, _ui, text) in enumerate(iter_text_units(content)):
                    lines.append(f"[s:{s} r:{r} c:{c} i:{i}] {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def locate_unit(resume: list[dict], s: int, r: int, c: int, i: int):
    """按坐标定位到「一个内容节点 + 它的一个文字单元」；地址非法返回 None。

    返回 (content, unit_type, unit_index, old_text)。
    """
    if not (0 <= s < len(resume)):
        return None
    windows = list(_leaf_windows(resume[s]))
    if not (0 <= r < len(windows)):
        return None
    contents = list(_text_contents(windows[r]))
    if not (0 <= c < len(contents)):
        return None
    units = iter_text_units(contents[c])
    if not (0 <= i < len(units)):
        return None
    unit_type, unit_index, old = units[i]
    return contents[c], unit_type, unit_index, old


def write_text_unit(content: dict, unit_type: str, unit_index: int, text: str) -> None:
    """把定位到的文字单元写回 content 节点（就地改，不动其它字段）。"""
    data = content.setdefault("content", {})
    if unit_type == "text":
        data["text"] = text
    elif unit_type == "col":
        cols = data.get("columns")
        if cols is not None and 0 <= unit_index < len(cols):
            cols[unit_index] = text
    elif unit_type == "range":
        start, _, end = text.partition("-")
        data["start"] = start.strip()
        data["end"] = end.strip()
    elif unit_type == "item":
        items = data.get("items")
        if items is not None and 0 <= unit_index < len(items):
            items[unit_index]["text"] = text
    elif unit_type == "tag":
        tags = data.get("tags")
        if tags is not None and 0 <= unit_index < len(tags):
            tags[unit_index] = text
