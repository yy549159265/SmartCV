"""问题卡与参考答案实体。

问题卡是对话面试与清单自测的唯一题源；出题阶段只生成问题，不生成答案。
参考答案在进入清单后由用户主动触发生成；依据不足时保留缺口并给出带显式假设的
示范答案，不再区分「来源」或「状态」——所有答案都是供用户对照的示范内容。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from agents.resume.interview.schemas.base import (
    Dimension,
    FollowLevel,
    InterviewModel,
    Priority,
)


class ReferenceAnswer(InterviewModel):
    thinking: str = Field("", description="回答思路：先讲什么、如何组织")
    answer: str = Field(
        "",
        description=(
            "示范回答正文，必须完整；无法由简历事实支撑的部分，"
            "要在 assumptions 中逐条写明假设"
        ),
    )
    key_points: list[str] = Field(default_factory=list, description="回答关键点")
    missing_info: list[str] = Field(
        default_factory=list,
        description="简历里缺少哪些回答所需的证据；没有缺口时为空",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="为补全答案所做的假设；逐条写明，不要把假设当成简历事实",
    )


def normalize_follow_level(value: object) -> str:
    """把模型返回的层级说明收敛成 L1 / L2 / L3。

    模型偶尔把说明一起写进级别（如「L3 归因」「l3」）。只认前缀，
    不要静默降成 L1，否则 L3 占比会随机不足、整包校验偶发失败。
    """
    text = str(value or "").strip().upper()
    if text.startswith("L3") or text == "3" or "归因" in text or "反事实" in text:
        return "L3"
    if text.startswith("L2") or text == "2" or "权衡" in text or "取舍" in text:
        return "L2"
    return "L1"


class FollowUp(InterviewModel):
    id: str = Field("", description="追问 id，可为空，由后端补全")
    level: FollowLevel = Field(..., description="追问级别，只填 L1、L2 或 L3")
    question: str = Field(..., description="追问本身，一句完整的问题")
    intent: str = Field("", description="该追问想验证什么")
    reference_answer: SkipJsonSchema[ReferenceAnswer] = Field(
        default_factory=ReferenceAnswer,
        description="进入清单后单独生成的 AI 示范答案；不参与出题结构化输出",
    )

    @field_validator("level", mode="before")
    @classmethod
    def _level_fallback(cls, value):
        return normalize_follow_level(value)


class FollowUpAnswer(InterviewModel):
    follow_up_id: str = Field(..., description="对应的 FollowUp.id")
    answer: ReferenceAnswer = Field(..., description="该追问的 AI 示范答案")


class FollowUpAnswerSet(InterviewModel):
    answers: list[FollowUpAnswer] = Field(default_factory=list)


class DynamicQuestion(InterviewModel):
    id: str = Field("", description="动态追问 id")
    question: str = Field(..., description="动态追问正文")
    level: FollowLevel = Field("L2", description="动态追问级别")
    anchor_id: str = Field("", description="关联的证据锚点")
    reason_type: Literal["new_anchor", "contradiction", "metric_anomaly", "shallow"] = Field(
        ..., description="允许动态追问的触发原因"
    )
    source_index: int = Field(0, description="由第几轮回答触发，用于追溯")


class QuestionCard(InterviewModel):
    id: str = Field("", description="问题卡 id，可为空，由后端补全")
    project_id: str = Field("", description="所属项目 id")
    anchor_id: str = Field("", description="对应的证据锚点 id")
    dimension: Dimension = Field("implementation", description="考察维度")
    priority: Priority = Field("medium", description="优先级")
    main_question: str = Field(..., description="主问题")
    follow_ups: list[FollowUp] = Field(
        ..., min_length=3, description="L1/L2/L3 追问链，至少 3 条"
    )
    evidence_quote: str = Field("", description="对应的简历原文引用")
    intent: str = Field("", description="考察意图")
    reference_answer: SkipJsonSchema[ReferenceAnswer] = Field(
        default_factory=ReferenceAnswer,
        description="进入清单后由用户主动触发、单独生成的 AI 示范答案",
    )
    leak_signals: list[str] = Field(
        ..., min_length=2, description="露馅信号，至少 2 条且要可操作"
    )
    coverage: list[str] = Field(default_factory=list, description="覆盖的考察点")
    dynamic_questions: list[DynamicQuestion] = Field(
        default_factory=list, description="面试过程中追加的动态追问"
    )


class PackGroupResult(InterviewModel):
    """问题生成 Agent 针对一个分组（项目 / 综合主题）的结构化输出。"""

    cards: list[QuestionCard] = Field(default_factory=list)
