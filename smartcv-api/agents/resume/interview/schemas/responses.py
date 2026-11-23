"""面试模块的模型输出与接口输出。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, field_validator

from agents.resume.interview.schemas.base import FollowLevel, InterviewModel
from agents.resume.interview.schemas.question_card import (
    FollowUp,
    normalize_follow_level,
)


class ContentEditOutput(InterviewModel):
    """内容编辑模型的一次结构化输出。"""

    content: dict[str, Any] = Field(
        ..., description="修改后的完整内容对象，键与输入保持一致"
    )
    summary: str = Field("", description="一句话说明改了什么；没有改动时写「未做修改」")

    @field_validator("content", mode="before")
    @classmethod
    def _parse_content(cls, value):
        # 部分供应商会把嵌套对象序列化成字符串再放进参数里。
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return value
            if isinstance(parsed, dict):
                return parsed
        return value


class ContentEditResult(InterviewModel):
    """接口返回：合并并锁定字段后的最终内容。"""

    content: dict[str, Any] = Field(..., description="可直接回填的内容")
    summary: str = Field("", description="修改摘要")


class FollowUpDraft(InterviewModel):
    """新增追问的模型输出：层级由模型按方向判断，id 由后端补全。"""

    level: FollowLevel = Field(
        ..., description="追问层级；按需要问到的深度选 L1、L2 或 L3"
    )
    question: str = Field(..., min_length=1, description="一句完整、可直接提出的追问")
    intent: str = Field("", description="这条追问想验证什么")
    summary: str = Field("", description="一句话说明补到了哪一层、补了什么角度")

    @field_validator("level", mode="before")
    @classmethod
    def _level_fallback(cls, value):
        return normalize_follow_level(value)


class FollowUpAddResult(InterviewModel):
    """接口返回：已补好 id 的新追问与改动摘要。"""

    follow_up: FollowUp = Field(..., description="可直接追加到追问链的新追问")
    summary: str = Field("", description="改动摘要")


class SampleAnswer(InterviewModel):
    """根据一轮作答评价里的改进建议生成的简短示例回答。"""

    answer: str = Field(
        ...,
        description="第一人称、可直接说出口的简短示范回答；纯文本，不含 Markdown",
    )
