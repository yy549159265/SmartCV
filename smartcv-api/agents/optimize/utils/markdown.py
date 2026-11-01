"""简历 JSON ↔ 带位置标记文本 的互转 + 按位置定位/替换。

前端传来的 Section[] 在这里拍平成「每行一段可改文字、行首带位置编号」的文本：

    [s:章节序号 r:窗口序号 c:内容序号 i:子项序号] 文字内容

诊断 agent 据此引用坐标；优化 agent 按诊断序号调用 patch_content(index, text)，
由这里按坐标就地替换文字，JSON 的 id / 样式 / 布局 / 图片一律不动 —— 前端重新渲染
时格式不会乱。

各内容类型对应的「可替换文字单元」：
  iconText   → 1 个（text）
  twoColumn  → 每列 1 个（col）
  timeRange  → 1 个（"起 - 止"整段，写回时再拆回 start/end）
  listText   → 每个列表项 1 个（item）
  tag        → 每个标签 1 个（tag）
  image / spacer 没有文字，不参与（不占 c / i 编号）
"""

import re

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


def _numbered_unit_lines(section: dict, s: int) -> list[str]:
    """一个章节里所有可改文字单元的行（带 [s:r:c:i] 编号）。"""
    lines: list[str] = []
    for r, window in enumerate(_leaf_windows(section)):
        for c, content in enumerate(_text_contents(window)):
            for i, (_utype, _ui, text) in enumerate(iter_text_units(content)):
                lines.append(f"[s:{s} r:{r} c:{c} i:{i}] {text}")
    return lines


def resume_to_markdown(resume: list[dict]) -> str:
    """把 Section[] 拍平成带位置编号的标记文本（每行一个可替换文字单元）。"""
    lines: list[str] = []
    for s, section in enumerate(resume):
        title = (section.get("title") or "").strip()
        lines.append(f"# {title}")
        lines.extend(_numbered_unit_lines(section, s))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def resume_to_grammar_markdown(resume: list[dict]) -> str:
    """全文纠错专用：章节标题也带 s 坐标，正文行沿用 [s:r:c:i]。

    普通 resume_to_markdown 的标题是 `# 标题`，没有坐标，模型无法指回某个章节；
    纠错要能改标题，所以单独给出 `[标题 s:N] 标题文字` 的行格式。
    """
    lines: list[str] = []
    for s, section in enumerate(resume):
        title = (section.get("title") or "").strip()
        lines.append(f"[标题 s:{s}] {title}")
        lines.extend(_numbered_unit_lines(section, s))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- 优秀示例：纯结构 Markdown（不带位置编号） ----------

# 说明：优秀示例是「别人的简历」，不能用 resume_to_markdown —— 那套 [s:r:c:i]
# 坐标属于用户自己的简历，混进示例会让模型把示例当成可修改的对象。
# 这里只输出结构文本，供诊断 agent 参考写作方式与结构。

_HTML_TAG = re.compile(r"<[^>]+>")


def _plain_text(value) -> str:
    """去掉内联 SVG / HTML 标签并压平空白：图标可能是品牌 SVG，原样塞进 prompt
    会占掉大量 token，而且对模型理解结构没有任何帮助。"""
    text = _HTML_TAG.sub("", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _plain_content_lines(content: dict, depth: int) -> list[str]:
    """一个内容节点 → 若干行普通 Markdown（不参与编号）。"""
    indent = "  " * depth
    ctype = content.get("type")
    data = content.get("content") or {}

    if ctype == "iconText":
        icon = _plain_text(data.get("icon"))
        text = _plain_text(data.get("text"))
        tags = [_plain_text(t) for t in data.get("tags") or [] if _plain_text(t)]
        if not (icon or text or tags):
            return []
        line = f"{indent}- {icon}{text}".rstrip()
        if tags:
            line += f"  标签：{' / '.join(tags)}"
        return [line]

    if ctype == "twoColumn":
        columns = [_plain_text(c) for c in data.get("columns") or [] if _plain_text(c)]
        if not columns:
            return []
        separator = _plain_text(data.get("separator")) or "|"
        return [f"{indent}- {f' {separator} '.join(columns)}"]

    if ctype == "timeRange":
        start = _plain_text(data.get("start"))
        end = _plain_text(data.get("end"))
        if start and end:
            return [f"{indent}- {start} - {end}"]
        if start or end:
            return [f"{indent}- {start or end}"]
        return []

    if ctype == "tag":
        tags = [_plain_text(t) for t in data.get("tags") or [] if _plain_text(t)]
        return [f"{indent}- 标签：{' / '.join(tags)}"] if tags else []

    if ctype == "listText":
        ordered = data.get("listType") == "ordered"
        lines: list[str] = []
        for number, item in enumerate(data.get("items") or [], 1):
            text = _plain_text((item or {}).get("text"))
            if not text:
                continue
            # 列表项自带缩进（0~2）叠加在窗口层级上，保留原文的层级感
            item_indent = "  " * min(int((item or {}).get("indent") or 0), 2)
            marker = f"{number}." if ordered else "-"
            lines.append(f"{indent}{item_indent}{marker} {text}")
        return lines

    # image / spacer 没有可参考的文字结构，跳过
    return []


def _plain_window_lines(window: dict, depth: int) -> list[str]:
    """一个布局窗口 → 若干行；容器窗口递归子窗口并多缩进一级。"""
    if window.get("rows"):
        lines: list[str] = []
        for child in window["rows"]:
            lines.extend(_plain_window_lines(child, depth + 1))
        return lines
    lines = []
    for content in window.get("contents") or []:
        lines.extend(_plain_content_lines(content, depth))
    return lines


def resume_to_plain_markdown(resume: list[dict]) -> str:
    """把 Section[] 转成「纯结构 Markdown」（无位置编号），用于优秀示例。"""
    lines: list[str] = []
    for section in resume:
        # 顶部信息块常常没有标题：不硬造标题，直接列内容
        title = _plain_text(section.get("title"))
        if title:
            lines.append(f"## {title}")
        for window in section.get("rows") or []:
            lines.extend(_plain_window_lines(window, 0))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def format_reference_examples(examples: list[dict]) -> str:
    """把选中的优秀示例拼成诊断 prompt 里的 `<优秀示例>` 内容。

    每份示例带方向与说明；正文是纯结构 Markdown，不带用户简历的坐标。
    """
    parts: list[str] = []
    for index, example in enumerate(examples, 1):
        direction = str(example.get("direction") or "").strip()
        description = str(example.get("description") or "").strip()
        attrs = f' 方向="{direction}"' if direction else ""
        body = resume_to_plain_markdown(example.get("resume") or []).strip()
        note = f"说明：{description}\n" if description else ""
        parts.append(
            f"<示例 {index}{attrs}>\n{note}<内容>\n{body}\n</内容>\n</示例 {index}>"
        )
    return "\n\n".join(parts)


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


def describe_location(resume: list[dict], item: dict) -> str:
    """把诊断坐标翻译成人能看懂的位置（章节标题 + 条目序号）。

    总结 agent 按这个位置写清单，下一轮诊断靠它知道「上一轮改了哪里」，
    所以要用标题而不是纯编号。
    """
    if item.get("kind") == "structure" or not isinstance(item.get("s"), int):
        return "整体结构"
    s = item["s"]
    if not 0 <= s < len(resume):
        return "简历"
    title = (resume[s].get("title") or "").strip() or f"第 {s + 1} 章"
    coords = [item.get(key) for key in ("r", "c", "i")]
    located = locate_unit(resume, s, *coords) if all(isinstance(v, int) for v in coords) else None
    if located is None:
        return title
    unit_type, i = located[1], item["i"]
    if unit_type == "item":
        return f"{title}·第 {i + 1} 条"
    if unit_type == "tag":
        return f"{title}·第 {i + 1} 个标签"
    return title


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
