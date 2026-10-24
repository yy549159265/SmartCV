"""确定性的章节切分与合并（大模型不可用时的兜底路径）。

规则：
- 标题优先看 content_list 的 text_level，其次看 Markdown 的 #；
- 标题文字只做精确别名匹配（不用“包含关键词”猜，避免“个人项目”被当成个人信息）；
- 匹配不到的类型归为 other，保留原标题和全部内容，绝不静默丢弃；
- 同类型章节自动合并；other 按原标题区分，不合并。
"""

from __future__ import annotations

import re
from enum import Enum

from ..schemas.models import Block, SectionPlan

_STRIP_TITLE = re.compile(r"[\s:：·•\-—_（）()【】\[\]<>《》/\\|｜,，;；]+")
_SPLIT_TITLE = re.compile(r"[/｜|、,，;；()（）\[\]【】]+")


class SectionType(str, Enum):
    personal_info = "personal_info"
    summary = "summary"
    education = "education"
    work = "work"
    internship = "internship"
    project = "project"
    skills = "skills"
    awards = "awards"
    certificates = "certificates"
    campus = "campus"
    other = "other"


# 精确别名（归一化后比较）。中英文都覆盖，新增说法往这里加一行即可。
_ALIASES: dict[str, str] = {}


def _register(section_type: SectionType, *names: str) -> None:
    for name in names:
        _ALIASES[_normalize_title(name)] = section_type.value


def _normalize_title(title: str) -> str:
    return _STRIP_TITLE.sub("", title or "").lower()


_register(
    SectionType.personal_info,
    "个人信息", "基本信息", "个人资料", "联系方式", "个人简历", "简历信息",
    "personal information", "contact information", "profile",
)
_register(
    SectionType.summary,
    "个人介绍", "自我介绍", "自我评价", "个人评价", "个人总结", "个人优势",
    "个人简介", "关于我", "个人陈述", "summary", "about me", "profile summary",
)
_register(
    SectionType.education,
    "教育经历", "教育背景", "学习经历", "教育", "学历", "education", "education background",
)
_register(
    SectionType.work,
    "工作经历", "工作经验", "职业经历", "任职经历", "工作履历", "职业履历",
    "work experience", "employment", "experience",
)
_register(
    SectionType.internship,
    "实习经历", "实习经验", "实习", "internship", "internship experience",
)
_register(
    SectionType.project,
    "项目经历", "项目经验", "项目实践", "项目", "主要项目", "项目履历",
    "projects", "project experience",
)
_register(
    SectionType.skills,
    "专业技能", "职业技能", "技能特长", "技能清单", "技术栈", "个人技能", "技能",
    "专业能力", "技术能力", "skills", "technical skills",
)
_register(
    SectionType.awards,
    "荣誉奖项", "获奖经历", "所获奖励", "荣誉证书", "奖励荣誉", "获奖情况",
    "honors", "awards", "honors awards",
)
_register(
    SectionType.certificates,
    "证书", "资格证书", "技能证书", "认证", "certificates", "certifications",
)
_register(
    SectionType.campus,
    "校园经历", "社团经历", "学生工作", "校园实践", "校园活动", "campus",
    "campus experience",
)


def match_section_type(title: str) -> str | None:
    """精确别名匹配；同时兼容“中文 / English”这种双语标题。"""
    if not title:
        return None
    candidates = {_normalize_title(title)}
    for part in _SPLIT_TITLE.split(title):
        if part.strip():
            candidates.add(_normalize_title(part))
    for candidate in candidates:
        if candidate in _ALIASES:
            return _ALIASES[candidate]
    return None


def _heading_level(block: Block) -> int | None:
    """标题层级：content_list 的 text_level / Markdown 的 # 数量。"""
    if block.level and block.level > 0:
        return block.level
    if block.kind == "heading":
        return 1
    return None


def _is_heading(block: Block) -> bool:
    if _heading_level(block) is not None:
        return True
    # 没有标题层级时，只接受精确别名，不猜
    return len(block.text) <= 20 and match_section_type(block.text) is not None


def split_sections(blocks: list[Block]) -> list[SectionPlan]:
    """按标题切分；标题不合并，先保留每一次出现，交给 merge_sections 处理。

    只有「最外层标题」才开新章节：公司名/项目名常被解析成更深一级的标题，
    它们属于上一节的正文，不能把工作经历切碎。已知章节名（教育经历等）
    即使层级更深，仍按章节处理。
    """
    plans: list[SectionPlan] = []
    preamble: list[Block] = []
    current: SectionPlan | None = None

    levels = [level for b in blocks if (level := _heading_level(b)) is not None]
    top_level = min(levels) if levels else None

    for block in blocks:
        if _is_heading(block):
            title = block.text.strip("# ").strip()
            if not title:
                continue
            level = _heading_level(block)
            known = match_section_type(title) is not None
            nested = level is not None and top_level is not None and level > top_level
            if nested and not known:
                # 深层未知标题：当作当前章节里的一行内容，保留原文；
                # 同时降级为普通文本，后续抽取/校验都按正文处理。
                block.kind = "text"
                block.level = None
                if current is not None:
                    current.blocks.append(block)
                else:
                    preamble.append(block)
                continue
            current = SectionPlan(
                type=match_section_type(title) or SectionType.other.value,
                title=title,
                blocks=[],
            )
            plans.append(current)
        elif current is not None:
            current.blocks.append(block)
        else:
            preamble.append(block)

    # 第一个标题之前的内容按个人信息处理（常见于没有“个人信息”标题的简历）
    if preamble:
        plans.insert(0, SectionPlan(type=SectionType.personal_info.value, title="", blocks=preamble))

    # 完全没有任何标题：保留为“其他”，至少不丢内容
    if not plans:
        if blocks:
            plans.append(SectionPlan(type=SectionType.other.value, title="简历内容", blocks=list(blocks)))

    return [p for p in plans if p.blocks]


def merge_sections(plans: list[SectionPlan]) -> list[SectionPlan]:
    """同类型合并；other 按原标题区分，不同标题不合并、不丢弃。"""
    merged: list[SectionPlan] = []
    index: dict[tuple[str, str], SectionPlan] = {}

    for plan in plans:
        key = (plan.type, plan.title if plan.type == SectionType.other.value else "")
        existing = index.get(key)
        if existing is None:
            existing = SectionPlan(type=plan.type, title=plan.title, blocks=[])
            index[key] = existing
            merged.append(existing)
        existing.blocks.extend(plan.blocks)

    return [p for p in merged if p.blocks]
