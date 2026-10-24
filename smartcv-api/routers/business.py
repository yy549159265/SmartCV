"""业务接口：简历解析 / 导出 / 统计。

这些接口面向简历文件本身，不直接承载 agent 对话。
（/resume/parse 内部是确定性解析流水线，只在上传文件和返回结果之间短暂处理，
解析结果直接回给前端，服务端不保存。）

路由统一挂在 /api 下，最终 URL 与拆分前完全一致。
"""

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from agents.md2json.schemas.store import create_store, delete_store, get_store
from routers.deps import get_agent_session
from schemas.provider import ProviderConfig, provider_config
from schemas.response import ok
from services.html2pdf import resume_html_to_pdf
from services.pdf2json import parse_resume_document
from services.stats import increment_stats, load_stats

router = APIRouter(prefix="/api", tags=["business"])


# ---------- 请求模型 ----------


class PdfRequest(BaseModel):
    html: str


class StatsIncRequest(BaseModel):
    kind: Literal["pdf", "json"]


# ---------- 接口 ----------


# 上传pdf解析成json
@router.post("/resume/parse")
async def resume_parse(
    request: Request,
    file: UploadFile = File(...),
    parser: str = Form("mineru"),
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
    key = session_id or uuid.uuid4().hex
    store = create_store(key)
    try:
        sections = await parse_resume_document(
            file, provider, store, request,
            parser=parser, mineru_token=mineruToken, session_id=session_id,
        )
        store.complete()
        return ok([s.model_dump(exclude_none=True) for s in sections])
    except asyncio.CancelledError:
        # 客户端刷新/断开：标记取消，不再往下跑。
        store.cancel()
        raise
    except HTTPException:
        # 校验/解析失败：store 里已把对应步骤标 failed，错误通过响应回前端。
        raise
    finally:
        # 隐私约束：结果已经发给前端，服务端立即删除这次解析的全部状态。
        delete_store(key, store)


@router.get("/resume/parse/status")
async def resume_parse_status(session_id: str | None = Depends(get_agent_session)):
    """轮询解析进度：只返回 { state, error, steps }，不含任何简历内容。

    store 不存在（从未创建或请求已结束被删除）时返回 unknown。
    """
    store = get_store(session_id)
    if store is None:
        return ok({"state": "unknown", "error": None, "steps": []})
    return ok(
        {
            "state": store.state,
            "error": store.error,
            "steps": [s.model_dump() for s in store.steps],
        }
    )


# 导出pdf简历
@router.post("/resume/pdf")
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


# ---------- /api/stats：导出统计（PDF / JSON 次数，存后端文件） ----------


@router.get("/stats")
async def stats_get():
    """读取累计导出次数：{pdf, json}。"""
    return ok(await asyncio.to_thread(load_stats))


@router.post("/stats/inc")
async def stats_inc(req: StatsIncRequest):
    """对应类型导出计数 +1，返回最新 {pdf, json}。"""
    return ok(await asyncio.to_thread(increment_stats, req.kind))
