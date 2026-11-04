"""Chat 任务的 TTL 存储 + SSE 事件通道。

仿照 agents/md2json/schemas/store.py 的 TTLCache 注册表：按 session_id 存一份
ChatTask，10 分钟过期自动清理。每个任务持有一个 asyncio.Queue 做背压（生产端
await put 会因队列满被堵住，从而反向压制 LLM 流式），一个 deque 做 SSE 事件
id 缓存（断线重连按 Last-Event-ID 重放）。
"""

import asyncio
import itertools
import json
import uuid
from collections import deque
from typing import Any

from cachetools import TTLCache

# SSE 事件队列容量：生产端（LLM 流式）与消费端（HTTP 响应）之间缓冲的条数。
# 满了就让生产端 await put 阻塞 = 背压，避免 LLM 疯狂吐 token 把内存/响应打爆。
_QUEUE_MAXSIZE = 64
# deque 缓存的最近事件条数（SSE 事件 id 缓存，供 Last-Event-ID 重放）。
_EVENT_CACHE_MAXLEN = 256

_JOB_TTL_SECONDS = 600  # 10 分钟
_MAX_JOBS = 200


def format_sse(event_id: int, event: dict) -> str:
    """把事件字典格式化成一条 SSE 文本：id 行 + data 行。"""
    data = json.dumps(event, ensure_ascii=False)
    return f"id: {event_id}\ndata: {data}\n\n"


class ChatTask:
    """一次 /api/chat 请求的任务：状态 + SSE 事件通道（queue 背压 + deque id 缓存）。"""

    def __init__(self, task_id: str, session_id: str | None = None) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.status: str = "running"  # running / done / failed / cancelled
        self.error: str | None = None
        self.resume: Any = None          # 最终改好的 Section[]（dict 列表）
        self.summary: str | None = None  # 主 agent 生成的修改说明
        self.diagnosis: list[dict] | None = None  # 结构化诊断项
        self.events: deque = deque(maxlen=_EVENT_CACHE_MAXLEN)  # (event_id, sse文本)
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._seq = itertools.count(1)
        # 反问答对：agent 暂停时登记问题 id + future，前端 POST 答案后 resolve
        self._question_id: str | None = None
        self._answer_future: asyncio.Future | None = None

    async def emit(self, event: dict) -> None:
        """生产端发事件：分配 id → 缓存进 deque → 塞进 queue（队列满则阻塞=背压）。"""
        event_id = next(self._seq)
        text = format_sse(event_id, event)
        self.events.append((event_id, text))
        await self.queue.put(text)

    # ---- 反问：暂停 → 等前端提交答案 ----

    def open_question(self, question_id: str) -> asyncio.Future:
        """登记一个待回答的问题，返回答案 future（由 submit_answer resolve）。"""
        future = asyncio.get_running_loop().create_future()
        self._question_id = question_id
        self._answer_future = future
        return future

    def submit_answer(self, question_id: str, answers: list[dict]) -> bool:
        """前端 POST 答案：id 对得上且仍在等待才接受；重复/过期提交返回 False。"""
        future = self._answer_future
        if future is None or future.done() or self._question_id != question_id:
            return False
        future.set_result(answers)
        return True

    def clear_question(self, question_id: str | None = None) -> None:
        """清掉待答登记；还没回答就取消 future（超时 / 任务取消时用）。"""
        if question_id is not None and self._question_id != question_id:
            return
        future = self._answer_future
        if future is not None and not future.done():
            future.cancel()
        self._answer_future = None
        self._question_id = None

    def finish(self, resume: Any, summary: str, diagnosis: list[dict]) -> None:
        self.resume = resume
        self.summary = summary
        self.diagnosis = diagnosis
        self.status = "done"

    def fail(self, error: str) -> None:
        self.error = error
        self.status = "failed"

    def cancel(self) -> None:
        self.status = "cancelled"
        # 生产任务被取消时，正在等答案的 future 也要取消，否则协程会一直挂着
        self.clear_question()


# ---- 全局注册表：按 session_id 存一份 ChatTask，10 分钟过期自动删除 ----
_TASKS: TTLCache = TTLCache(maxsize=_MAX_JOBS, ttl=_JOB_TTL_SECONDS)


def create_chat_task(session_id: str | None) -> ChatTask:
    task = ChatTask(task_id=uuid.uuid4().hex, session_id=session_id)
    _TASKS[session_id or task.task_id] = task
    return task


def get_chat_task(session_id: str | None) -> ChatTask | None:
    if not session_id:
        return None
    return _TASKS.get(session_id)
