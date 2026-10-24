"""IR → 简历 JSON（Section[]）。

整个构建过程是确定性的：
- 章节顺序由模板 order 决定；
- 条目顺序保持原文顺序；
- id 用 s01 / s01-w01 / s01-c001 这类稳定编号；
- 不调用 LLM，不生成原文之外的内容。
"""

from __future__ import annotations

from math import ceil
from typing import Callable

from agents.md2json.schemas.resume import (
    Content,
    ContentData,
    ContentStyle,
    LayoutWindow,
    ListItem,
    Section,
    SectionStyle,
)

from ..schemas.canonical import (
    CanonicalResume,
    CampusItem,
    EducationItem,
    OtherSection,
    ProjectItem,
    WorkItem,
)
from .extract import (
    Entry,
    PersonalItem,
    extract_entries,
    extract_personal,
    extract_skill_lines,
    extract_text_lines,
    find_time,
)
from ..schemas.models import SectionPlan
from .sections import SectionType
from .template import Template


class _Ids:
    """稳定、可复现的 id 生成器。"""

    def __init__(self) -> None:
        self._section = 0
        self._window = 0
        self._content = 0

    def start_section(self) -> str:
        self._section += 1
        self._window = 0
        self._content = 0
        return f"s{self._section:02d}"

    def window(self) -> str:
        self._window += 1
        return f"s{self._section:02d}-w{self._window:02d}"

    def content(self) -> str:
        self._content += 1
        return f"s{self._section:02d}-c{self._content:03d}"


def _icon_text(ids: _Ids, icon: str, text: str) -> Content:
    return Content(
        id=ids.content(),
        type="iconText",
        content=ContentData(icon=icon, text=text),
        style=ContentStyle(),
    )


def _list_text(ids: _Ids, items: list[str]) -> Content:
    return Content(
        id=ids.content(),
        type="listText",
        content=ContentData(
            listType="bullet",
            items=[ListItem(text=text, indent=0) for text in items],
        ),
        style=ContentStyle(),
    )


def _two_column(ids: _Ids, columns: list[str], separator: str = "|") -> Content:
    return Content(
        id=ids.content(),
        type="twoColumn",
        content=ContentData(columns=columns, separator=separator),
        style=ContentStyle(),
    )


def _time_range(ids: _Ids, start: str, end: str, align: str = "right") -> Content:
    return Content(
        id=ids.content(),
        type="timeRange",
        content=ContentData(start=start, end=end),
        style=ContentStyle(textAlign=align),  # type: ignore[arg-type]
    )


def _vertical(ids: _Ids, contents: list[Content]) -> LayoutWindow:
    return LayoutWindow(id=ids.window(), layout="vertical", contents=contents)


def _horizontal(ids: _Ids, rows: list[LayoutWindow]) -> LayoutWindow:
    return LayoutWindow(id=ids.window(), layout="horizontal", contents=[], rows=rows)


def _build_text(ids: _Ids, plan: SectionPlan) -> list[Content]:
    """保留原文顺序：连续的列表行合成一个 listText，其余行各成一条 iconText。"""
    lines = extract_text_lines(plan.blocks)
    contents: list[Content] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            contents.append(_list_text(ids, list(pending)))
            pending.clear()

    for kind, text in lines:
        if kind == "list":
            pending.append(text)
        else:
            flush()
            contents.append(_icon_text(ids, "", text))
    flush()
    return contents


def _build_personal(ids: _Ids, plan: SectionPlan) -> list[Content]:
    items: list[PersonalItem] = extract_personal(plan.blocks)
    if not items:
        return _build_text(ids, plan)
    return [_icon_text(ids, item.icon, item.text) for item in items]


def _build_skills(ids: _Ids, plan: SectionPlan) -> list[Content]:
    lines = extract_skill_lines(plan.blocks)
    if not lines:
        return _build_text(ids, plan)
    return [_list_text(ids, lines)]


def _entry_header(
    ids: _Ids, entry: Entry, separator: str, right_time: bool
) -> LayoutWindow | None:
    header: Content | None = None
    if len(entry.columns) == 1:
        header = _icon_text(ids, "", entry.columns[0])
    elif len(entry.columns) >= 2:
        header = _two_column(ids, entry.columns, separator)

    time: Content | None = None
    if entry.start or entry.end:
        time = _time_range(ids, entry.start, entry.end, "right" if right_time else "left")

    if header and time:
        return _horizontal(ids, [_vertical(ids, [header]), _vertical(ids, [time])])
    if header:
        return _vertical(ids, [header])
    if time:
        return _vertical(ids, [time])
    return None


def _timeline_windows(
    ids: _Ids, plan: SectionPlan, separator: str, right_time: bool
) -> list[LayoutWindow]:
    """工作/教育/项目：每个条目一个“标题 + 时间”窗口，后面跟描述窗口。"""
    windows: list[LayoutWindow] = []
    for entry in extract_entries(plan.blocks):
        header = _entry_header(ids, entry, separator, right_time)
        if header is not None:
            windows.append(header)

        body: list[Content] = []
        if entry.bullets:
            body.append(_list_text(ids, entry.bullets))
        for paragraph in entry.paragraphs:
            body.append(_icon_text(ids, "", paragraph))
        if body:
            windows.append(_vertical(ids, body))

    if not windows:
        contents = _build_text(ids, plan)
        if contents:
            windows.append(_vertical(ids, contents))
    return windows


def _build_contents(ids: _Ids, plan: SectionPlan) -> tuple[list[Content], list[LayoutWindow] | None]:
    """返回 (contents, rows)；二者最多一个非空。"""
    if plan.type == SectionType.personal_info.value:
        return _build_personal(ids, plan), None
    if plan.type == SectionType.skills.value:
        return _build_skills(ids, plan), None
    if plan.type == SectionType.summary.value:
        return _build_text(ids, plan), None
    if plan.type == SectionType.education.value:
        return [], _timeline_windows(ids, plan, "|", True)
    if plan.type == SectionType.work.value:
        return [], _timeline_windows(ids, plan, "|", True)
    if plan.type == SectionType.internship.value:
        return [], _timeline_windows(ids, plan, "|", True)
    if plan.type == SectionType.project.value:
        return [], _timeline_windows(ids, plan, "·", False)
    return _build_text(ids, plan), None


def _section_style(style: dict) -> SectionStyle:
    allowed = {"fontSize", "color", "lineHeight", "textAlign", "titleSize", "gap", "spaceBefore", "titleUnderline"}
    clean = {k: v for k, v in (style or {}).items() if k in allowed}
    return SectionStyle(**clean) if clean else SectionStyle(gap=8)


def build_sections(plans: list[SectionPlan], template: Template) -> list[Section]:
    """按模板顺序把章节计划转成 Section[]。"""
    ordered = sorted(plans, key=lambda p: template.order_index(p.type))
    ids = _Ids()
    sections: list[Section] = []

    for plan in ordered:
        if not plan.blocks:
            continue
        section_id = ids.start_section()
        contents, rows = _build_contents(ids, plan)
        if rows is None:
            if not contents:
                continue
            rows = [_vertical(ids, contents)]
        if not rows:
            continue

        sections.append(
            Section(
                id=section_id,
                title=template.title_for(plan.type, plan.title),
                style=_section_style(template.style_for(plan.type)),
                rows=rows,
            )
        )

    return sections


# ---------------------------------------------------------------------------
# 大模型规范化结果（CanonicalResume）→ Section[]
#
# 与上面的确定性路径共用 _Ids / 内容构造函数，但字段来源是 canonical.py 的
# 结构化数据：时间、学校、学位、专业已经是独立字段，这里只负责排版。
# ---------------------------------------------------------------------------


def _lines(items: list[str]) -> list[str]:
    """一条数组元素一行；元素内部如果还有换行，也拆开，避免多行挤在一个块里。"""
    result: list[str] = []
    for item in items or []:
        for line in str(item).splitlines():
            text = line.strip()
            if text:
                result.append(text)
    return result


def _tag(ids: _Ids, tags: list[str]) -> Content:
    return Content(
        id=ids.content(),
        type="tag",
        content=ContentData(tags=list(tags)),
        style=ContentStyle(textAlign="left"),  # type: ignore[arg-type]
    )


def _spacer(ids: _Ids, font_size: float | None = None) -> Content:
    style = ContentStyle(fontSize=font_size) if font_size else ContentStyle()
    return Content(id=ids.content(), type="spacer", content=ContentData(), style=style)


def _time_parts(
    start: str, end: str, fallback: str
) -> tuple[str, str, str]:
    """统一成 (start, end, 一行显示文本)。"""
    start = (start or "").strip()
    end = (end or "").strip()
    fallback = (fallback or "").strip()
    if not start and not end and fallback:
        # 兼容模型仍输出 “2007.2-2011.6” / “2014.1-至今” 这种整段时间
        found_start, found_end, _ = find_time(fallback)
        if found_start or found_end:
            start, end = found_start, found_end
    if start or end:
        text = " - ".join(part for part in (start, end) if part)
    else:
        text = fallback
    return start, end, text


def _time_content(ids: _Ids, start: str, end: str, text: str) -> Content | None:
    if start and end:
        return _time_range(ids, start, end, "right")
    if text:
        # 只有开始时间或无法拆分时，按原文显示，不要渲染成 “start - ”
        return Content(
            id=ids.content(),
            type="iconText",
            content=ContentData(icon="", text=text),
            style=ContentStyle(textAlign="right"),  # type: ignore[arg-type]
        )
    return None


def _header_row(
    ids: _Ids, columns: list[str], start: str, end: str, time_text: str
) -> LayoutWindow | None:
    """左侧字段 + 右侧时间，严格保持在同一行。"""
    columns = [c.strip() for c in columns if c and c.strip()]
    if len(columns) >= 2:
        left: Content | None = _two_column(ids, columns, "|")
    elif columns:
        left = _icon_text(ids, "", columns[0])
    else:
        left = None

    right = _time_content(ids, start, end, time_text)

    if left and right:
        return _horizontal(ids, [_vertical(ids, [left]), _vertical(ids, [right])])
    if left:
        return _vertical(ids, [left])
    if right:
        return _vertical(ids, [right])
    return None


def _personal_rows(ids: _Ids, canonical: CanonicalResume) -> list[LayoutWindow]:
    personal = canonical.personal
    left: list[Content] = []
    if personal.name:
        left.append(
            Content(
                id=ids.content(),
                type="iconText",
                content=ContentData(icon="", text=personal.name),
                style=ContentStyle(fontSize=52),
            )
        )
    if personal.job_title:
        left.append(_icon_text(ids, "👤", personal.job_title))
    if personal.phone:
        left.append(_icon_text(ids, "📞", personal.phone))
    if personal.location:
        left.append(_icon_text(ids, "📍", personal.location))

    right: list[Content] = []
    if personal.email:
        right.append(_icon_text(ids, "✉️", personal.email))
    if personal.website:
        right.append(_icon_text(ids, "🔗", personal.website))
    for extra in _lines(personal.extra):
        right.append(_icon_text(ids, "", extra))

    if left and right:
        # 右侧加占位，让邮箱和电话在同一行，视觉上更像简历抬头
        prefix: list[Content] = []
        if personal.name:
            prefix.append(_spacer(ids, 52))
        if personal.job_title:
            prefix.append(_spacer(ids))
        return [_horizontal(ids, [_vertical(ids, left), _vertical(ids, prefix + right)])]
    if left:
        return [_vertical(ids, left)]
    if right:
        return [_vertical(ids, right)]
    return []


def _education_rows(ids: _Ids, item: EducationItem) -> list[LayoutWindow]:
    start, end, time_text = _time_parts(item.start, item.end, item.time)
    right_columns = [item.degree, item.major, time_text]
    rows: list[LayoutWindow] = []

    if item.school:
        # 学校在左、学位/专业/时间在右，仍然是一行
        right_columns = [c.strip() for c in right_columns if c and c.strip()]
        if right_columns:
            if len(right_columns) >= 2:
                right: Content = _two_column(ids, right_columns, "|")
            else:
                right = _icon_text(ids, "", right_columns[0])
            right.style.textAlign = "right"
            rows.append(
                _horizontal(
                    ids,
                    [
                        _vertical(ids, [_icon_text(ids, "", item.school)]),
                        _vertical(ids, [right]),
                    ],
                )
            )
        else:
            rows.append(_vertical(ids, [_icon_text(ids, "", item.school)]))
    else:
        header = _header_row(ids, [item.degree, item.major], start, end, time_text)
        if header is not None:
            rows.append(header)

    details = _lines(item.details)
    if details:
        rows.append(_vertical(ids, [_list_text(ids, details)]))
    return rows


def _work_rows(
    ids: _Ids,
    start: str,
    end: str,
    time: str,
    company: str,
    title: str,
    description: list[str],
    tags: list[str],
) -> list[LayoutWindow]:
    start, end, time_text = _time_parts(start, end, time)
    rows: list[LayoutWindow] = []

    header = _header_row(ids, [company, title], start, end, time_text)
    if header is not None:
        rows.append(header)

    body: list[Content] = []
    clean_tags = _lines(tags)
    if clean_tags:
        body.append(_tag(ids, clean_tags))
    lines = _lines(description)
    if lines:
        # 一条职责一个 bullet，绝不把两条职责合并成一条
        body.append(_list_text(ids, lines))
    if body:
        rows.append(_vertical(ids, body))
    return rows


def _project_rows(ids: _Ids, item: ProjectItem) -> list[LayoutWindow]:
    return _work_rows(
        ids, item.start, item.end, item.time, item.name, item.role, item.description, item.tags
    )


def _campus_rows(ids: _Ids, item: CampusItem) -> list[LayoutWindow]:
    return _work_rows(
        ids, item.start, item.end, item.time, item.organization, item.role, item.description, []
    )


def _chunk(items: list[str], count: int) -> list[list[str]]:
    if count <= 1:
        return [list(items)]
    size = ceil(len(items) / count)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _skill_columns(
    canonical: CanonicalResume,
) -> tuple[list[list[tuple[str, list[str]]]], str]:
    """把技能分组平衡地分到 1~3 列。

    返回 (列内容, 共享标题)。共享标题只在一个分组被拆成多列时出现，
    避免把同一个分组名在每一列重复一遍。
    """
    cells: list[tuple[str, list[str]]] = []
    for group in canonical.skills:
        label = (group.group or "").strip()
        items = _lines(group.items)
        if label or items:
            cells.append((label, items))
    if not cells:
        return [], ""

    if len(cells) == 1:
        label, items = cells[0]
        if len(items) >= 6:
            chunks = _chunk(items, 3)
            return [[("", chunk)] for chunk in chunks], label
        return [[(label, items)]], ""

    count = min(3, len(cells))
    size = ceil(len(cells) / count)
    return [cells[i : i + size] for i in range(0, len(cells), size)], ""


def _skill_contents(ids: _Ids, label: str, items: list[str]) -> list[Content]:
    """短技能用标签芯片，长句用列表，避免把一整段话塞进一个 tag。"""
    contents: list[Content] = []
    if label:
        contents.append(_icon_text(ids, "", label))
    if items:
        if max(len(item) for item in items) > 24:
            contents.append(_list_text(ids, items))
        else:
            contents.append(_tag(ids, items))
    return contents


def _skill_rows(ids: _Ids, canonical: CanonicalResume) -> list[LayoutWindow]:
    columns, shared_label = _skill_columns(canonical)
    if not columns:
        return []

    if len(columns) == 1:
        contents: list[Content] = []
        for label, items in columns[0]:
            contents.extend(_skill_contents(ids, label, items))
        return [_vertical(ids, contents)] if contents else []

    leaves: list[LayoutWindow] = []
    for column in columns:
        contents: list[Content] = []
        for label, items in column:
            contents.extend(_skill_contents(ids, label, items))
        if contents:
            leaves.append(_vertical(ids, contents))
    if not leaves:
        return []

    rows: list[LayoutWindow] = []
    if shared_label:
        # 分组名单独一行，下面再排多列标签，标签之间才能对齐
        rows.append(_vertical(ids, [_icon_text(ids, "", shared_label)]))
    rows.append(_horizontal(ids, leaves))
    return rows


def _other_rows(ids: _Ids, item: OtherSection) -> list[LayoutWindow]:
    lines = _lines(item.items)
    if not lines:
        return []
    return [_vertical(ids, [_list_text(ids, lines)])]


def build_canonical_sections(canonical: CanonicalResume, template: Template) -> list[Section]:
    """CanonicalResume → Section[]。

    顺序仍由模板 order 决定；id 按最终显示顺序生成（s01、s01-w01、s01-c001）。
    所有版式规则都在这里，模型只提供语义字段。
    """
    specs: list[tuple[str, str, Callable[[_Ids], list[LayoutWindow]]]] = []

    if _personal_rows_ready(canonical):
        specs.append(("personal_info", "", lambda i: _personal_rows(i, canonical)))
    if _lines(canonical.summary):
        specs.append(
            (
                "summary",
                "",
                lambda i: [
                    _vertical(i, [_icon_text(i, "", line) for line in _lines(canonical.summary)])
                ],
            )
        )
    if canonical.education:
        specs.append(
            (
                "education",
                "",
                lambda i: [row for item in canonical.education for row in _education_rows(i, item)],
            )
        )
    if canonical.work:
        specs.append(
            (
                "work",
                "",
                lambda i: [
                    row
                    for item in canonical.work
                    for row in _work_rows(
                        i,
                        item.start,
                        item.end,
                        item.time,
                        item.company,
                        item.title,
                        item.description,
                        item.tags,
                    )
                ],
            )
        )
    if canonical.internship:
        specs.append(
            (
                "internship",
                "",
                lambda i: [
                    row
                    for item in canonical.internship
                    for row in _work_rows(
                        i,
                        item.start,
                        item.end,
                        item.time,
                        item.company,
                        item.title,
                        item.description,
                        item.tags,
                    )
                ],
            )
        )
    if canonical.project:
        specs.append(
            (
                "project",
                "",
                lambda i: [row for item in canonical.project for row in _project_rows(i, item)],
            )
        )
    if canonical.skills:
        specs.append(("skills", "", lambda i: _skill_rows(i, canonical)))
    if _lines(canonical.awards):
        specs.append(
            ("awards", "", lambda i: [_vertical(i, [_list_text(i, _lines(canonical.awards))])])
        )
    if _lines(canonical.certificates):
        specs.append(
            (
                "certificates",
                "",
                lambda i: [_vertical(i, [_list_text(i, _lines(canonical.certificates))])],
            )
        )
    if canonical.campus:
        specs.append(
            (
                "campus",
                "",
                lambda i: [row for item in canonical.campus for row in _campus_rows(i, item)],
            )
        )
    for other in canonical.other:
        if _lines(other.items):
            specs.append(
                ("other", other.title, lambda i, item=other: _other_rows(i, item))
            )

    # 同类型章节保持 canonical 顺序（other 可能有多个不同标题）
    specs.sort(key=lambda spec: template.order_index(spec[0]))

    ids = _Ids()
    sections: list[Section] = []
    for section_type, title, build_rows in specs:
        section_id = ids.start_section()
        rows = build_rows(ids)
        if not rows:
            continue
        display_title = template.title_for(section_type, title)
        if section_type == SectionType.other.value and not display_title:
            display_title = title or "其他"
        sections.append(
            Section(
                id=section_id,
                title=display_title,
                style=_section_style(template.style_for(section_type)),
                rows=rows,
            )
        )
    return sections


def _personal_rows_ready(canonical: CanonicalResume) -> bool:
    p = canonical.personal
    return bool(
        p.name
        or p.job_title
        or p.phone
        or p.email
        or p.location
        or p.website
        or _lines(p.extra)
    )
