"""按标准章节抽取确定性中间表示（IR）。

这里不调用 LLM，也不改写文字：只做切分、识别时间段、识别标签。
所有原文最终都会进入某个 IR 字段，供 build 阶段拼成 JSON。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas.models import Block

# 时间范围：2021.07、2021/07、2021年7月、2021-07；结束支持至今/现在/今
_TIME_RANGE = re.compile(
    r"(?P<start>(?:19|20)\d{2}(?:\s*[./\-年]\s*\d{1,2}\s*月?)?)"
    r"\s*(?:-|–|—|~|～|至|到)\s*"
    r"(?P<end>(?:19|20)\d{2}(?:\s*[./\-年]\s*\d{1,2}\s*月?)?|至今|现在|今)"
)
_BULLET = re.compile(r"^\s*(?:[-*+•●·▪◦–—]|\d{1,2}[.、)])\s+(.+)$")
_FIELD_SPLIT = re.compile(r"\s*[|｜·]\s*|\t+|\s{2,}")
_SENTENCE_END = re.compile(r"[。！？；.!?;]\s*$")
_LABEL = re.compile(r"^\s*([^：:]{1,10})\s*[：:]\s*(.+)$")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|www\.)[^\s，。；、]+", re.I)
_CJK_ONLY = re.compile(r"^[㐀-鿿·]{2,6}$")
_LOCATION_HINT = re.compile(r"(省|市|区|县|镇|街道|上海|北京|广州|深圳|杭州|成都|武汉|南京|西安|苏州)")
_HEADLINE_HINT = re.compile(r"(求职意向|目标岗位|应聘|意向岗位|职位)")
_NAME_LABELS = {"姓名", "名字", "name"}
_PHONE_LABELS = {"电话", "手机", "手机号", "联系方式", "tel", "phone"}
_EMAIL_LABELS = {"邮箱", "邮件", "email", "e-mail"}
_LOCATION_LABELS = {"地址", "城市", "所在地", "现居", "居住地", "location", "address"}
_HEADLINE_LABELS = {"求职意向", "目标岗位", "意向岗位", "职位", "应聘岗位", "headline", "title"}
_LINK_LABELS = {"github", "gitlab", "博客", "个人网站", "作品集", "website", "blog", "portfolio"}


@dataclass(slots=True)
class PersonalItem:
    icon: str
    text: str


@dataclass(slots=True)
class Entry:
    columns: list[str] = field(default_factory=list)
    start: str = ""
    end: str = ""
    bullets: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


def is_bullet(text: str) -> bool:
    return bool(_BULLET.match(text or ""))


def strip_bullet(text: str) -> str:
    matched = _BULLET.match(text or "")
    return (matched.group(1) if matched else text).strip()


def split_fields(text: str) -> list[str]:
    return [part.strip() for part in _FIELD_SPLIT.split(text or "") if part.strip()]


def find_time(text: str) -> tuple[str, str, tuple[int, int] | None]:
    matched = _TIME_RANGE.search(text or "")
    if not matched:
        return "", "", None
    return matched.group("start").strip(), matched.group("end").strip(), matched.span()


def remove_time(text: str, span: tuple[int, int] | None) -> str:
    if not span:
        return text
    return (text[: span[0]] + " " + text[span[1] :]).strip()


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search(text or ""))


def _looks_like_title_only(text: str) -> bool:
    """短、无句末标点、不像一条职责描述的独立行，可能是公司/学校标题。"""
    if not text or len(text) > 40 or _ends_sentence(text) or is_bullet(text):
        return False
    if text.startswith(("负责", "参与", "主导", "完成", "使用", "通过", "协助", "独立", "根据", "基于")):
        return False
    return True


def extract_entries(blocks: list[Block]) -> list[Entry]:
    """工作/实习/项目/教育通用：按时间范围或“字段分隔”识别条目。

    时间可能在标题行的同一行、上一行或下一行，所以时间先暂存，
    等下一个标题/列表行认领，避免把单独的时间行拆成空条目。
    """
    lines = [b.text.strip() for b in blocks if b.text.strip()]
    entries: list[Entry] = []
    current: Entry | None = None
    pending_titles: list[str] = []
    pending_time: tuple[str, str] | None = None

    def next_is_bullet(index: int) -> bool:
        return index + 1 < len(lines) and is_bullet(lines[index + 1])

    def next_has_time(index: int) -> bool:
        return index + 1 < len(lines) and bool(find_time(lines[index + 1])[0])

    def new_entry(columns: list[str], start: str = "", end: str = "") -> Entry:
        nonlocal pending_time
        if pending_time and not start and not end:
            start, end = pending_time
        pending_time = None
        entry = Entry(columns=list(columns), start=start, end=end)
        entries.append(entry)
        return entry

    for i, text in enumerate(lines):
        if is_bullet(text):
            # 有暂存时间说明上一条目已结束，这是一条新条目
            if current is None or pending_time is not None:
                current = new_entry(pending_titles)
                pending_titles.clear()
            current.bullets.append(strip_bullet(text))
            continue

        start, end, span = find_time(text)
        rest = remove_time(text, span) if span else text
        fields = split_fields(rest)

        if start and not fields:
            # 只有时间段：上一条还没时间就补上；否则暂存给下一条
            if current is not None and not (current.start or current.end) and not pending_titles:
                current.start, current.end = start, end
            else:
                pending_time = (start, end)
            continue

        is_anchor = bool(start) or (
            len(fields) >= 2 and len(text) <= 100 and not _ends_sentence(text)
        )
        if is_anchor:
            columns = list(pending_titles) + fields
            pending_titles.clear()
            current = new_entry(columns, start, end)
            continue

        # 标题 + 时间都已齐备，后面的普通行就是这条目的描述，别再当标题排队；
        # 但如果下一行又是时间，说明这一行是下一个条目的标题，先把上一条落下来。
        if current is None and pending_titles and pending_time:
            if next_has_time(i):
                new_entry(pending_titles)
                pending_titles = [text]
            else:
                current = new_entry(pending_titles)
                pending_titles.clear()
                current.paragraphs.append(text)
            continue

        # 非条目行：短标题先暂存，等下一条条目/列表行认领
        if _looks_like_title_only(text):
            if current is None:
                pending_titles.append(text)
            elif next_is_bullet(i):
                # 无时间的新公司/项目：后面紧跟列表，按新条目处理
                current = new_entry([text])
            else:
                current.paragraphs.append(text)
            continue

        if current is None:
            current = new_entry([])
        current.paragraphs.append(text)

    # 结尾遗留的短标题：并到最后一个条目；没有条目就单独成段
    if pending_titles:
        if entries:
            entries[-1].paragraphs[:0] = pending_titles
        else:
            entries.append(Entry(columns=[], paragraphs=list(pending_titles)))
        pending_titles.clear()
    if pending_time:
        start, end = pending_time
        if entries and not (entries[-1].start or entries[-1].end):
            entries[-1].start, entries[-1].end = start, end
        elif not entries:
            entries.append(Entry(start=start, end=end))
        pending_time = None

    if not entries and lines:
        entries.append(Entry(columns=[], paragraphs=lines))

    return entries


def extract_personal(blocks: list[Block]) -> list[PersonalItem]:
    """个人信息：保留每行原文，只按内容补一个图标；不丢字段。"""
    items: list[PersonalItem] = []
    for block in blocks:
        text = strip_bullet(block.text).strip()
        if not text:
            continue
        for part in split_fields(text) or [text]:
            label = ""
            value = part
            matched = _LABEL.match(part)
            if matched:
                label, value = matched.group(1).strip(), matched.group(2).strip()
            if not value:
                continue
            items.append(PersonalItem(icon=_pick_icon(label, value), text=value))

    # 没有显式“姓名”标签时，把第一条短中文当姓名
    if items and not any(item.icon == "👤" for item in items):
        for item in items:
            if _CJK_ONLY.match(item.text) and not _LOCATION_HINT.search(item.text):
                item.icon = "👤"
                break

    return items


def _pick_icon(label: str, value: str) -> str:
    key = label.strip().lower()
    if key in _NAME_LABELS:
        return "👤"
    if key in _PHONE_LABELS or _PHONE.search(value):
        return "📞"
    if key in _EMAIL_LABELS or _EMAIL.search(value):
        return "✉️"
    if key in _LOCATION_LABELS or (_LOCATION_HINT.search(value) and len(value) <= 20):
        return "📍"
    if key in _HEADLINE_LABELS or _HEADLINE_HINT.search(value):
        return "💼"
    if key in _LINK_LABELS or _URL.search(value):
        return "🔗"
    return ""


def extract_skill_lines(blocks: list[Block]) -> list[str]:
    """职业技能：保留每一行原文（去掉列表符号）。"""
    return [strip_bullet(b.text).strip() for b in blocks if b.text.strip()]


def extract_text_lines(blocks: list[Block]) -> list[tuple[str, str]]:
    """个人介绍/荣誉/其他：返回 [(kind, text)]，kind = list | text。"""
    result: list[tuple[str, str]] = []
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if is_bullet(text):
            result.append(("list", strip_bullet(text)))
        else:
            result.append(("text", text))
    return result
