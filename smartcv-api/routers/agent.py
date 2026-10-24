"""Agent 接口：润色 / 优化对话（SSE）/ 提示词与技能预览。

路由统一挂在 /api 下，最终 URL 与拆分前完全一致。
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents.md2json.schemas.resume import Section
from agents.optimize.graph import run_chat_stream
from agents.optimize.schemas.task import create_chat_task, get_chat_task
from agents.polish.agent import run_polish_agent
from routers.deps import get_agent_session
from schemas.provider import ProviderConfig
from schemas.response import error, ok

logger = logging.getLogger("smartcv")

router = APIRouter(prefix="/api", tags=["agent"])

# agents/ 目录（本文件在 routers/ 下，所以往上退一级）
_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


# ---------- 请求模型 ----------


class PolishRequest(BaseModel):
    items: list[str] = Field(min_length=1)
    provider: ProviderConfig
    # 用户的润色描述/思路（前端可选填）：空字符串 = 没填，按默认规则润色。
    # 与前端 api/polish.ts 的字段名保持一致。
    description: str = ""
    # 参考材料（可选）：JD、简历、对话历史等。只作为上下文，不参与改写。
    # 用通用字段而不是 jd，同一个接口就能服务润色 / 问答增强等多种场景。
    context: str = ""
    # 润色模式：strict = 严谨（规则锁死，只重构表达），free = 自由（像直接问 AI，
    # 由模型自主判断怎么写最好，并优先遵循用户思路），enhance = 提示词增强
    # （把口语化修改需求改写成可执行的提示词，参考材料通常放 JD）。默认 strict，
    # 老前端不带该字段时行为与加模式之前完全一致。
    mode: Literal["strict", "free", "enhance"] = "strict"


class ChatRequest(BaseModel):
    # resume 直接收前端整份章节数组（Section[]，即前端 store.resume），
    # 后端 agent 拿它当对话上下文，不用再包一层 Resume
    resume: list[Section]
    message: str
    jd: str = ""
    provider: ProviderConfig


class ChatAnswerItem(BaseModel):
    """一个问题的回答：选中的选项 + 自定义输入（可为空）。"""

    id: str
    selected: list[str] = Field(default_factory=list)
    custom: str = ""


class ChatAnswerRequest(BaseModel):
    # 与 ask_question 事件里的 questionId 对应；过期/重复提交会被拒绝
    questionId: str
    # 空数组 = 用户点了「跳过」，诊断按现有信息继续
    answers: list[ChatAnswerItem] = Field(default_factory=list)


# ---------- 接口 ----------


# 文字润色
@router.post("/polish")
async def polish(
    req: PolishRequest,
    session_id: str | None = Depends(get_agent_session),
):
    try:
        items = await asyncio.to_thread(
            run_polish_agent, req.provider, req.items,
            description=req.description, mode=req.mode,
            session_id=session_id, context=req.context,
        )
    except NotImplementedError:
        return JSONResponse(status_code=501, content=error(501, "润色 agent 尚未实现"))
    return ok({"items": items})


# ---------- /api/agent/md：展示后端 agent 的提示词与技能（只读，供「Agent 设置 → md预览」） ----------


def _agent_md_payload() -> dict:
    """扫描 agents/ 目录：提示词（system_prompt*.md）+ 技能（skill/**/*.md）。"""

    def read(f: Path) -> str:
        try:
            return f.read_text(encoding="utf-8")
        except Exception:
            return ""

    prompts: list[dict] = []
    skills: list[dict] = []
    for f in sorted(_AGENTS_DIR.rglob("system_prompt*.md")):
        if "skill" in f.parts:
            continue
        rel = f.relative_to(_AGENTS_DIR)
        label = f.stem.replace("system_prompt_", "")
        if rel.parent.name and rel.parent.name != ".":
            label = f"{rel.parent.name}/{label}"
        prompts.append({"name": label, "path": rel.as_posix(), "content": read(f)})
    skill_dir = _AGENTS_DIR / "skill"
    if skill_dir.exists():
        for f in sorted(skill_dir.rglob("*.md")):
            rel = f.relative_to(_AGENTS_DIR)
            skills.append({"name": f"{rel.parent.name}/{f.stem}", "path": rel.as_posix(), "content": read(f)})
    return {"prompts": prompts, "skills": skills}


@router.get("/agent/md")
async def agent_md():
    """返回后端 agent 用到的提示词与技能 md，前端分组展示，只读不可改。"""
    return ok(_agent_md_payload())


# ---------- /api/chat：优化对话（SSE 流式） ----------

# SSE 响应头：不要被代理/浏览器缓冲，逐事件下发；X-Accel-Buffering 是给 nginx 的
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# SSE 心跳间隔：空闲超过该时长推一条注释行（: keepalive）保活。
# 浏览器 fetch 流本身没有空闲超时，风险主要在 nginx（默认 proxy_read_timeout
# 60s）和公司网关/代理；agent 长时间思考、工具执行时不发数据，需要心跳续命。
_HEARTBEAT_SECONDS = 15


def _last_event_id(request: Request) -> int | None:
    """SSE 断线重连续传：客户端用 Last-Event-ID 头（或 last_event_id 查询参数）带上已收到的最后一条事件 id。"""
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or ""
    return int(raw) if raw.isdigit() else None


async def _run_chat_task(task, provider, resume_sections, jd, question, session_id):
    """后台生产任务：跑优化流水线 → 写 task 状态；结束放 None 哨兵（消费端据此收尾）。"""
    try:
        result = await run_chat_stream(provider, resume_sections, jd, question, task.emit, session_id=session_id)
        task.finish(result["resume"], result["summary"], result["diagnosis"])
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as e:
        logger.exception("chat 流水线异常")
        task.fail(str(e))
        try:
            await task.emit({"type": "error", "message": f"优化失败：{e}"})
        except Exception:
            pass
    finally:
        try:
            await task.queue.put(None)
        except asyncio.CancelledError:
            pass


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    session_id: str | None = Depends(get_agent_session),
):
    """优化对话：SSE 流式。

    入参 { resume, message, jd, provider }；后端跑 诊断→优化（按坐标就地改 JSON）→总结
    流水线，把改好的简历 JSON 发成 resume 事件，前端据此重绘，格式不被打乱。
    """
    resume_sections = [s.model_dump(exclude_none=True) for s in req.resume]
    task = create_chat_task(session_id)
    # 生产任务与消费（SSE 响应）通过 task 的 queue 解耦：queue 满时生产端 await put
    # 阻塞 = 背压，反过来压住 LLM 流式；deque 缓存事件 id 供断线重放。
    producer = asyncio.create_task(
        _run_chat_task(task, req.provider, resume_sections, req.jd, req.message, session_id)
    )

    async def event_stream():
        last_id = _last_event_id(request)
        try:
            # 重连：先从 deque 缓存重放比 Last-Event-ID 新的事件，再接 live 队列
            if last_id is not None:
                for event_id, text in task.events:
                    if event_id > last_id:
                        yield text
            while True:
                try:
                    item = await asyncio.wait_for(task.queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # 心跳：空档期（agent 思考 / 工具执行不发数据）超过阈值就推一条
                    # 注释行，避免网关按空闲时间掐断长连接。前端解析时没有 data: 行
                    # 会直接跳过，不进任务事件缓存，断线重连也不受影响。
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


@router.post("/chat/answer")
async def chat_answer(
    req: ChatAnswerRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """回答诊断 agent 的反问：把答案交给正在暂停等待的任务，SSE 流继续往下跑。

    必须带与 /api/chat 相同的 X-Agent-Session-Id；任务过期、问题 id 对不上
    或重复提交都返回 404/409，前端把问题卡片置为失效。
    """
    task = get_chat_task(session_id)
    if task is None:
        return JSONResponse(status_code=404, content=error(404, "对话任务不存在或已过期"))
    accepted = task.submit_answer(req.questionId, [a.model_dump() for a in req.answers])
    if not accepted:
        return JSONResponse(status_code=409, content=error(409, "该问题已失效或已回答"))
    return ok({"accepted": True})
