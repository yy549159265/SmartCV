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
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

# 开启致命错误转储：原生扩展（Playwright / OpenCV 等）发生访问违规（segfault）时
# Python 不会报错、进程直接没，faulthandler 能把崩溃点堆栈打出来。
faulthandler.enable()

# 业务日志：uvicorn 默认只配它自己 uvicorn.* 那套 logger，root logger 仍停在
# WARNING，我们的 INFO（裸 logging.info 和 getLogger("smartcv")）会被静默丢掉。
# 这里把 root 提到 INFO 并挂上控制台 handler，业务日志就能打出来了。
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger().setLevel(logging.INFO)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.optimize.utils.checkpointer import clear_checkpoints, close_checkpointer, open_checkpointer
from routers import agent as agent_router
from routers import business as business_router
from schemas.response import error
from services.html2pdf import close_browser


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


# ---------- 注册路由 ----------

app.include_router(business_router.router)
app.include_router(agent_router.router)


if __name__ == "__main__":
    import uvicorn

    # PyCharm 调试入口；debug 时别开 reload —— reload 会另起子进程，断点进不去。
    port = int(os.getenv("SMARTCV_API_PORT", "8700"))
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=False)
