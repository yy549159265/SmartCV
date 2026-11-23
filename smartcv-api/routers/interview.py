"""AI 模拟面试接口：画像 / 内容编辑 / 问题包 / 对话面试 SSE / 状态恢复。

画像、内容编辑与问题包是普通 JSON；对话面试的每一轮 action 走 SSE，每条 SSE 只
服务一次请求，断开即取消本轮。刷新后用 `GET /api/interview/state` 重新对齐，
不做断线重放。provider 每轮都带：API Key 只在浏览器，不写进检查点。
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from agents.resume.interview import general_answer_agent, pack_agent, resume_agent
from agents.resume.interview import graph as interview_graph
from agents.resume.interview.schemas import (
    AnswerRequest,
    ContentEditOutput,
    ContentEditRequest,
    FollowUpAddRequest,
    FollowUpAnswerSet,
    FollowUpAnswersRequest,
    FollowUpDraft,
    PackRequest,
    ProfileRequest,
    ReferenceAnswer,
    SampleAnswerHttpRequest,
    StreamRequest,
    ThreadRequest,
)
from agents.resume.interview.utils import policy
from agents.utils.checkpointer import new_thread_id
from agents.utils.usage import collect_usage
from routers.deps import get_agent_session
from schemas.response import error, ok

logger = logging.getLogger("smartcv")

router = APIRouter(prefix="/api/interview", tags=["interview"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

_HEARTBEAT_SECONDS = 15
_LOCKS: dict[str, asyncio.Lock] = {}


def _thread_lock(thread_id: str) -> asyncio.Lock:
    lock = _LOCKS.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[thread_id] = lock
    if len(_LOCKS) > 256:
        for key, value in list(_LOCKS.items()):
            if key != thread_id and not value.locked():
                _LOCKS.pop(key, None)
            if len(_LOCKS) <= 128:
                break
    return lock


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/profile")
async def profile(
    req: ProfileRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """简历文本 → 已用代码核对过原文的画像与证据锚点。"""
    try:
        with collect_usage() as meter:
            profile_data, anchors, warnings = await resume_agent.run(
                req.provider, req.resume, session_id=session_id
            )
    except ValueError as exc:
        return JSONResponse(status_code=400, content=error(400, str(exc)))
    except Exception as exc:  # noqa: BLE001
        logger.exception("面试画像抽取失败")
        return JSONResponse(
            status_code=502, content=error(502, f"简历分析失败：{str(exc)[:200]}")
        )
    return ok(
        {
            "profile": profile_data.model_dump(by_alias=True),
            "anchors": [anchor.model_dump(by_alias=True) for anchor in anchors],
            "warnings": warnings,
            "usage": meter.snapshot(),
        }
    )


@router.post("/edit")
async def edit_content(req: ContentEditRequest):
    """通用内容编辑：一段 JSON + 修改思路 -> 修改后的同结构 JSON。

    `scene` 选择 `prompts/general/<scene>.md`；输出实体固定为 `ContentEditOutput`，
    提示词里的 JSON Schema 由该实体自动生成。
    """
    try:
        with collect_usage() as meter:
            result = await general_answer_agent.run(
                req.provider, req, ContentEditOutput
            )
    except ValueError as exc:
        return JSONResponse(status_code=400, content=error(400, str(exc)))
    except general_answer_agent.GeneralAgentError as exc:
        logger.warning("内容修改未通过校验：%s", str(exc)[:300])
        return JSONResponse(status_code=502, content=error(502, str(exc)[:800]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("内容修改失败")
        return JSONResponse(
            status_code=502, content=error(502, f"内容修改失败：{str(exc)[:200]}")
        )

    return ok({**result.model_dump(by_alias=True), "usage": meter.snapshot()})


@router.post("/follow-up")
async def add_follow_up(req: FollowUpAddRequest):
    """按用户方向新增一条追问；层级由模型判断，id 由后端补全。"""
    try:
        with collect_usage() as meter:
            result = await general_answer_agent.run(
                req.provider, req, FollowUpDraft
            )
    except ValueError as exc:
        return JSONResponse(status_code=400, content=error(400, str(exc)))
    except general_answer_agent.GeneralAgentError as exc:
        logger.warning("新增追问未通过校验：%s", str(exc)[:300])
        return JSONResponse(status_code=502, content=error(502, str(exc)[:800]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("新增追问失败")
        return JSONResponse(
            status_code=502, content=error(502, f"新增追问失败：{str(exc)[:200]}")
        )

    return ok({**result.model_dump(by_alias=True), "usage": meter.snapshot()})


@router.post("/pack")
async def pack(req: PackRequest):
    """第 3 步：按已选场景并发生成问题包，对话与清单共用。

    不创建检查点；只有选对话面试时才走 /thread 建场。
    """
    try:
        policy.validate_mode(req)
    except policy.PolicyError as exc:
        return JSONResponse(status_code=400, content=error(400, str(exc)))

    try:
        with collect_usage() as meter:
            cards, warnings = await pack_agent.generate(req.provider, req)
    except pack_agent.PackError as exc:
        # 明细（哪张卡、哪条校验）只进日志；返回前端的是一句可行动的原因。
        logger.warning("问题卡未通过校验：%s", str(exc)[:2000])
        return JSONResponse(
            status_code=502, content=error(502, exc.public_message)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("问题卡生成失败")
        return JSONResponse(
            status_code=502, content=error(502, f"问题卡生成失败：{str(exc)[:200]}")
        )

    return ok(
        {
            "cards": [card.model_dump(by_alias=True) for card in cards],
            "warnings": warnings,
            "usage": meter.snapshot(),
        }
    )


@router.post("/reference-answer")
async def reference_answer(req: AnswerRequest):
    """为一张卡生成主问题参考答案；进入清单后按卡片调用。

    出题阶段不会生成答案。画像依据不足时仍返回完整示范答案，
    同时保留 `missingInfo` 并在 `assumptions` 里标注假设。
    """
    try:
        with collect_usage() as meter:
            answer = await general_answer_agent.run(
                req.provider, req, ReferenceAnswer
            )
    except general_answer_agent.GeneralAgentError as exc:
        logger.warning("AI 示范答案未通过校验：%s", str(exc)[:300])
        return JSONResponse(status_code=502, content=error(502, str(exc)[:800]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI 示范答案生成失败")
        return JSONResponse(
            status_code=502, content=error(502, f"AI 示范答案生成失败：{str(exc)[:200]}")
        )

    return ok(
        {"answer": answer.model_dump(by_alias=True), "usage": meter.snapshot()}
    )


@router.post("/follow-up-answers")
async def follow_up_answers(req: FollowUpAnswersRequest):
    """为某张卡的 L1/L2/L3 追问生成示范答案；依据不足时同样保留缺口与假设。"""
    try:
        with collect_usage() as meter:
            answers = await general_answer_agent.run(
                req.provider, req, FollowUpAnswerSet
            )
    except general_answer_agent.GeneralAgentError as exc:
        logger.warning("AI 追问答案未通过校验：%s", str(exc)[:300])
        return JSONResponse(status_code=502, content=error(502, str(exc)[:800]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI 追问答案生成失败")
        return JSONResponse(
            status_code=502, content=error(502, f"AI 追问答案生成失败：{str(exc)[:200]}")
        )

    return ok(
        {
            "answers": [
                item.model_dump(by_alias=True) for item in answers.answers
            ],
            "usage": meter.snapshot(),
        }
    )


@router.post("/sample-answer")
async def sample_answer(
    req: SampleAnswerHttpRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """按已记录的一轮作答生成示例回答；由评价卡上的按钮触发。

    只读检查点，不推进面试；同一轮可以重复生成，结果由前端写回本次会话。
    """
    try:
        async with _thread_lock(req.thread_id):
            # 放在锁内读检查点，避免和同时推进的 /stream 读到旧记录。
            values = await interview_graph.load_values(req.thread_id, session_id)
            if values is None:
                return JSONResponse(
                    status_code=404,
                    content=error(404, "面试不存在或已过期，请重新开始"),
                )
            with collect_usage() as meter:
                answer = await interview_graph.sample_answer(
                    req.provider,
                    values,
                    card_id=req.card_id,
                    question=req.question,
                )
            # 示例回答不推进面试，但消耗的 token 记入本场统计。
            await interview_graph.record_usage(
                req.thread_id, session_id, meter.snapshot()
            )
    except interview_graph.SampleAnswerNotFound as exc:
        return JSONResponse(status_code=404, content=error(404, str(exc)))
    except general_answer_agent.GeneralAgentError as exc:
        logger.warning("AI 示例回答未通过校验：%s", str(exc)[:300])
        return JSONResponse(status_code=502, content=error(502, str(exc)[:800]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI 示例回答生成失败")
        return JSONResponse(
            status_code=502, content=error(502, f"AI 示例回答生成失败：{str(exc)[:200]}")
        )

    return ok({**answer.model_dump(by_alias=True), "usage": meter.snapshot()})


@router.post("/thread")
async def thread(
    req: ThreadRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """第 3 步：题包生成后选中对话面试，创建检查点；不调用模型、不重新出题。"""
    try:
        policy.validate_thread(req)
    except policy.PolicyError as exc:
        return JSONResponse(status_code=400, content=error(400, str(exc)))

    thread_id = new_thread_id()
    try:
        await interview_graph.create_thread(
            thread_id,
            owner_session=session_id,
            use_mode=req.use_mode,
            scene=req.scene,
            follow_depth=req.follow_depth or "",
            focus=req.focus,
            profile=req.profile,
            anchors=req.anchors,
            cards=req.cards,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("面试检查点创建失败")
        return JSONResponse(
            status_code=500, content=error(500, f"面试创建失败：{str(exc)[:200]}")
        )

    return ok({"threadId": thread_id})


@router.post("/stream")
async def stream(
    req: StreamRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """推进一轮面试 / 教学，SSE 返回。"""
    if req.action == "answer" and not req.answer.strip():
        return JSONResponse(status_code=422, content=error(422, "回答不能为空"))
    if req.action == "teach_message" and not req.message.strip():
        return JSONResponse(status_code=422, content=error(422, "内容不能为空"))

    values = await interview_graph.load_values(req.thread_id, session_id)
    if values is None:
        return JSONResponse(
            status_code=404, content=error(404, "面试不存在或已过期，请重新开始")
        )
    try:
        policy.validate_action(req.action, values.get("phase") or "interviewing")
    except policy.PolicyError as exc:
        return JSONResponse(status_code=409, content=error(409, str(exc)))

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def put(event: dict) -> None:
        await queue.put(_sse(event))

    async def produce() -> None:
        lock = _thread_lock(req.thread_id)
        try:
            async with lock:
                await interview_graph.stream_interview(
                    req.provider,
                    thread_id=req.thread_id,
                    action=req.action,
                    answer=req.answer,
                    message=req.message,
                    owner_session=session_id,
                    emit=put,
                )
            await put({"type": "done", "status": "ok"})
        except interview_graph.InterviewNotFound as exc:
            await put({"type": "error", "message": str(exc), "fatal": True})
            await put({"type": "done", "status": "error"})
        except policy.PolicyError as exc:
            await put({"type": "error", "message": str(exc), "fatal": True})
            await put({"type": "done", "status": "error"})
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "interview stream failed: thread=%s action=%s",
                req.thread_id,
                req.action,
            )
            await put(
                {
                    "type": "error",
                    "message": f"面试推进失败：{str(exc)[:200]}",
                    "fatal": True,
                }
            )
            await put({"type": "done", "status": "error"})
        finally:
            await queue.put(None)

    producer = asyncio.create_task(produce())

    async def event_stream():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                yield item
        finally:
            producer.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/state")
async def state(
    thread_id: str = Query(..., alias="threadId"),
    session_id: str | None = Depends(get_agent_session),
):
    """只读恢复：当前题、轮次、phase、作答记录；不返回问题包与参考答案。"""
    view = await interview_graph.get_state(thread_id, session_id)
    if view is None:
        return JSONResponse(
            status_code=404, content=error(404, "面试不存在或已过期，请重新开始")
        )
    return ok(view.model_dump(by_alias=True))
