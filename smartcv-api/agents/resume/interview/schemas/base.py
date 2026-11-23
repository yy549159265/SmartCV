"""模拟面试数据模型的公共基类、引用坐标与枚举。

实体按领域拆分：
  resume.py        简历画像与证据锚点
  question_card.py 问题卡与参考答案
  interview.py     面试过程运行时实体
  requests.py      接口输入
  responses.py     模型与接口输出
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict
from pydantic.alias_generators import to_camel

from agents.utils.resume import normalize_refs

# 引用坐标：[s, r, c, i]，依次是章节 / 叶子窗口 / 文字内容 / 文字单元。
# 模型只输出坐标，原文由后端 `resolve_refs` 解析并逐字核对。
Coord = list[int]
Refs = Annotated[list[Coord], BeforeValidator(normalize_refs)]

TechLevel = Literal["精通", "熟练", "掌握"]
AnchorKind = Literal["tech", "result", "architecture", "metric", "contribution"]
UseMode = Literal["dialog", "checklist"]
# 出题场景只有项目面试与综合面试；checklist 是生成之后选择的消费方式，
# 不再是场景。这里保留该值只为兼容升级前保存在浏览器里的旧题包。
Scene = Literal["project", "comprehensive", "checklist"]
PackScene = Literal["project", "comprehensive"]
# 追问强度：normal 正常交流，deep 追问更直接、更关注依据与个人贡献。
FollowDepth = Literal["normal", "deep"]
# 项目面试的考察方向；可选项，balanced 表示不限定方向、保持混合出题，
# 综合面试与升级前的旧题包也使用该值。
InterviewFocus = Literal["balanced", "business", "tech", "architecture", "review"]
FollowLevel = Literal["L1", "L2", "L3"]
Dimension = Literal[
    "project_background",
    "business_need",
    "architecture",
    "implementation",
    "difficulty",
    "problem_solving",
    "result",
    "contribution",
    "tech_stack",
    "motivation",
    "career_plan",
    "salary",
    "stability",
    "authenticity",
]
Priority = Literal["high", "medium", "low"]
Action = Literal[
    "answer",
    "skip",
    "skip_followup",
    "reanswer",
    "teach",
    "teach_message",
    "return",
    "end",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InterviewModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        extra="ignore",
    )
