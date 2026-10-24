"""结构完整性与内容保真校验。

校验只读内存里的 IR / Section，不调用 LLM，也不把原文写进日志：
- coverage：清洗后的块有多少能（按去空白/标点后的文本）在结果里找到；
- unmatched_ids：没找到的块 id（只有 id，不含正文）；
- missing_tokens：原文里的手机号/邮箱是否在结果中丢失（只在进程内使用）；
- warnings：给日志看的中文提示，不含用户正文。
"""

from __future__ import annotations

import re

from agents.md2json.schemas.resume import Content, LayoutWindow, Section

from ..schemas.models import Block, SectionPlan, ValidationReport

# 去掉空白、标点和下划线，只留下文字/数字，用来做「不改变语义」的包含判断
_KEY_NOISE = re.compile(r"[^\w]+|_", re.UNICODE)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 表格行 / 多字段行：规范化会把字段重排到不同列，必须逐字段比较
_FIELD_SEP = re.compile(r"[|｜\t]+")
# 过短的单字（如“男/女”）容易误判，不参与覆盖率统计
_MIN_KEY = 2


def _key(text: str) -> str:
    return _KEY_NOISE.sub("", text or "")


def _row_matched(text: str, combined: str) -> bool:
    """`A | B | C` 按字段逐个比对；规范化后字段顺序可能变化。"""
    parts = [part.strip() for part in _FIELD_SEP.split(text or "") if part.strip()]
    if len(parts) < 2:
        return False
    return all(len(_key(part)) < _MIN_KEY or _key(part) in combined for part in parts)


def _iter_contents(rows: list[LayoutWindow]):
    for row in rows:
        yield from row.contents
        if row.rows:
            yield from _iter_contents(row.rows)


def _content_strings(content: Content) -> list[str]:
    data = content.content
    values: list[str] = []
    if data.text:
        values.append(data.text)
    if data.columns:
        values.extend(data.columns)
    if data.start:
        values.append(data.start)
    if data.end:
        values.append(data.end)
    if data.items:
        values.extend(item.text for item in data.items if item.text)
    if data.tags:
        values.extend(data.tags)
    return values


def _section_key(sections: list[Section]) -> str:
    parts: list[str] = []
    for section in sections:
        # 标题本身也是原文的一部分（清洗时保留的标题块），必须计入保真比较
        parts.append(section.title)
        for content in _iter_contents(section.rows):
            parts.extend(_content_strings(content))
    return _key("".join(parts))


def validate_sections(
    blocks: list[Block],
    plans: list[SectionPlan] | None,
    sections: list[Section],
) -> ValidationReport:
    """对比「清洗后的原文块」与「最终 Section[]」，报告保真情况。

    标题块不计入覆盖率：模板会把「教育背景」统一成「教育经历」，标题被
    改写是设计行为；章节是否存在由 Section[] 本身保证。这里只校验正文块。

    plans 为 None 时表示走的是大模型规范化路径，没有规则切分出来的章节计划；
    此时仅按 heading 标记排除标题块。
    """
    heading_titles = {plan.title for plan in plans if plan.title} if plans else set()
    content_blocks = [
        block
        for block in blocks
        if block.kind != "heading" and block.text not in heading_titles
    ]

    report = ValidationReport(total_blocks=len(content_blocks))
    combined = _section_key(sections)

    matched = 0
    for block in content_blocks:
        key = _key(block.text)
        if len(key) < _MIN_KEY:
            matched += 1
            continue
        if key in combined or _row_matched(block.text, combined):
            matched += 1
        else:
            report.unmatched_ids.append(block.id)

    if content_blocks:
        report.coverage = matched / len(content_blocks)

    # 关键联系信息：原文有、结果没有 → 记录 token（仅进程内，用于定位问题）
    source = "\n".join(block.text for block in content_blocks)
    for pattern in (_PHONE, _EMAIL):
        for token in pattern.findall(source):
            if _key(token) and _key(token) not in combined:
                report.missing_tokens.append(token)

    if plans is not None:
        present = {plan.type for plan in plans if plan.blocks}
        if "personal_info" not in present:
            report.warnings.append("未识别到个人信息章节")
        if "education" not in present:
            report.warnings.append("未识别到教育经历章节")
    if not sections:
        report.warnings.append("没有生成任何章节")
    if report.unmatched_ids:
        report.warnings.append(f"{len(report.unmatched_ids)} 个原文块未完整进入结果")
    if report.coverage < 0.9:
        report.warnings.append(f"内容覆盖率偏低：{report.coverage:.0%}")

    return report
