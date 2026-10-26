"""诊断 agent 的结构化输出。

一条诊断 = 位置 + 原文片段 + 为什么改 + 事实依据 + 修改方向。

坐标只在后端流转（诊断 → 优化 agent），前端只展示文字，不展示 s/r/c/i。
`quote` 只保留原文开头的一小段：优化 agent 拿到的是完整标记文本，不需要重复整段。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# quote 最多保留的字符数：够定位、够前端展示，又不会把整段经历塞进结构化结果
QUOTE_MAX_LEN = 60


class DiagnosisItem(BaseModel):
    """一条诊断。kind=text 用坐标定位；kind=structure 是无坐标的结构问题。"""

    kind: Literal["text", "structure"] = Field(
        ...,
        description=(
            "text = 问题落在某段已有文字上，必须给 s/r/c/i 和 quote；"
            "structure = 增删章节、调整顺序、排版、图片等无法用坐标表示的问题，坐标和 quote 留空"
        ),
    )
    s: int | None = Field(None, description="kind=text 时必填：章节序号（0 起）")
    r: int | None = Field(None, description="kind=text 时必填：章节内叶子窗口序号（0 起）")
    c: int | None = Field(None, description="kind=text 时必填：窗口内可改内容序号（0 起）")
    i: int | None = Field(None, description="kind=text 时必填：内容内文字单元序号（0 起）")
    quote: str = Field(
        "",
        description=(
            "kind=text 时必填：该坐标当前正文的开头片段，最多 60 字，逐字来自简历；"
            "纯文本，不要加 Markdown 标记（**、`、列表符号），否则优化阶段核对不上；"
            "kind=structure 时留空"
        ),
    )
    reason: str = Field(..., description="为什么这个位置的内容需要改动：缺什么、问题是什么")
    evidence: str = Field(..., description="事实依据：简历原文、JD 要求或用户回答中的具体内容")
    suggestion: str = Field(..., description="修改方向：往哪个方向改；只给方向，不写最终成品")

    @field_validator("quote")
    @classmethod
    def _trim_quote(cls, value: str) -> str:
        """超长原文只留开头一段，避免结构化结果过大。"""
        return (value or "").strip()[:QUOTE_MAX_LEN]


class DiagnosisResult(BaseModel):
    """诊断 agent 的完整输出。"""

    items: list[DiagnosisItem] = Field(..., description="诊断项列表，按重要性排序")
