"""简历骨架生成工具：把「# 章节标题 + <start>/<windows>/<end> 标记行」的 Markdown
直接转成骨架 JSON（Section[]），供前端编辑。内容原样保留，便于核对解析是否正确。"""

import re
import sys
from typing import Callable

from langchain_core.tools import BaseTool, tool
from agents.md2json.schemas.resume import (
    Content,
    ContentData,
    ContentStyle,
    LayoutWindow,
    Resume,
    Section,
    SectionStyle,
)
from agents.md2json.schemas.store import PDF2ResumeStore, Step, create_store

# 匹配时间段，如 2021/07 - 2024/12、2013.09 - 至今（工作/项目/教育块头行的最后一个字段）
_TIME_RANGE_RE = re.compile(
    r"\d{4}[-/.]?\d{0,2}\s*[-~]\s*(\d{4}[-/.]?\d{0,2}|至今|现在)"
)


class _IdGen:
    """全文唯一 id 生成器（b- 前缀 + 递增序号）。"""

    def __init__(self) -> None:
        self._n = 0

    def next_id(self) -> str:
        self._n += 1
        return f"b-{self._n}"


def _parse_segments(line: str) -> list[str]:
    """把一条 `<start> f1 <windows> f2 <end>` 行拆成字段数组（去掉空段）。"""
    body = line
    if body.startswith("<start>"):
        body = body[len("<start>") :]
    if body.endswith("<end>"):
        body = body[: -len("<end>")]
    return [s.strip() for s in body.split("<windows>") if s.strip()]


def _split_time_range(seg: str) -> tuple[str, str]:
    start, end = re.split(r"\s*[-~]\s*", seg, maxsplit=1)
    return start.strip(), end.strip()


# 面向用户/模型的通用错误提示：不暴露中间转换内容（标记行、具体行号），只说明原因并给出建议
_INVALID_MSG = (
    "解析失败：提交的内容无法被识别为简历结构，无法完成转换。"
    "建议重新上传一份更清晰完整的简历，或换用更强的模型重新转换。"
)


def _validate_markdown(markdown: str) -> str | None:
    """格式校验：除空行外，每行必须以 `#` 或 `<start>` 开头，`<start>` 行必须以 `<end>` 结尾。"""
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not (line.startswith("#") or line.startswith("<start>")):
            return _INVALID_MSG
        if line.startswith("<start>") and not line.endswith("<end>"):
            return _INVALID_MSG
    return None


def _split_sections(markdown: str) -> list[tuple[str, list[str]]]:
    """按 `#` 标题切分，返回 [(标题, 该章节的标记行列表)]。

    开头直接是 `<start>` 行（用户可能不写「个人信息」标题）时，
    把这段内容归入空标题章节，按个人信息处理。
    """
    sections: list[tuple[str, list[str]]] = []
    title: str | None = None
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if title is not None or lines:
                sections.append((title or "", lines))
            title = line.lstrip("#").strip()
            lines = []
        else:
            lines.append(line)
    if title is not None or lines:
        sections.append((title or "", lines))
    return sections


def _make_list_text(ids: _IdGen, texts: list[str]) -> Content:
    return Content(
        id=ids.next_id(),
        kind="content",
        type="listText",
        content=ContentData(listType="bullet", items=[{"text": t, "indent": 0} for t in texts]),
        style=ContentStyle(),
    )


def _build_personal_info(ids: _IdGen, title: str, lines: list[str]) -> list[Content]:
    """个人信息：每个字段一条 iconText。"""
    contents: list[Content] = []
    for line in lines:
        for seg in _parse_segments(line):
            contents.append(
                Content(
                    id=ids.next_id(),
                    kind="content",
                    type="iconText",
                    content=ContentData(icon="", text=seg),
                    style=ContentStyle(),
                )
            )
    return contents


def _build_timeline_section(ids: _IdGen, title: str, lines: list[str]) -> list[Content]:
    """工作/项目/教育：块头行（≥2 段，末尾常带时间段）→ twoColumn + timeRange，其余描述行 → listText。"""
    separator = "·" if "项目" in title else "|"
    time_right = "项目" not in title  # 工作/教育的时间段右对齐
    contents: list[Content] = []
    pending: list[str] = []  # 当前块累积的描述行
    for line in lines:
        segs = _parse_segments(line)
        if len(segs) >= 2:
            if pending:
                contents.append(_make_list_text(ids, pending))
                pending = []
            time_idx = next((i for i, s in enumerate(segs) if _TIME_RANGE_RE.search(s)), None)
            cols = [s for i, s in enumerate(segs) if i != time_idx] if time_idx is not None else segs
            if cols:
                contents.append(
                    Content(
                        id=ids.next_id(),
                        kind="content",
                        type="twoColumn",
                        content=ContentData(columns=cols, separator=separator),
                        style=ContentStyle(),
                    )
                )
            if time_idx is not None:
                start, end = _split_time_range(segs[time_idx])
                style = ContentStyle(textAlign="right") if time_right else ContentStyle()
                contents.append(
                    Content(
                        id=ids.next_id(),
                        kind="content",
                        type="timeRange",
                        content=ContentData(start=start, end=end),
                        style=style,
                    )
                )
        else:
            pending.append(segs[0])
    if pending:
        contents.append(_make_list_text(ids, pending))
    return contents


def _build_tag_section(ids: _IdGen, title: str, lines: list[str]) -> list[Content]:
    """专业技能：每行一条 tag。"""
    contents: list[Content] = []
    for line in lines:
        segs = _parse_segments(line)
        if segs:
            contents.append(
                Content(
                    id=ids.next_id(),
                    kind="content",
                    type="tag",
                    content=ContentData(tags=segs),
                    style=ContentStyle(),
                )
            )
    return contents


def _build_default(ids: _IdGen, title: str, lines: list[str]) -> list[Content]:
    """兜底：多段行 → twoColumn，连续单段行 → listText（不再拍平丢结构）。"""
    contents: list[Content] = []
    pending: list[str] = []
    for line in lines:
        segs = _parse_segments(line)
        if len(segs) >= 2:
            if pending:
                contents.append(_make_list_text(ids, pending))
                pending = []
            contents.append(
                Content(
                    id=ids.next_id(),
                    kind="content",
                    type="twoColumn",
                    content=ContentData(columns=segs, separator="|"),
                    style=ContentStyle(),
                )
            )
        else:
            pending.append(segs[0])
    if pending:
        contents.append(_make_list_text(ids, pending))
    return contents


def _is_block_header(line: str) -> bool:
    """判断是否「时间线块头」行：≥2 段且某段带时间段。"""
    segs = _parse_segments(line)
    return len(segs) >= 2 and any(_TIME_RANGE_RE.search(s) for s in segs)


def _has_multi_single(lines: list[str]) -> bool:
    """章节里是否存在 ≥2 行**连续相邻**的「只有 <start>...<end>、中间没有 <windows>」纯文本行。

    挨着的一组才算一个列表；散落在多段行之间的单行不属于同一个列表。
    """
    run = 0
    for line in lines:
        if len(_parse_segments(line)) == 1:
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


def _choose_builder(title: str, lines: list[str]) -> Callable:
    """按标题关键词选构建方式；标题不认识时按内容形态兜底，避免章节标题写死。"""
    if not title or "个人" in title:
        return _build_personal_info  # 没写标题的首段内容按个人信息处理
    if any(_is_block_header(line) for line in lines):
        return _build_timeline_section
    if _has_multi_single(lines):
        return _build_timeline_section  # 多行纯文本 → 列表 → listText
    if any(k in title for k in ("工作", "项目", "教育", "经历", "经验")):
        return _build_timeline_section
    if "技能" in title:
        return _build_tag_section
    return _build_default


def make_section_tools(store: PDF2ResumeStore) -> BaseTool:
    """创建「生成简历骨架」的单个工具，闭包绑定本次调用的 store。

    只保留 1 个工具：agent 用 skill 生成标准标记文本后，把标记文本传给
    generate_resume(markdown) 直接构造 JSON。
    """

    @tool
    def generate_resume(markdown: str) -> str:
        """将带标记的简历文本解析成简历骨架 JSON。

        什么时候用：原始文本已用 md2md 技能整理成标准标记格式，需要生成简历骨架时调用。

        输入内容：逐行排布的纯文本，每行只能是下面两种之一——
            `# 章节标题`，或一条 `<start> 字段1 <windows> 字段2 <end>` 记录行。
        返回：一句状态（如「转换完成，共 N 个章节」）；生成的 JSON 已存入 store，不回传。
        """
        store.markdown = markdown
        store.finish_step(Step.ORGANIZE)

        # 1 格式校验所有行是否以 # 或 <start> 开头，排除空行
        store.start_step(Step.CONVERT)
        if error := _validate_markdown(markdown):
            store.fail_step(Step.CONVERT, error)
            return error

        # 2 以# 分割，然后循环 处理每一个 章节内容
        ids = _IdGen()
        sections: list[Section] = []
        for title, lines in _split_sections(markdown):
            # 3 按标题/内容形态把标记行转成内容单元，再包成 Section
            builder = _choose_builder(title, lines)
            contents = builder(ids, title, lines)
            sections.append(
                Section(
                    id=ids.next_id(),
                    kind="section",
                    title=title,
                    style=SectionStyle(gap=12),
                    rows=[LayoutWindow(id=ids.next_id(), layout="vertical", contents=contents)],
                )
            )

        store.content = Resume(sections=sections)
        store.finish_step(Step.CONVERT)
        # JSON 已存进 store.content，这里只回状态，不把整份 JSON 回给模型省 token
        return f"转换完成，共 {len(sections)} 个章节"

    return generate_resume

