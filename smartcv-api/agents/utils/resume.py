"""简历 JSON 的公共操作。

对外只有两个主函数，都是「传入简历 JSON，拿回一份文本」：

    resume_to_marked_text(resume)   带坐标简历：每行一段可改文字，行首是 [s:r:c:i]
    resume_to_plain_text(resume)    不带坐标简历：纯结构 Markdown，给优秀示例 / 只读展示用

其余函数是这两个函数的支撑件，以及 agent 按坐标读写的工具（locate_unit /
write_text_unit / describe_location / norm_text），不在业务代码里重复实现。

带坐标简历的形态（行首方括号是位置编号，不是正文）：

    # 基本信息
    [s:0 r:0 c:0 i:0] 王先生

各内容类型拆成的「可替换文字单元」：
  iconText   → 1 个（text）
  twoColumn  → 每列 1 个（col）
  timeRange  → 1 个（"起 - 止"整段，写回时再拆回 start/end）
  listText   → 每个列表项 1 个（item）
  tag        → 每个标签 1 个（tag）
  image / spacer 没有文字，不参与（不占 c / i 编号）
"""

import re


# ==================== 主函数：JSON → 文本 ====================


def resume_to_marked_text(resume: list[dict], *, title_with_coord: bool = False) -> str:
    """带坐标简历：把 Section[] 拍平成「每行一个可替换文字单元」的标记文本。

    默认章节标题输出 `# 标题`（标题没有坐标，符合 coordinate 技能的约定）；
    全文纠错要能改标题，传 title_with_coord=True 时标题输出 `[标题 s:N] 标题文字`。

    Args:
        resume: 简历 JSON（Section[]）。
        title_with_coord: 标题行是否带章节坐标，只给全文纠错用。
    """
    lines: list[str] = []
    for s, section in enumerate(resume):
        title = (section.get("title") or "").strip()
        lines.append(f"[标题 s:{s}] {title}" if title_with_coord else f"# {title}")
        lines.extend(_numbered_unit_lines(section, s))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def resume_to_plain_text(resume: list[dict]) -> str:
    """不带坐标简历：把 Section[] 转成纯结构 Markdown，保留 ## 标题与 - 列表层级。

    用于优秀示例（别人的简历只借写作方式与结构，不能带用户简历的坐标）；
    也适合任何只需要看内容的场景。
    """
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


# ==================== 坐标 → 文字单元 ====================


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


def describe_location(resume: list[dict], item: dict) -> str:
    """把诊断坐标翻译成人能看懂的位置（章节标题 + 条目序号）。

    总结 agent 按这个位置写清单，下一轮诊断靠它知道「上一轮改了哪里」，
    所以要用标题而不是纯编号。
    """
    if not isinstance(item.get("s"), int):
        return "简历"
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


def describe_location_detail(resume: list[dict], item: dict) -> dict:
    """把诊断坐标拆成结构化位置：章节标题 / 章节序号 / 章内位置 / 完整路径。

    前端「诊断结论」按章节树状展示用：前端拿到 section + sectionIndex 分组排序，
    再用 within 标注「第几条」，不用再解析一段拼接字符串。
    path 是 describe_location 的语义等价物，留给需要单行展示的场景。
    """
    if not isinstance(item.get("s"), int):
        return {"section": "简历", "sectionIndex": -1, "within": "", "path": "简历"}
    s = item["s"]
    if not 0 <= s < len(resume):
        return {"section": "简历", "sectionIndex": s, "within": "", "path": "简历"}
    title = (resume[s].get("title") or "").strip() or f"第 {s + 1} 章"
    coords = [item.get(key) for key in ("r", "c", "i")]
    located = locate_unit(resume, s, *coords) if all(isinstance(v, int) for v in coords) else None
    if located is None:
        return {"section": title, "sectionIndex": s, "within": "", "path": title}
    unit_type = located[1]
    i = item["i"]
    if unit_type == "item":
        within = f"第 {i + 1} 条"
    elif unit_type == "tag":
        within = f"第 {i + 1} 个标签"
    elif unit_type == "col":
        within = f"第 {i + 1} 栏"
    elif unit_type == "range":
        within = "时间"
    else:
        within = "正文"
    return {"section": title, "sectionIndex": s, "within": within, "path": f"{title}·{within}"}


def norm_text(text: str) -> str:
    """去掉空白和 Markdown 装饰，用于核对两段文字是否是「同一段」。

    诊断 agent 有时会把 quote 写成 `**加粗**`、`` `代码` `` 或带列表符号，
    而简历原文是纯文本；不抹掉这些标记，核对必然对不上，就会误判成
    「原文核对失败」而不执行。两侧都走同一个函数，所以是安全的。
    """
    value = re.sub(r"\s+", "", text or "")
    # 强调 / 代码 / 删除线符号：原文里没有，纯装饰
    value = re.sub(r"[*`~]", "", value)
    # 成对的下划线强调（__加粗__ / _斜体_）：只去掉包裹符号，单词里的下划线（user_id）不动
    value = re.sub(r"_{1,2}([^_\s]+?)_{1,2}", r"\1", value)
    # 行首列表符号（"- xxx" / "• xxx"）
    return re.sub(r"^[-+•·]+", "", value)


# ==================== 结构遍历（内部） ====================

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


# ---------- 纯结构 Markdown 的内部实现 ----------

# 优秀示例是「别人的简历」，不能带 [s:r:c:i]（那套坐标属于用户自己的简历），
# 所以单独走一套不带编号的渲染。

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
