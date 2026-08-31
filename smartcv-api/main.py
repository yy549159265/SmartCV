"""
SmartCV 后端 —— FastAPI 应用（所有接口写在一个文件）

只有 3 个接口，其余逻辑都在前端：
  POST /api/resume/parse   上传 PDF/Word → 返回简历 JSON（章节数组）
  POST /api/polish         批量润色列表文本 → 返回润色后的列表
  POST /api/chat           优化对话（SSE 流式）：诊断 + 按坐标就地改 JSON + 主 agent 总结

启动：uvicorn main:app --reload --port 8600
      （8000 在 Windows 的 Hyper-V/WSL 预留端口段里，bind 会失败，用 8600）
也可以直接跑本文件（PyCharm 调试用）：python main.py
"""
# 必须放在所有 import 之前：huggingface_hub 在 import 时就把这些读死了，
# 放后面（docling → huggingface_hub 已导入）就来不及了，会仍连 huggingface.co。
# 1) HF_ENDPOINT：国内连不上 huggingface.co，用 hf-mirror 镜像下载 docling 模型。
# 2) HF_HUB_DISABLE_XET：大文件走 Xet 存储（独立域名 *.xethub.hf.co，镜像代理不了），
#    会 401，关掉后退回普通 HTTP 下载，就能走镜像了。
import os

from agents.md2json.schemas.resume import Resume

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# docling 加载模型时 PyTorch 会打两类无害告警（量化接口将来弃用 / 无 GPU 时
# pin_memory 无效），不是我们代码的问题；还有 transformers 的模型加载进度条。
# 都在这里静音，避免污染服务日志。要放在 import docling 之前。
os.environ.setdefault("TQDM_DISABLE", "1")  # 关掉 "Loading weights" 进度条

import warnings

warnings.filterwarnings(
    "ignore",
    message="'pin_memory' argument is set as true but no accelerator is found",
)
warnings.filterwarnings("ignore", message="torch.quantize_per_tensor")

import asyncio
import contextlib
import faulthandler
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

# 开启致命错误转储：docling 里是 C++/PyTorch/OpenCV 原生代码，万一访问违规
# （segfault）Python 不会报错、进程直接没，faulthandler 能把崩溃点堆栈打出来。
faulthandler.enable()

# 业务日志：uvicorn 默认只配它自己 uvicorn.* 那套 logger，root logger 仍停在
# WARNING，我们的 INFO（裸 logging.info 和 getLogger("smartcv")）会被静默丢掉。
# 这里把 root 提到 INFO 并挂上控制台 handler，业务日志就能打出来了。
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger().setLevel(logging.INFO)

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from agents.md2json.schemas.resume import Section
from agents.md2json.schemas.store import create_store, get_store
from agents.optimize.checkpointer import clear_checkpoints, close_checkpointer, open_checkpointer
from agents.optimize.graph import run_chat_stream
from agents.optimize.schemas.task import create_chat_task
from agents.polish.agent import run_polish_agent
from schemas.provider import ProviderConfig, provider_config
from schemas.response import error, ok
from services.pdf2json import parse_resume_document
from services.stats import increment_stats, load_stats
from services.html2pdf import close_browser, resume_html_to_pdf


_CHECKPOINT_DB = Path(__file__).resolve().parent / "chat_checkpoints.sqlite"
# 检查点 sqlite 清理间隔：每 1h 清空一次，防止 langgraph checkpoint 无限膨胀
_CHECKPOINT_CLEANUP_SECONDS = 60 * 60


async def _checkpoint_cleanup_loop() -> None:
    """后台循环：每隔一段时间清空 chat 检查点 sqlite（含 -shm/-wal）。"""
    while True:
        await asyncio.sleep(_CHECKPOINT_CLEANUP_SECONDS)
        try:
            await clear_checkpoints(str(_CHECKPOINT_DB))
            logger.info("已清空 chat 检查点（%s）", _CHECKPOINT_DB)
        except Exception:
            logger.exception("清空 chat 检查点失败")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时打开 chat 的 sqlite 检查点，并启动 1h 清理循环；退出时释放。"""
    await open_checkpointer(str(_CHECKPOINT_DB))
    cleanup_task = asyncio.create_task(_checkpoint_cleanup_loop())
    yield
    cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task
    await close_checkpointer()
    await close_browser()


app = FastAPI(title="SmartCV API", lifespan=lifespan)

# 前端 dev server 已配 /api 代理（同源），这里 CORS 只是兜底
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- agent 会话 id：前端每个请求都带 X-Agent-Session-Id（UUID7） ----------

logger = logging.getLogger("smartcv")
_AGENT_SESSION_HEADER = "x-agent-session-id"
# 轮询接口每秒打一次会话日志，刷屏，单独静音掉
_QUIET_SESSION_PATHS = {"/api/resume/parse/status"}


@app.middleware("http")
async def agent_session_middleware(request: Request, call_next):
    """读取前端传来的 agent 会话 id（UUID7），校验后存进 request.state。

    后续接 agent（对话/解析/润色）时从这里拿会话上下文，把同一用户的多次
    调用串成一次会话；现在只做解析 + 打日志。前端没带或格式不对都不拦请求
    （放行），只是不产生会话 id。
    """
    raw = request.headers.get(_AGENT_SESSION_HEADER, "").strip()
    request.state.agent_session_id = raw or None
    request.state.agent_session_valid = False
    if raw:
        try:
            value = UUID(raw)
        except ValueError:
            logger.warning("illegal agent session id %r ignored", raw)
        else:
            request.state.agent_session_valid = True
            if request.url.path not in _QUIET_SESSION_PATHS:
                logger.info(
                    "agent session %s (v%d) -> %s %s",
                    value, value.version, request.method, request.url.path,
                )
    return await call_next(request)


def get_agent_session(request: Request) -> str | None:
    """给后续 agent 接口用：当前请求的会话 id（前端没带或非法则为 None）。"""
    if not getattr(request.state, "agent_session_valid", False):
        return None
    return getattr(request.state, "agent_session_id", None)


class _QuietPathFilter(logging.Filter):
    """按路径静音某个日志记录（用于每秒轮询的接口，避免刷屏）。"""

    def __init__(self, quiet_path: str) -> None:
        super().__init__()
        self.quiet_path = quiet_path

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return self.quiet_path not in record.getMessage()
        except Exception:
            return True


logging.getLogger("uvicorn.access").addFilter(_QuietPathFilter("/api/resume/parse/status"))


# ---------- 统一响应：任何错误都包装成 { code, message, data } ----------

_FIELD_NAMES = {
    "provider": "供应商",
    "baseUrl": "接口地址",
    "apiKey": "API Key",
    "model": "模型名称",
    "items": "润色内容",
}


def _humanize_validation_error(err: dict) -> str:
    """把 Pydantic 校验错误翻成中文。loc 最后一段是字段名。"""
    loc = err.get("loc") or []
    raw_field = str(loc[-1]) if loc else ""
    field = _FIELD_NAMES.get(raw_field, raw_field)
    etype = err.get("type", "")
    if etype in ("missing", "string_too_short"):
        return f"「{field}」不能为空"
    if etype.startswith("int_") or etype.startswith("float_"):
        return f"「{field}」必须是数字"
    return f"「{field}」格式不正确：{err.get('msg', '')}"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败（422）统一包装。原本 FastAPI 的 detail 是英文数组，这里转成中文。"""
    errors = exc.errors()
    first = errors[0] if errors else {}
    return JSONResponse(status_code=422, content=error(422, _humanize_validation_error(first)))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常（404/401 等）统一包装。"""
    return JSONResponse(status_code=exc.status_code, content=error(exc.status_code, str(exc.detail)))


# ---------- 请求模型 ----------


class PolishRequest(BaseModel):
    items: list[str] = Field(min_length=1)
    provider: ProviderConfig


class ChatRequest(BaseModel):
    # resume 直接收前端整份章节数组（Section[]，即前端 store.resume），
    # 后端 agent 拿它当对话上下文，不用再包一层 Resume
    resume: list[Section]
    message: str
    jd: str = ""
    provider: ProviderConfig


class PdfRequest(BaseModel):
    html: str


class StatsIncRequest(BaseModel):
    kind: Literal["pdf", "json"]




# ---------- 接口 ----------

# 上传pdf解析成json
@app.post("/api/resume/parse")
async def resume_parse(
    request: Request,
    file: UploadFile = File(...),
    parser: str = Form("docling"),
    mineruToken: str = Form(""),
    provider: ProviderConfig = Depends(provider_config),
    session_id: str | None = Depends(get_agent_session),
):
    # 提前按 Content-Length 拒掉大文件：不读 body 就返回 413，省内存。
    # （余量给 multipart 边界和 provider 表单字段留空间；没带该头的请求走 service 里的兜底检查。）
    MAX_UPLOAD = 5 * 1024 * 1024 + 128 * 1024
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件超过 5MB，请压缩后再上传")

    # 进度状态存进全局注册表（按 session_id 索引），前端轮询 /api/resume/parse/status。
    # 前端总会带 X-Agent-Session-Id；没带时兜底生成一个 key，状态仍可追踪。
    store = create_store(session_id or uuid.uuid4().hex)
    try:
        await parse_resume_document(
            file, provider, store, request,
            parser=parser, mineru_token=mineruToken, session_id=session_id,
        )
    except asyncio.CancelledError:
        # 客户端刷新/断开：标记取消，不再往下跑（agent 已在 to_thread 里被跳过）。
        store.cancel()
        raise
    except HTTPException:
        # 校验/解析失败：store 里已把对应步骤标 failed，错误通过响应回前端。
        raise
    if store.content is None:
        raise HTTPException(status_code=502, detail=store.error or "简历解析失败")
    store.complete()
    return ok([s.model_dump(exclude_none=True) for s in store.content.sections])

@app.get("/api/resume/parse/status")
async def resume_parse_status(session_id: str | None = Depends(get_agent_session)):
    """轮询解析进度：返回 { state, error, steps, content }，store 不存在返回 unknown。"""
    store = get_store(session_id)
    if store is None:
        return ok({"state": "unknown", "error": None, "steps": [], "content": None})
    return ok(
        {
            "state": store.state,
            "error": store.error,
            "steps": [s.model_dump() for s in store.steps],
            "content": store.content.model_dump(exclude_none=True) if store.content else None,
        }
    )

# 导出pdf简历
@app.post("/api/resume/pdf")
async def resume_pdf(req: PdfRequest):
    try:
        pdf = await resume_html_to_pdf(req.html)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 生成失败：{e}")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="smartcv-resume.pdf"'},
    )

# 文字润色
@app.post("/api/polish")
async def polish(
    req: PolishRequest,
    session_id: str | None = Depends(get_agent_session),
):
    try:
        items = await asyncio.to_thread(run_polish_agent, req.provider, req.items, session_id=session_id)
    except NotImplementedError:
        return JSONResponse(status_code=501, content=error(501, "润色 agent 尚未实现"))
    return ok({"items": items})


# ---------- /api/agent/md：展示后端 agent 的提示词与技能（只读，供「Agent 设置 → md预览」） ----------


def _agent_md_payload() -> dict:
    """扫描 agents/ 目录：提示词（system_prompt*.md）+ 技能（skill/**/*.md）。"""
    agents_dir = Path(__file__).resolve().parent / "agents"

    def read(f: Path) -> str:
        try:
            return f.read_text(encoding="utf-8")
        except Exception:
            return ""

    prompts: list[dict] = []
    skills: list[dict] = []
    for f in sorted(agents_dir.rglob("system_prompt*.md")):
        if "skill" in f.parts:
            continue
        rel = f.relative_to(agents_dir)
        label = f.stem.replace("system_prompt_", "")
        if rel.parent.name and rel.parent.name != ".":
            label = f"{rel.parent.name}/{label}"
        prompts.append({"name": label, "path": rel.as_posix(), "content": read(f)})
    skill_dir = agents_dir / "skill"
    if skill_dir.exists():
        for f in sorted(skill_dir.rglob("*.md")):
            rel = f.relative_to(agents_dir)
            skills.append({"name": f"{rel.parent.name}/{f.stem}", "path": rel.as_posix(), "content": read(f)})
    return {"prompts": prompts, "skills": skills}


@app.get("/api/agent/md")
async def agent_md():
    """返回后端 agent 用到的提示词与技能 md，前端分组展示，只读不可改。"""
    return ok(_agent_md_payload())


# ---------- /api/stats：导出统计（PDF / JSON 次数，存后端文件） ----------


@app.get("/api/stats")
async def stats_get():
    """读取累计导出次数：{pdf, json}。"""
    return ok(await asyncio.to_thread(load_stats))


@app.post("/api/stats/inc")
async def stats_inc(req: StatsIncRequest):
    """对应类型导出计数 +1，返回最新 {pdf, json}。"""
    return ok(await asyncio.to_thread(increment_stats, req.kind))


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


@app.post("/api/chat")
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


if __name__ == "__main__":
    import uvicorn

    # PyCharm 调试入口：直接跑本文件即可。
    # debug 时别开 reload —— reload 会另起一个子进程，断点进不去。
    uvicorn.run("main:app", host="127.0.0.1", port=8600, reload=False)
