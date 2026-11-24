"""面试模块的接口输入。

API 边界用 camelCase（`InterviewModel` 统一挂 alias_generator），
图状态与提示词输入继续使用 snake_case。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from agents.resume.interview.schemas.base import (
    Action,
    FollowDepth,
    FollowLevel,
    InterviewFocus,
    InterviewModel,
    PackScene,
    Scene,
    UseMode,
)
from agents.resume.interview.schemas.question_card import QuestionCard
from agents.resume.interview.schemas.resume import Anchor, ResumeProfile
from schemas.provider import ProviderConfig


class ProfileRequest(InterviewModel):
    """POST /api/interview/profile：分析简历，产出画像与证据锚点。"""

    resume: list[dict] = Field(
        ...,
        min_length=1,
        description="简历编辑器的原始块；引用坐标 [s,r,c,i] 以它为基准解析出原文",
    )
    provider: ProviderConfig = Field(
        ...,
        description="本次请求自带的模型配置；API Key 只在请求内使用，不落库",
    )


class PackRequest(InterviewModel):
    """POST /api/interview/pack：按场景出题。

    第 3 步生成一份题包，对话面试与清单自测共用；题量由模型按证据量决定。
    排查面试不使用项目选择、考察方向与追问强度，由后端按三类题型分组出题。
    """

    provider: ProviderConfig
    profile: ResumeProfile = Field(
        ..., description="用户确认后的画像；出题与参考答案的唯一事实来源"
    )
    anchors: list[Anchor] = Field(
        default_factory=list,
        description="画像里保留的证据锚点；追问方向与事实校验都引用它的原文",
    )
    scene: PackScene = Field(
        "project", description="project / comprehensive / scenario"
    )
    follow_depth: FollowDepth | None = Field(
        None, description="仅项目面试使用：normal 常规 / deep 深度追问"
    )
    focus: InterviewFocus = Field(
        "balanced",
        description="项目面试考察方向（可选）：business 业务场景 / tech 实现细节 / architecture 架构设计 / review 复盘决策；不传为 balanced 混合出题",
    )
    project_ids: list[str] = Field(
        default_factory=list, description="项目面试选中的单个项目 id"
    )


class AnswerRequest(InterviewModel):
    """POST /api/interview/reference-answer：为一张卡生成主问题参考答案。

    进入清单后按卡片调用，不参与题包生成。画像依据充足时按事实作答；
    依据不足时保留 missingInfo，同时给出一份带显式假设的示范答案。
    """

    provider: ProviderConfig
    profile: ResumeProfile = Field(
        ..., description="用户确认后的画像；优先使用其中的项目、技术栈与事实"
    )
    anchors: list[Anchor] = Field(default_factory=list, description="可追溯的证据锚点")
    card: QuestionCard = Field(..., description="需要补参考答案的题卡")


class FollowUpAnswersRequest(InterviewModel):
    """POST /api/interview/follow-up-answers：为一张卡的追问生成示范答案。

    与 `AnswerRequest` 共用同一套依据判断：能落到画像事实就按事实写，
    依据不足时保留缺口并给出带显式假设的示范答案。一次只处理要求的追问 id，
    不重新出题，也不改主问题参考答案。
    """

    provider: ProviderConfig
    profile: ResumeProfile
    anchors: list[Anchor] = Field(default_factory=list)
    card: QuestionCard
    follow_up_ids: list[str] = Field(
        default_factory=list,
        description="需要补答案的 FollowUp.id；为空时处理卡片里的全部追问",
    )


class FollowUpAddRequest(InterviewModel):
    """POST /api/interview/follow-up：按用户方向为一张卡新增一条追问。

    用户只给方向，不指定层级；由模型结合已有追问链判断补到 L1 / L2 / L3，
    返回带新 id 的追问对象。只追加，不改动已有追问与参考答案。
    """

    provider: ProviderConfig = Field(..., description="本次请求自带的模型配置")
    profile: ResumeProfile = Field(
        ..., description="候选人画像；新追问只能基于这里已有的事实"
    )
    anchors: list[Anchor] = Field(
        default_factory=list, description="画像里保留的证据锚点"
    )
    card: QuestionCard = Field(..., description="要补追问的问题卡，含已有追问链")
    instruction: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户想追问的方向，自然语言即可；不需要指定层级",
    )

    @field_validator("instruction", mode="before")
    @classmethod
    def _strip_instruction(cls, value):
        return value.strip() if isinstance(value, str) else value


class SampleAnswerRequest(InterviewModel):
    """内部调用：根据本轮作答评价生成一段简短示例回答。

    画像、题卡、作答与评价都由检查点还原后填入；provider 由调用方单独传入。
    """

    profile: ResumeProfile
    anchors: list[Anchor] = Field(default_factory=list)
    card: QuestionCard
    question: str = Field(..., min_length=1, description="本轮实际被问到的问题，可能是追问")
    level: FollowLevel | None = Field(None, description="追问级别；主问题为空")
    answer: str = Field("", description="用户本轮的原始回答")
    feedback: str = Field("", description="评价里给出的改进建议")
    leaks: list[str] = Field(default_factory=list, description="评价里没讲到的关键点")


class SampleAnswerHttpRequest(InterviewModel):
    """POST /api/interview/sample-answer：按一段已记录的作答生成示例回答。

    前端只传线程与定位信息；画像、题卡、原始回答与评价都由后端从检查点读取，
    避免示例回答基于前端传来的旧数据。
    """

    provider: ProviderConfig = Field(..., description="本次请求自带的模型配置")
    thread_id: str = Field(..., min_length=1, description="面试线程 id")
    card_id: str = Field("", description="本轮评价对应的题卡 id；为空时取最近一条记录")
    question: str = Field("", description="本轮实际被问到的问题；用于在同一张卡里定位具体一轮")


class ContentEditRequest(InterviewModel):
    """POST /api/interview/edit：一段 JSON + 修改思路 -> 同结构的改好内容。

    `scene` 选择 `prompts/general/<scene>.md`；当前用于画像锚点与追问，后续
    项目简介、技术栈等位置可直接复用，不需要新增接口。
    """

    provider: ProviderConfig = Field(..., description="本次请求自带的模型配置")
    scene: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="编辑场景，对应 prompts/general/<scene>.md；决定本次使用的提示词片段",
    )
    instruction: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户想怎么改，自然语言即可",
    )
    content: dict[str, Any] = Field(
        ...,
        description="要修改的内容实体；字段由调用方决定，返回时保持同一组顶层键",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="调用方补充的上下文，如所属项目、简历原文；不参与回填",
    )
    locked_fields: list[str] = Field(
        default_factory=list,
        description="不允许模型改写的字段名；通常用于 id、原文引用等证据字段",
    )

    @field_validator("instruction", mode="before")
    @classmethod
    def _strip_instruction(cls, value):
        return value.strip() if isinstance(value, str) else value


class ThreadRequest(InterviewModel):
    """POST /api/interview/thread：出题后选对话面试，再创建检查点。"""

    profile: ResumeProfile = Field(
        ..., description="用户确认后的画像；建场后作为面试官反馈与追问的唯一事实来源"
    )
    anchors: list[Anchor] = Field(
        default_factory=list, description="画像里保留的证据锚点"
    )
    cards: list[QuestionCard] = Field(
        ..., min_length=1, description="已生成的问题卡；建场只读取它，不重新出题"
    )
    scene: Scene = Field(
        "project", description="出题场景：project / comprehensive / scenario"
    )
    follow_depth: FollowDepth | None = Field(
        None, description="仅项目面试使用：normal 常规 / deep 深度追问"
    )
    focus: InterviewFocus = Field(
        "balanced",
        description="项目面试考察方向：business / tech / architecture / review；综合面试为 balanced",
    )
    use_mode: UseMode = Field(
        "dialog", description="只有 dialog 会创建线程；清单自测在浏览器端消费问题卡"
    )


class StreamRequest(InterviewModel):
    """POST /api/interview/stream：推进一轮面试或讲解，以 SSE 返回事件。"""

    thread_id: str = Field(
        ...,
        min_length=1,
        description="检查点线程 id；决定读取哪一场面试的进度",
    )
    action: Action = Field(
        ...,
        description="answer / skip / skip_followup / reanswer / teach / teach_message / return / end，决定进入哪个图节点",
    )
    answer: str = Field(
        "", max_length=4000, description="本轮作答；action=answer 时必填"
    )
    message: str = Field(
        "", max_length=2000, description="讲解模式下的追问；action=teach_message 时使用"
    )
    provider: ProviderConfig
