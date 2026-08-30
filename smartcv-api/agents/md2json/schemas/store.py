"""简历解析任务的步骤化状态存储 + 全局注册表。

按 session_id 存一份 PDF2ResumeStore，前端上传后轮询 /api/resume/parse/status
拿到各固定步骤的状态，展示进度；用户刷新/断开时服务端置为 cancelled。
"""

from enum import IntEnum
from typing import Literal

from cachetools import TTLCache
from pydantic import BaseModel, Field

from agents.md2json.schemas.resume import Resume


class Step(IntEnum):
    """解析全流程的固定步骤，值 = 该步骤在 steps 里的索引。

    代码里引用步骤一律用成员名（如 Step.UPLOAD），改展示文案只动 STEP_NAMES，
    不牵连调用点。
    """

    UPLOAD = 0  # 文件上传与校验
    PARSE = 1  # 正在解析简历为 MarkDown 格式
    ORGANIZE = 2  # 正在使用 Agent 整理 MarkDown 简历
    CONVERT = 3  # 正在使用 Agent 转换 MarkDown 简历为 Json
    DONE = 4  # 完成


# 步骤展示名，顺序与 Step 一一对应；前端弹窗显示的就是这些文案，要改只改这里
STEP_NAMES = [
    "文件上传与校验",
    "正在解析简历为 MarkDown 格式",
    "正在使用 Agent 整理 MarkDown 简历",
    "正在使用 Agent 转换 MarkDown 简历为 Json",
    "完成",
]


class StepStatus(BaseModel):
    name: str
    status: Literal["pending", "running", "done", "failed"] = "pending"


class PDF2ResumeStore(BaseModel):
    state: Literal["pending", "running", "done", "failed", "cancelled"] = "pending"
    session_id: str | None = None
    markdown: str | None = None  # 整理后的标记文本（generate_resume 收到时写入）
    content: Resume | None = None
    error: str | None = None
    steps: list[StepStatus] = Field(default_factory=list)

    def start_step(self, step: Step) -> None:
        self.steps[step.value].status = "running"
        self.state = "running"

    def finish_step(self, step: Step) -> None:
        self.steps[step.value].status = "done"

    def fail_step(self, step: Step, error: str) -> None:
        self.steps[step.value].status = "failed"
        self.error = error
        self.state = "failed"

    def complete(self) -> None:
        self.state = "done"
        self.finish_step(Step.DONE)

    def cancel(self) -> None:
        self.state = "cancelled"
        self.error = "已中断"


# ---- 全局注册表：按 session_id 存一份，供前端轮询状态 ----
# 用内存级 TTL 缓存（类似 Redis 的 EXPIRE）：每条 10 分钟过期自动删除，
# 满容量自动逐出最旧，无需手动定时清理。
_JOB_TTL_SECONDS = 600  # 10 分钟
_MAX_JOBS = 200
_JOBS: TTLCache = TTLCache(maxsize=_MAX_JOBS, ttl=_JOB_TTL_SECONDS)


def create_store(session_id: str) -> PDF2ResumeStore:
    store = PDF2ResumeStore(
        session_id=session_id,
        steps=[StepStatus(name=n) for n in STEP_NAMES],
    )
    _JOBS[session_id] = store
    return store


def get_store(session_id: str | None) -> PDF2ResumeStore | None:
    if not session_id:
        return None
    return _JOBS.get(session_id)
