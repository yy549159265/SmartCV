"""
SmartCV 后端 —— FastAPI 应用入口（只负责组装）

接口按业务拆到 routers/ 下：
  routers/business.py  业务接口：简历解析 / 导出 / 统计
  routers/agent.py     agent 接口：润色 / 优化对话（SSE）/ 提示词预览

启动：uvicorn main:app --reload --port 8700
      （8000/8600 都可能落在 Windows 的 Hyper-V/WSL 预留端口段里，bind 报
       WinError 10013；可用 `netsh interface ipv4 show excludedportrange protocol=tcp`
       查当前预留段，换一个不在段内的端口）
也可以直接跑本文件（PyCharm 调试用）：python main.py
      （端口取环境变量 SMARTCV_API_PORT，默认 8700；前端 vite 代理读同一个变量）
"""

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
from logging.handlers import RotatingFileHandler
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

faulthandler.enable()

# Windows 控制台 / 重定向到文件时，输出流可能是 GBK 或 ASCII；中文日志会被
# logging 退化成 \xe5\x81\x9a 这类转义。统一成 UTF-8，日志可读。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_LOG_LEVEL = os.getenv("SMARTCV_LOG_LEVEL", "INFO").upper()

_log_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

# 控制台：只打印 INFO 及以上，保持正常输出
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_log_fmt)

# 文件：DEBUG 及以上都写（debug 只进文件，不刷控制台）。文件被 .gitignore 的 *.log 忽略。
# _LOG_DIR = Path(__file__).resolve().parent / "logs"
# _LOG_DIR.mkdir(parents=True, exist_ok=True)
# _file_handler = RotatingFileHandler(
#     _LOG_DIR / "smartcv-api.log",
#     maxBytes=5 * 1024 * 1024,
#     backupCount=3,
#     encoding="utf-8",
# )
# _file_handler.setLevel(logging.DEBUG)
# _file_handler.setFormatter(_log_fmt)

logging.basicConfig(level=_LOG_LEVEL, handlers=[_console_handler])
logging.getLogger().setLevel(_LOG_LEVEL)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.resume.marker.tools.fetch import close_fetchers
from agents.utils.checkpointer import (
    clear_checkpoints,
    close_checkpointer,
    open_checkpointer,
    prune_idle_threads,
)
from routers import agent as agent_router
from routers import business as business_router
from routers import interview as interview_router
from routers import market as market_router
from schemas.response import error
from services.html2pdf import close_browser


_CHECKPOINT_DB = Path(__file__).resolve().parent / "chat_checkpoints.sqlite"
_CHECKPOINT_CLEANUP_SECONDS = 60 * 60

# 面试检查点独立存放：进行中的一场面试不能被 chat 的整库清理误伤。
_INTERVIEW_CHECKPOINT_DB = Path(__file__).resolve().parent / "interview_checkpoints.sqlite"
_INTERVIEW_IDLE_SECONDS = 60 * 60
_INTERVIEW_PRUNE_SECONDS = 10 * 60


async def _checkpoint_cleanup_loop() -> None:
    """后台循环：每隔一段时间清空 chat 检查点 sqlite（含 -shm/-wal）。"""
    while True:
        await asyncio.sleep(_CHECKPOINT_CLEANUP_SECONDS)
        try:
            await clear_checkpoints(str(_CHECKPOINT_DB))
            logger.info("已清空 chat 检查点（%s）", _CHECKPOINT_DB)
        except Exception:
            logger.exception("清空 chat 检查点失败")


async def _interview_prune_loop() -> None:
    """按线程最后更新时间裁剪面试检查点：空闲超过 1h 的线程删除。"""
    while True:
        await asyncio.sleep(_INTERVIEW_PRUNE_SECONDS)
        try:
            removed = await asyncio.to_thread(
                prune_idle_threads, "interview", _INTERVIEW_IDLE_SECONDS
            )
            if removed:
                logger.info("已清理 %d 个空闲面试线程", removed)
        except Exception:
            logger.exception("清理面试检查点失败")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时打开 chat / interview 两个 saver 与各自清理循环；退出时释放。"""
    await open_checkpointer(str(_CHECKPOINT_DB))
    await open_checkpointer(str(_INTERVIEW_CHECKPOINT_DB), name="interview")
    cleanup_task = asyncio.create_task(_checkpoint_cleanup_loop())
    interview_task = asyncio.create_task(_interview_prune_loop())
    yield
    cleanup_task.cancel()
    interview_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task
    with contextlib.suppress(asyncio.CancelledError):
        await interview_task
    await close_checkpointer()
    await close_checkpointer("interview")
    await close_browser()
    await close_fetchers()


app = FastAPI(title="SmartCV API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


logger = logging.getLogger("smartcv")
_AGENT_SESSION_HEADER = "x-agent-session-id"
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


_FIELD_NAMES = {
    "provider": "供应商",
    "baseUrl": "接口地址",
    "apiKey": "API Key",
    "model": "模型名称",
    "items": "润色内容",
    "description": "润色描述",
    "context": "参考材料",
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


app.include_router(business_router.router)
app.include_router(agent_router.router)
app.include_router(market_router.router)
app.include_router(interview_router.router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SMARTCV_API_PORT", "9000"))
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=False)
