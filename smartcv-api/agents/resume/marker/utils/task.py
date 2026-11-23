"""市场洞察任务通道：SSE 事件缓存 + 反问等待。

按 taskId 单独注册：调研是分钟级长任务，需要支持「前端断线后按 taskId 重连」，
不能和对话任务共用一套 key。
"""

import asyncio
import itertools
import json
import uuid
from collections import deque

from cachetools import TTLCache

_QUEUE_MAXSIZE = 64
_EVENT_CACHE_MAXLEN = 512
_TASK_TTL_SECONDS = 900
_MAX_TASKS = 100

_TASKS: TTLCache = TTLCache(maxsize=_MAX_TASKS, ttl=_TASK_TTL_SECONDS)


def format_sse(event_id: int, event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False)
    return f"id: {event_id}\ndata: {data}\n\n"


class MarketTask:
    """一次调研任务：状态 + 事件队列 + 事件 id 缓存 + 待回答的追问。"""

    def __init__(self, task_id: str, session_id: str | None = None) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.status = "running"
        self.error: str | None = None
        self.result: dict | None = None
        self.events: deque = deque(maxlen=_EVENT_CACHE_MAXLEN)
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        # 后台 producer 句柄：取消接口直接掐断，不依赖 SSE 客户端断开被及时感知。
        self.producer: asyncio.Task | None = None
        self._seq = itertools.count(1)
        self._question_id: str | None = None
        self._answer_future: asyncio.Future | None = None

    async def emit(self, event: dict) -> None:
        event_id = next(self._seq)
        text = format_sse(event_id, event)
        self.events.append((event_id, text))
        await self.queue.put(text)

    def open_question(self, question_id: str) -> asyncio.Future:
        future = asyncio.get_running_loop().create_future()
        self._question_id = question_id
        self._answer_future = future
        return future

    def submit_answer(self, question_id: str, answers: list[dict]) -> bool:
        future = self._answer_future
        if future is None or future.done() or self._question_id != question_id:
            return False
        future.set_result(answers)
        return True

    def clear_question(self, question_id: str | None = None) -> None:
        if question_id is not None and self._question_id != question_id:
            return
        future = self._answer_future
        if future is not None and not future.done():
            future.cancel()
        self._answer_future = None
        self._question_id = None

    def finish(self, result: dict) -> None:
        self.result = result
        self.status = "done"

    def fail(self, error: str) -> None:
        self.error = error
        self.status = "failed"

    def cancel(self) -> None:
        self.status = "cancelled"
        self.clear_question()


def create_market_task(session_id: str | None = None) -> MarketTask:
    task = MarketTask(task_id=uuid.uuid4().hex, session_id=session_id)
    _TASKS[task.task_id] = task
    return task


def get_market_task(task_id: str | None) -> MarketTask | None:
    if not task_id:
        return None
    return _TASKS.get(task_id)


def submit_market_answer(task_id: str, question_id: str, answers: list[dict]) -> bool:
    task = get_market_task(task_id)
    if task is None:
        return False
    return task.submit_answer(question_id, answers)


def cancel_market_task(task_id: str) -> bool:
    """取消一轮调研：停掉 producer，并作废待回答的问题；重复调用无副作用。"""
    task = get_market_task(task_id)
    if task is None:
        return False

    task.cancel()
    producer = task.producer
    if producer is not None and not producer.done():
        producer.cancel()
    # producer 还没真正跑起来就被取消时不会走到它的 finally，这里补一个结束哨兵。
    try:
        task.queue.put_nowait(None)
    except asyncio.QueueFull:
        pass
    return True
