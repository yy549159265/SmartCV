"""简历画像与证据锚点实体。

画像只概括简历里已有的事实；锚点的 `quote` 由后端按 `refs` 回查原文后填入，
模型只输出坐标。
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from agents.resume.interview.schemas.base import (
    AnchorKind,
    InterviewModel,
    Refs,
    TechLevel,
)


class TechStackItem(InterviewModel):
    name: str = Field("", description="技术名称，必须来自简历原文")
    level: TechLevel = Field("掌握", description="简历体现的掌握程度：精通 / 熟练 / 掌握")
    refs: Refs = Field(
        default_factory=list,
        description="支撑该等级的简历坐标列表，如 [[0,1,0,0]]；只写坐标，不复制原文",
    )
    quote: SkipJsonSchema[str] = Field(
        "", description="后端按 refs 解析出的原文，模型不要填写"
    )

    @field_validator("level", mode="before")
    @classmethod
    def _level_fallback(cls, value):
        # 模型偶尔写「熟悉 / 了解」；按设计统一降为「掌握」，不因此丢掉整份画像。
        return value if value in ("精通", "熟练", "掌握") else "掌握"


class ProjectItem(InterviewModel):
    id: str = Field("", description="项目 id，可为空，由后端按顺序补全")
    name: str = Field("", description="项目名称")
    intro: str = Field("", description="项目介绍 / 背景")
    role: str = Field("", description="项目角色")
    tech_stack: list[str] = Field(default_factory=list, description="项目使用的技术栈")
    highlights: list[str] = Field(
        default_factory=list,
        description="项目经历里的每个小点，一条一个字符串（不要合并成一段）",
    )


class Anchor(InterviewModel):
    id: str = Field("", description="锚点 id，可为空，由后端补全")
    kind: AnchorKind = Field(..., description="锚点类型")
    refs: Refs = Field(
        default_factory=list,
        description="简历原文坐标列表，如 [[0,3,1,0]]；只写坐标，不复制原文",
    )
    quote: SkipJsonSchema[str] = Field(
        "", description="后端按 refs 解析出的原文，模型不要填写；解析失败时锚点会被丢弃"
    )
    project_id: str = Field("", description="所属项目 id；不属于具体项目时为空")
    follow_directions: list[str] = Field(
        default_factory=list, description="可追问方向，例如「QPS 怎么测的」「方案取舍」"
    )


class ResumeProfile(InterviewModel):
    direction: str = Field("", description="职业方向")
    intro: str = Field("", description="个人简介，只能概括简历里已有的事实")
    intro_refs: Refs = Field(
        default_factory=list, description="支撑个人简介的简历坐标列表"
    )
    tech_stacks: list[TechStackItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)


class ProfileExtraction(InterviewModel):
    """简历分析 Agent 的一次结构化输出。"""

    direction: str = Field("", description="职业方向")
    intro: str = Field("", description="个人简介，1~3 句，只概括简历里已有的事实")
    intro_refs: Refs = Field(
        default_factory=list, description="支撑个人简介的简历坐标列表"
    )
    tech_stacks: list[TechStackItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    anchors: list[Anchor] = Field(default_factory=list)
