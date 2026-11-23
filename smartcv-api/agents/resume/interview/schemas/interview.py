"""面试过程运行时实体。

问题卡由 question_card.py 定义；这里只放面试官轮次、作答记录、
讲解事件与 LangGraph 状态。
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import Field

from agents.resume.interview.schemas.base import (
    FollowDepth,
    FollowLevel,
    InterviewModel,
    Scene,
    now_iso,
)


class InterviewerTurn(InterviewModel):
    """面试官对一轮回答的评价与下一步决策。"""

    off_topic: bool = Field(False, description="回答是否明显答非所问")
    leaks: list[str] = Field(default_factory=list, description="命中的露馅信号")
    feedback: str = Field(
        "",
        description="给候选人的改进建议：先具体肯定，再给最多一条可选补充；"
        "回答已经完整时可留空，不要硬找问题",
    )
    decision: Literal["follow_up", "next_card", "end"] = Field(
        "follow_up", description="继续追问 / 下一题 / 结束"
    )
    followup_id: str = Field("", description="选择的预设追问 id；动态追问时留空")
    dynamic_question: str = Field("", description="需要动态追问时填完整问题")
    dynamic_level: FollowLevel = Field("L2", description="动态追问级别")
    dynamic_reason: Literal["", "new_anchor", "contradiction", "metric_anomaly", "shallow"] = Field(
        "", description="动态追问的触发原因；预设追问留空"
    )
    dynamic_anchor_id: str = Field("", description="动态追问关联的锚点")
    coverage_complete: bool = Field(False, description="当前卡考察点是否已覆盖")
    card_summary: str = Field("", description="本题小结，供下一题参考")


class AnswerRecord(InterviewModel):
    card_id: str = Field("")
    question: str = Field("", description="本轮实际被问到的问题")
    answer: str = Field("", description="用户回答；跳过时为空")
    source: Literal["main", "followup", "reanswer", "skip"] = Field("main")
    level: FollowLevel | None = Field(None)
    leaks: list[str] = Field(default_factory=list)
    off_topic: bool = Field(False)
    feedback: str = Field("")
    sample_answer: str = Field(
        "", description="根据本轮改进建议生成的简短示例回答；未生成或跳过时为空"
    )
    skipped: bool = Field(False)
    created_at: str = Field(default_factory=now_iso)


class TeachingTurn(InterviewModel):
    role: Literal["user", "teacher"] = Field("user")
    content: str = Field("")


class TokenUsage(InterviewModel):
    """一次或一组模型调用的 token 汇总；前端在阶段旁展示。"""

    input_tokens: int = Field(0, description="输入 token")
    output_tokens: int = Field(0, description="输出 token")
    total_tokens: int = Field(0, description="输入 + 输出")
    calls: int = Field(0, description="模型调用次数")


class TeachingEvent(InterviewModel):
    card_id: str = Field("")
    question: str = Field("")
    turns: list[TeachingTurn] = Field(default_factory=list)
    outcome: Literal["active", "returned", "skipped"] = Field("active")
    started_at: str = Field(default_factory=now_iso)
    ended_at: str = Field("")


class InterviewStateView(InterviewModel):
    """GET /api/interview/state 的只读视图；不含整份问题包与参考答案。"""

    thread_id: str = ""
    scene: Scene = "project"
    follow_depth: FollowDepth | None = Field(None, description="追问强度：normal / deep")
    phase: Literal["interviewing", "teaching", "finished"] = "interviewing"
    current_card_id: str = ""
    current_question: str = ""
    current_level: FollowLevel | None = None
    index: int = 0
    total: int = 0
    dynamic_count: int = 0
    followup_used: dict[str, int] = Field(default_factory=dict)
    records: list[AnswerRecord] = Field(default_factory=list)
    skipped_cards: list[str] = Field(default_factory=list)
    teaching: list[TeachingEvent] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage, description="本场累计 token 用量")
    finished_reason: str = ""


class InterviewState(TypedDict, total=False):
    """LangGraph 状态；只放本模块自己的字段，消息历史不进检查点。

    注意：节点写入的每个 key 都必须在这里声明成 channel，否则 LangGraph 会
    静默丢弃。字段分三组：本轮输入、建场上下文、面试进度。
    """

    # ---- 本轮输入：START 按 action 分发，节点执行完会清空 ----
    action: str  # answer / skip / skip_followup / teach / teach_message / return / end，决定走哪个节点
    answer: str  # 本轮回答正文；仅 answer 节点读取
    message: str  # 讲解模式下的用户追问；仅 teach_message 节点读取

    # ---- 建场上下文：create_thread 写入，之后只读 ----
    thread_id: str  # 线程 id；读检查点时用于确认拿到的确实是本线程
    owner_session: str  # 浏览器会话 id；防止换一个页面就读到别人的面试
    use_mode: str  # dialog；清单自测不建场，后端出题也不依赖它
    scene: str  # project / comprehensive；决定面试官提示词与复盘口径
    follow_depth: str  # normal / deep / ""；只影响面试官的追问强度
    focus: str  # business / tech / architecture / review；综合面试为 balanced，约束追问方向
    profile: dict  # 用户确认后的 ResumeProfile；出题与参考答案的唯一事实来源
    anchors: list[dict]  # Anchor 列表；追问方向与事实校验的原文依据
    cards: list[dict]  # QuestionCard 列表；动态追问会原地写回对应卡片的 dynamic_questions

    # ---- 面试进度 ----
    phase: str  # interviewing / teaching / finished；控制可选动作与前端视图
    current_card_id: str  # 当前题卡 id；为空表示题目已出完、等待进 finish
    current_question: str  # 当前实际问的问题（可能是追问）；为空表示还没出题
    current_level: str  # 当前问题级别 L1/L2/L3；主问题为空
    current_is_dynamic: bool  # 当前问题是否为面试官临场生成的动态追问
    current_followup_id: str  # 当前预设追问 id；主问题或动态追问为空
    asked_followups: list[str]  # 已问过的预设追问 id，避免同一条追问反复出现
    followup_used: dict[str, int]  # {cardId: 已追问次数}，用于单卡追问上限
    dynamic_count: int  # 本场动态追问总数，用于每场上限与复盘统计
    consecutive_off_topic: int  # 连续答非所问次数，达到阈值后强制换题
    reanswer_pending: bool  # 重答标记；下一轮记录记作 reanswer
    usage: dict  # 本场累计 token 用量；每次模型调用后累加
    done_card_ids: list[str]  # 已答完或跳过的题卡 id，决定进度与下一题
    skipped_cards: list[str]  # 被跳过的题卡 id，复盘里单独标注
    records: list[dict]  # AnswerRecord 列表；每轮评估追加到这里
    teaching_events: list[dict]  # TeachingEvent 列表；保存讲解对话、结局与时间
    progress_digest: list[str]  # 最近 12 条进度摘要，供面试官续接上下文
    finished_reason: str  # all_done / user_end；前端据此映射结束文案

    # ---- 流程协调（不参与出题，但必须是 channel） ----
    started: bool  # 是否已发过 interview.started，避免每轮 action 重复推送
    finish_pending: bool  # answer / skip 之后的条件边据此决定是否进 finish 节点
