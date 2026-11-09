"""Agent 接口：润色 / 优化对话（SSE）/ 提示词与技能预览。"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents.md2json.schemas.resume import Section
from agents.resume.grammar.agent import run_grammar_agent
from agents.resume.optimize.graph import run_chat_stream
from agents.resume.optimize.utils.task import create_chat_task, get_chat_task
from agents.single.agent import run_analyze_agent, run_polish_agent
from routers.deps import get_agent_session
from schemas.provider import ProviderConfig
from schemas.response import error, ok
from services.reference_examples import resolve_examples

logger = logging.getLogger("smartcv")

router = APIRouter(prefix="/api", tags=["agent"])

_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


class PolishRequest(BaseModel):
    items: list[str] = Field(min_length=1)
    provider: ProviderConfig
    description: str = ""
    context: str = ""
    mode: Literal["strict", "free", "enhance"] = "strict"


class ChatRequest(BaseModel):
    resume: list[Section]
    message: str
    jd: str = ""
    referenceIds: list[str] = Field(default_factory=list, max_length=3)
    rewriteMode: Literal["standard", "bold"] = "standard"
    provider: ProviderConfig


class GrammarRequest(BaseModel):
    resume: list[Section]
    provider: ProviderConfig


class ChatAnswerItem(BaseModel):
    """一个问题的回答：选中的选项 + 自定义输入（可为空）。"""

    id: str
    selected: list[str] = Field(default_factory=list)
    custom: str = ""


class ChatAnswerRequest(BaseModel):
    questionId: str
    answers: list[ChatAnswerItem] = Field(default_factory=list)


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


class AnalyzeRequest(BaseModel):
    resume: list[Section] = Field(min_length=1)
    provider: ProviderConfig


@router.post("/analyze")
async def analyze(
    req: AnalyzeRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """分析一份简历：返回 [职业名称, 可借鉴的写法]。

    用于优秀示例库上传示例前，帮用户判断这份简历适合投什么方向、好在哪。
    只读：不写会话历史、不改简历，分析完即丢弃。
    """
    try:
        items = await asyncio.to_thread(
            run_analyze_agent,
            req.provider,
            [s.model_dump(exclude_none=True) for s in req.resume],
            session_id,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=error(400, str(e)))
    except Exception as e:
        logger.exception("简历分析失败")
        return JSONResponse(status_code=500, content=error(500, f"简历分析失败：{e}"))
    return ok({"items": items})


@router.post("/grammar")
async def grammar(
    req: GrammarRequest,
    session_id: str | None = Depends(get_agent_session),
):
    """全文纠错：一次结构化 LLM 调用 + 代码校验，返回改好的简历与改动清单。

    与 /api/chat 不同，这里不是对话：不写会话历史、不跑诊断/审查 agent，
    前端拿到 { resume, changes, skipped, stats } 后复用修改对比弹窗让用户确认。
    """
    try:
        result = await asyncio.to_thread(
            run_grammar_agent,
            req.provider,
            [s.model_dump(exclude_none=True) for s in req.resume],
            session_id,
        )
    except Exception as e:
        logger.exception("全文纠错失败")
        return JSONResponse(status_code=500, content=error(500, f"全文纠错失败：{e}"))
    return ok(result)


def _agent_md_payload() -> dict:
    """扫描 agents/ 目录：提示词（system_prompt*.md + *_prompt.md）+ 技能（skill/**/*.md）。

    `*_prompt.md` 是 single agent 的片段提示词（polish_prompt.md /
    enhance_prompt.md），配合 system_prompt_base.md 模板一起展示。
    """

    def read(f: Path) -> str:
        try:
            return f.read_text(encoding="utf-8")
        except Exception:
            return ""

    files: list[Path] = []
    for pattern in ("system_prompt*.md", "*_prompt.md"):
        files.extend(_AGENTS_DIR.rglob(pattern))
    seen: set[Path] = set()
    prompts: list[dict] = []
    skills: list[dict] = []
    for f in sorted(files):
        if f in seen or "skill" in f.parts:
            continue
        seen.add(f)
        rel = f.relative_to(_AGENTS_DIR)
        label = f.stem.replace("system_prompt_", "").replace("_prompt", "")
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


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

_HEARTBEAT_SECONDS = 15


def _last_event_id(request: Request) -> int | None:
    """SSE 断线重连续传：客户端用 Last-Event-ID 头（或 last_event_id 查询参数）带上已收到的最后一条事件 id。"""
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or ""
    return int(raw) if raw.isdigit() else None


async def _run_chat_task(
    task, provider, resume_sections, jd, question, session_id, references, rewrite_mode
):
    """后台生产任务：跑优化流水线 → 写 task 状态；结束放 None 哨兵（消费端据此收尾）。"""
    try:
        result = await run_chat_stream(
            provider,
            resume_sections,
            jd,
            question,
            task.emit,
            session_id=session_id,
            references=references,
            rewrite_mode=rewrite_mode,
        )
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
    references = resolve_examples(req.referenceIds)
    task = create_chat_task(session_id)
    producer = asyncio.create_task(
        _run_chat_task(
            task,
            req.provider,
            resume_sections,
            req.jd,
            req.message,
            session_id,
            references,
            req.rewriteMode,
        )
    )

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
