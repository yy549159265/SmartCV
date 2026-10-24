"""简历解析任务的步骤化状态存储 + 全局注册表。

按 session_id 存一份 PDF2ResumeStore，前端上传后轮询 /api/resume/parse/status
拿到各固定步骤的状态，展示进度。

隐私约束：这里只存步骤状态和错误文案，不存 Markdown、简历正文或解析结果。
请求结束（成功/失败/取消）后调用 delete_store 立即删除。
"""

from enum import IntEnum
from typing import Literal

from cachetools import TTLCache
from pydantic import BaseModel, Field


class Step(IntEnum):
    """解析全流程的固定步骤，值 = 该步骤在 steps 里的索引。

    代码里引用步骤一律用成员名（如 Step.UPLOAD），改展示文案只动 STEP_NAMES，
    不牵连调用点。
    """

    UPLOAD = 0  # 文件上传与校验
    PARSE = 1  # 正在解析简历为 MarkDown 格式
    CLEAN = 2  # 正在清洗解析结果
    SEGMENT = 3  # 正在识别简历章节
    CONVERT = 4  # 正在生成简历 JSON
    VALIDATE = 5  # 正在校验内容完整性
    DONE = 6  # 完成


# 步骤展示名，顺序与 Step 一一对应；前端弹窗显示的就是这些文案，要改只改这里
STEP_NAMES = [
    "文件上传与校验",
    "正在解析简历为 MarkDown 格式",
    "正在清洗解析结果",
    "正在识别简历章节",
    "正在生成简历 JSON",
    "正在校验内容完整性",
    "完成",
]


class StepStatus(BaseModel):
    name: str
    status: Literal["pending", "running", "done", "failed"] = "pending"


class PDF2ResumeStore(BaseModel):
    state: Literal["pending", "running", "done", "failed", "cancelled"] = "pending"
    session_id: str | None = None
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
# 满容量自动逐出最旧，无需手动定时清理。请求结束后还会主动 delete_store。
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


def delete_store(session_id: str | None, store: PDF2ResumeStore | None = None) -> None:
    """请求结束后立即删除，服务端不保留本次解析的任何状态。

    传 store 时只在注册表里还是同一份对象时才删，避免并发/重试请求
    互相删掉对方刚创建的进度。
    """
    if not session_id:
        return
    if store is not None and _JOBS.get(session_id) is not store:
        return
    _JOBS.pop(session_id, None)
