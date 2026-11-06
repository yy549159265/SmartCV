"""诊断 agent 的结构化输出。

一条诊断 = 位置 + 原文片段 + 为什么改 + 事实依据 + 修改方向 + 处理档位。

坐标只在后端流转（诊断 → 优化 agent），前端只展示文字，不展示 s/r/c/i。
`quote` 只保留原文开头的一小段：优化 agent 拿到的是完整标记文本，不需要重复整段。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# quote 最多保留的字符数：够定位、够前端展示，又不会把整段经历塞进结构化结果
QUOTE_MAX_LEN = 60

class DiagnosisItem(BaseModel):
    """一条诊断。每条都必须落在简历里已有的一段文字上，用 s/r/c/i 定位。"""

    # 处理档位：诊断 agent 对「这条结论要不要改」的第一层判断。
    # 优化 agent 据此决定审查重点：must/suggest 走收益判定，keep/insufficient 直接 skip。
    disposition: Literal["must", "suggest", "keep", "insufficient"] = Field(
        "suggest",
        description=(
            "本条结论的处理档位：\n"
            "must = 必须修改：事实错误、时间/学历/职位矛盾、关键信息缺失（时间/公司/职责），或与 JD 硬性要求明显不符、明显病句/错别字；\n"
            "suggest = 建议修改：原文没有硬伤，但改后表达更专业、更量化、更贴合 JD，收益明确；\n"
            "keep = 可以保留：原文已经清晰、准确、专业，无需修改（明确判定不改，而不是为改而改）；\n"
            "insufficient = 信息不足：缺少必要信息，无法判断该不该改或往哪改，需要先向用户确认"
        ),
    )
    # 坐标保留可空：结构化输出偶发缺字段时不至于让整份诊断失败，
    # 优化阶段会把这些条目判为不可执行（见 tools.can_patch）。正常情况下必须全部给出。
    s: int | None = Field(None, description="章节序号（0 起）")
    r: int | None = Field(None, description="章节内叶子窗口序号（0 起）")
    c: int | None = Field(None, description="窗口内可改内容序号（0 起）")
    i: int | None = Field(None, description="内容内文字单元序号（0 起）")
    quote: str = Field(
        "",
        description=(
            "该坐标当前正文的开头片段，最多 60 字，逐字来自简历；"
            "纯文本，不要加 Markdown 标记（**、`、列表符号），否则优化阶段核对不上"
        ),
    )
    reason: str = Field(..., description="为什么这个位置的内容需要改动：缺什么、问题是什么")
    evidence: str = Field(..., description="事实依据：简历原文、JD 要求或用户回答中的具体内容")
    suggestion: str = Field(..., description="修改方向：往哪个方向改；只给方向，不写最终成品")
    reference: str = Field(
        "",
        description=(
            "若本条诊断参考了优秀示例，写「示例 N：可迁移的写法特征」（只写写法，不写示例事实）；"
            "没有参考时留空"
        ),
    )

    @field_validator("quote")
    @classmethod
    def _trim_quote(cls, value: str) -> str:
        """超长原文只留开头一段，避免结构化结果过大。"""
        return (value or "").strip()[:QUOTE_MAX_LEN]


class DiagnosisResult(BaseModel):
    """诊断 agent 的完整输出。"""

    items: list[DiagnosisItem] = Field(..., description="诊断项列表，按重要性排序")
    style_notes: list[str] = Field(
        default_factory=list,
        description=(
            "从优秀示例提炼的可迁移写作规范（3~6 条）：只描述怎么写，"
            "不包含公司、数字、技术栈、成果等任何事实；未选择示例时为空"
        ),
    )
