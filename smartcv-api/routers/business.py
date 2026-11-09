"""业务接口：简历解析 / 导出 / 统计 / 示例模板。

这些接口面向简历文件本身，不直接承载 agent 对话。
（/resume/parse 内部是确定性解析流水线，只在上传文件和返回结果之间短暂处理，
解析结果直接回给前端，服务端不保存。）
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agents.md2json.schemas.store import create_store, delete_store, get_store
from routers.deps import get_agent_session
from schemas.provider import ProviderConfig, provider_config
from schemas.response import ok
from services.html2pdf import resume_html_to_pdf
from services.pdf2json import parse_resume_document
from services.reference_examples import (
    create_example as create_reference_example,
    get_example as get_reference_example,
    list_examples as list_reference_examples,
)
from services.stats import increment_stats, load_stats

router = APIRouter(prefix="/api", tags=["business"])


class PdfRequest(BaseModel):
    html: str


class StatsIncRequest(BaseModel):
    kind: Literal["pdf", "json"]


@router.post("/resume/parse")
async def resume_parse(
    request: Request,
    file: UploadFile = File(...),
    parser: str = Form("mineru"),
    mineruToken: str = Form(""),
    provider: ProviderConfig = Depends(provider_config),
    session_id: str | None = Depends(get_agent_session),
):
    MAX_UPLOAD = 5 * 1024 * 1024 + 128 * 1024
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件超过 5MB，请压缩后再上传")

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
        store.cancel()
        raise
    except HTTPException:
        raise
    finally:
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


@router.get("/stats")
async def stats_get():
    """读取累计导出次数：{pdf, json}。"""
    return ok(await asyncio.to_thread(load_stats))


@router.post("/stats/inc")
async def stats_inc(req: StatsIncRequest):
    """对应类型导出计数 +1，返回最新 {pdf, json}。"""
    return ok(await asyncio.to_thread(increment_stats, req.kind))


_EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "example"
_EXAMPLE_INDEX = _EXAMPLE_DIR / "index.json"


@router.get("/examples")
async def examples_list():
    """列出 example/ 下的示例简历：直接读目录里的 index.json 清单。"""
    try:
        entries = json.loads(_EXAMPLE_INDEX.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="示例目录里找不到 index.json")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="示例清单不是合法的 JSON")
    if not isinstance(entries, list):
        raise HTTPException(status_code=500, detail="示例清单格式不正确")
    return ok(entries)


@router.get("/examples/{name}")
async def examples_item(name: str):
    """读取单个示例文件的内容（解析成 JSON 返回）。

    只允许普通 json 文件名（不带路径分隔符），杜绝路径穿越；
    校验放在读文件之前，坏请求不会碰到文件系统。
    """
    if "/" in name or "\\" in name or not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="示例文件名不合法")
    path = (_EXAMPLE_DIR / name).resolve()
    if path.parent != _EXAMPLE_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="示例文件不存在")
    try:
        return ok(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="示例文件不是合法的 JSON")


class ReferenceExampleCreate(BaseModel):
    """上传一份优秀示例：三个字段都是必填。"""

    direction: str = Field(..., description="适用职业方向，如「后端开发」")
    description: str = Field(..., description="优秀简历描述：这份示例好在哪里、适合参考什么")
    resume: list[dict] = Field(..., description="优秀简历 JSON（Section[]）")


@router.get("/reference-examples")
async def reference_examples_list():
    """列出示例库（只回元数据，不带简历正文）。"""
    return ok(await asyncio.to_thread(list_reference_examples))


@router.get("/reference-examples/{example_id}")
async def reference_examples_detail(example_id: str):
    """读取单份示例的完整内容（缩略图 / 查看弹窗用）。"""
    record = await asyncio.to_thread(get_reference_example, example_id)
    if record is None:
        raise HTTPException(status_code=404, detail="优秀示例不存在")
    return ok(record)


@router.post("/reference-examples")
async def reference_examples_create(req: ReferenceExampleCreate):
    """新增一份示例。

    没有用户体系，示例库全局共享；上传后不可编辑、不可删除，
    前端会先预览再二次确认才调用这个接口。
    """
    try:
        meta = await asyncio.to_thread(
            create_reference_example, req.direction, req.description, req.resume
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(meta)
