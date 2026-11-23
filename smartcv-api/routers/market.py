"""市场洞察接口：启动调研（SSE）+ 回答 planner 的反问。

交互模型：
  POST /api/market/stream   创建 taskId，边跑边推事件；响应头 X-Market-Task-Id 也带一份。
  POST /api/market/answer   用 taskId + questionId 回答 ask_question，SSE 流继续。

前端只需提供目标岗位或一份简历，其余字段由 planner 通过 ask_question 多轮补全。
"""

import asyncio
import contextlib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from agents.resume.marker import MarketRequest, run_market_stream
from agents.resume.marker.role_agent import run as run_role_inference
from agents.resume.marker.utils.stage_log import stage_exception, stage_info, stage_warning
from agents.resume.marker.utils.task import cancel_market_task, create_market_task, submit_market_answer
from agents.utils.choose_llm import choose_llm
from routers.deps import get_agent_session
from schemas.provider import ProviderConfig
from schemas.response import error, ok

router = APIRouter(prefix="/api/market", tags=["market"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
_HEARTBEAT_SECONDS = 15


class MarketAnswerItem(BaseModel):
    """一个问题的回答：选中的选项 + 自定义输入（可为空）。"""

    id: str
    selected: list[str] = Field(default_factory=list)
    custom: str = ""


class MarketAnswerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(..., alias="taskId")
    question_id: str = Field(..., alias="questionId")
    answers: list[MarketAnswerItem] = Field(default_factory=list)


class MarketCancelRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(..., alias="taskId")


class MarketRoleRequest(BaseModel):
    """简历反推：前端传当前简历快照 + 供应商配置。"""

    resume: list[dict] = Field(..., min_length=1)
    provider: ProviderConfig


def _last_event_id(request: Request) -> int | None:
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or ""
    return int(raw) if raw.isdigit() else None


async def _run_market_task(task, provider: ProviderConfig, req: MarketRequest) -> None:
    """后台生产任务：跑流水线 → 写 task 状态；结束放 None 哨兵。"""
    try:
        result = await run_market_stream(provider, req, task.emit, task=task)
        # 没选调研重点时流水线在规划阶段主动结束，不把空结果标成完成。
        if result.get("aborted"):
            task.cancel()
        else:
            task.finish(result)
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as exc:
        stage_warning("pipeline", "后台任务异常结束", task=task.task_id, error=exc)
        already_failed = task.status == "failed"
        task.fail(str(exc))
        # run_market_stream 已在内部发过 fatal error/done（并把 task 标成 failed）；
        # 这里只兜底它之外（如选择模型）的异常。
        if not already_failed:
            with contextlib.suppress(Exception):
                await task.emit({"type": "error", "node": "pipeline", "message": str(exc), "fatal": True})
                await task.emit({"type": "done", "status": "failed"})
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await task.queue.put(None)


@router.post("/stream")
async def market_stream(
    req: MarketRequest,
    request: Request,
    session_id: str | None = Depends(get_agent_session),
):
    """启动一次市场调研，返回 SSE 事件流。

    事件类型见 agents/resume/marker：graph / status / node.* / collect.* /
    extract.* / profile.* / strategy.* / report.* / ask_question / done。
    第一条事件固定是 `task`，携带 taskId，供反问接口使用。
    """
    if not req.target_role.strip() and not req.resume:
        stage_warning("pipeline", "请求缺少目标岗位和简历")
        return JSONResponse(status_code=400, content=error(400, "请提供目标岗位或选择一份简历"))

    task = create_market_task(session_id)
    await task.emit({"type": "task", "taskId": task.task_id, "status": "running"})
    producer = asyncio.create_task(_run_market_task(task, req.provider, req))
    # 挂到任务通道上，「重新调研」时用 /cancel 直接停掉这一轮。
    task.producer = producer

    async def event_stream():
        last_id = _last_event_id(request)
        try:
            if last_id is not None:
                for event_id, text in task.events:
                    if event_id > last_id:
                        yield text
            while True:
                try:
                    item = await asyncio.wait_for(task.queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                yield item
        finally:
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await producer

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={**_SSE_HEADERS, "X-Market-Task-Id": task.task_id},
    )


@router.post("/answer")
async def market_answer(req: MarketAnswerRequest):
    """回答 planner 的反问：答案交回暂停中的任务，SSE 流继续往下跑。"""
    accepted = submit_market_answer(
        req.task_id,
        req.question_id,
        [item.model_dump() for item in req.answers],
    )
    if not accepted:
        stage_warning("plan", "回答已失效", task=req.task_id, question=req.question_id)
        return JSONResponse(status_code=409, content=error(409, "该问题已失效或已回答"))
    stage_info(
        "plan",
        "收到回答",
        task=req.task_id,
        question=req.question_id,
        answers=len(req.answers),
    )
    return ok({"accepted": True})


@router.post("/cancel")
async def market_cancel(req: MarketCancelRequest):
    """取消一轮调研。前端重新调研时先取消旧的，避免旧任务继续跑。"""
    cancelled = cancel_market_task(req.task_id)
    stage_info("pipeline", "取消", task=req.task_id, cancelled=cancelled)
    # 任务可能已自然结束 / 超出 TTL，取消按幂等处理，不把它当错误。
    return ok({"cancelled": cancelled})


@router.post("/roles")
async def market_roles(req: MarketRoleRequest):
    """根据一份简历反推 4 个目标岗位 + 可直接填入 MarketRequest 的城市 / 年限。"""
    try:
        llm = choose_llm(req.provider, timeout=120, max_retries=1)
        result = await run_role_inference(llm, req.resume)
    except Exception as exc:
        stage_exception("roles", "岗位反推失败")
        return JSONResponse(status_code=502, content=error(502, f"岗位反推失败：{exc}"))

    if not result["roles"]:
        stage_warning("roles", "没有可用岗位")
        return JSONResponse(status_code=502, content=error(502, "AI 没有返回可用的岗位，请重试"))
    return ok(result)
