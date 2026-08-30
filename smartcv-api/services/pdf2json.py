"""
文档解析服务：用 docling 把 PDF / Word 解析成结构化文本（Markdown）。

按"是否有文字层"分两条路径（见 parse_resume_document，流程图）：

  A. 有文字层的电子版 PDF / Word
      直接抽取文字，零 OCR、快、100% 准确。
  B. 扫描/图片型 PDF（无文字层）
      渲染页面为图片 → 版面分析模型（标题/段落/表格/照片区）
      → OCR 提取文字 + TableFormer 还原表格。

docling 也提供按区域自动判断（OcrMode.DEFAULT / PDF_AWARE_LAYOUT_REGIONS），
但那是把 OCR 模型挂在整个 pipeline 上——即使文字层齐全，EasyOCR 权重照样加载。
这里在文档级别先判一次，文字层齐全就直接用不带 OCR 的转换器，真正零 OCR。

注意：
  - 需要安装 docling：pip install docling
  - 首次跑扫描件路径会下载布局/表格/EasyOCR 中文模型权重（一次性）
  - .docx / .pdf 支持好；老的 .doc（二进制格式）docling 支持有限，
    建议让用户另存为 .docx 或 .pdf

MinerU 云解析服务：把本地 PDF/Word 上传到 MinerU，拿回 Markdown。

与 docling 本地解析不同，MinerU 是异步云服务，v4 Standard API 流程：
  1. POST /file-urls/batch        申请 OSS 签名上传链接 → batch_id + file_urls
  2. PUT 文件字节到 file_urls[0]  （签名链接，不要 Content-Type）
  3. 上传完系统自动提交任务，无需再调提交接口
  4. 轮询 GET /extract-results/batch/{batch_id} 直到 state=done
  5. 下载 full_zip_url，解压取 full.md

注意两种响应信封：
  成功   {"code":0,"data":{...},"msg":"ok"}
  鉴权失败 {"success":false,"msgCode":"A0202","msg":"..."}
"""
import asyncio
import logging
import time
import uuid
import zipfile
from io import BytesIO

import httpx
import pypdfium2 as pdfium
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrMode,
    PdfPipelineOptions,
    TableFormerMode,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from fastapi import HTTPException, Request, UploadFile

from agents.md2json.agent import run_resume_agent
from agents.md2json.schemas.store import PDF2ResumeStore, Step
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_ALLOWED_SUFFIXES = (".pdf", ".docx")
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# 文字层判定阈值：扫描件 pypdfium2 能取到的字符数≈0；真正的电子版简历至少几百字。
# 取 50 把"只剩页码之类的残缺文字层"也归到 OCR 路径（正确性优先）。
_TEXT_LAYER_MIN_CHARS = 50


def _build_pdf_options(do_ocr: bool) -> PdfPipelineOptions:
    opts = PdfPipelineOptions()
    opts.do_ocr = do_ocr
    if do_ocr:
        # 必须直接指定 EasyOcrOptions（kind 判别），别用默认的 OcrAutoOptions：
        # auto 选引擎时只透传 mode、把 lang 丢掉，EasyOCR 会退回默认
        # ["fr","de","es","en"]，里面没有中文，中文简历就全识别成乱码/英文。
        opts.ocr_options = EasyOcrOptions(lang=["ch_sim", "en"])
        # 只对"没有 PDF 文字单元"的版面区域跑 OCR，有文字层的区域直接取文本。
        opts.ocr_options.mode = OcrMode.PDF_AWARE_LAYOUT_REGIONS
        # 表格用 TableFormer 还原，用高精度档。
        opts.table_structure_options.mode = TableFormerMode.ACCURATE
    return opts


# 两个转换器：OCR 模型（EasyOCR 中文权重几十 MB）只在 OCR 转换器首次 convert 时才
# 加载，所以快速路径（有文字层）永远不会碰到它。
_fast_converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=_build_pdf_options(do_ocr=False)
        )
    }
)
_ocr_converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=_build_pdf_options(do_ocr=True)
        )
    }
)


def _has_text_layer(content: bytes) -> bool:
    """用 pypdfium2 直接读 PDF 文字层，判断是不是电子版。

    扫描件没有文字层，能取到的字符数≈0；电子版能取到完整文本。
    检测失败时保守起见返回 False（走 OCR 路径，正确性优先）。
    """
    total = 0
    try:
        pdf = pdfium.PdfDocument(content)
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                textpage = page.get_textpage()
                total += len(textpage.get_text_range().strip())
                textpage.close()
                page.close()
        finally:
            pdf.close()
    except Exception:
        return False
    return total >= _TEXT_LAYER_MIN_CHARS


def _page_nos_with_items(doc) -> set[int]:
    """docling 结果里"有内容"的页号集合：doc 级 item 按 prov 里的 page_no 归属到页。"""
    pages: set[int] = set()
    for item in list(doc.texts) + list(doc.pictures) + list(doc.tables):
        for prov in item.prov:
            pages.add(prov.page_no)
    return pages


def _is_incomplete(doc, content: bytes) -> bool:
    """docling 转换结果是否缺页：某页一个内容单元都没有（页数对不上 PDF 本身也算）。

    图片型 PDF 的 OCR 冷启动偶发丢页 —— 实测新进程第一次转换，第一页整个没识别
    出来（doc.texts 只剩第二页内容）；检测到缺页触发一次重试即可救回。
    """
    try:
        pdf = pdfium.PdfDocument(content)
        total_pages = len(pdf)
        pdf.close()
    except Exception:
        total_pages = None
    if total_pages is None:
        return False
    return len(_page_nos_with_items(doc)) < total_pages


_BASE = "https://mineru.net/api/v4"
_POLL_INTERVAL_S = 3
_POLL_TIMEOUT_S = 180


def _unwrap(resp: httpx.Response, context: str) -> dict:
    """把 MinerU 两种响应信封统一成 data 字典，出错抛中文 HTTPException。"""
    try:
        body = resp.json()
    except ValueError:
        raise HTTPException(
            status_code=502, detail=f"MinerU {context}失败：HTTP {resp.status_code}"
        )
    if isinstance(body, dict) and body.get("success") is False:
        msg_code = body.get("msgCode", "")
        if msg_code in ("A0202", "A0211"):
            raise HTTPException(
                status_code=401, detail=f"MinerU Token 无效或已过期（{msg_code}）"
            )
        raise HTTPException(
            status_code=502, detail=f"MinerU 鉴权失败：{body.get('msg', msg_code)}"
        )
    if body.get("code") != 0:
        raise HTTPException(
            status_code=502,
            detail=f"MinerU {context}失败：{body.get('msg', body.get('msgCode', '未知错误'))}",
        )
    return body.get("data") or {}


async def _request_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    **kwargs,
) -> httpx.Response:
    """对瞬时传输错误（TLS 握手失败 / 拒连 / 超时）做有限重试。

    只重试「没拿到响应」的传输层错误；拿到 HTTP 状态码的错误（如 401/502）
    不重试，交给 _unwrap 转成可读错误。MinerU 下载结果时偶发 TLS 握手被重置，
    重连一次通常就能成功。
    """
    last_exc: httpx.TransportError | None = None
    for i in range(attempts):
        try:
            return await client.request(method, url, **kwargs)
        except httpx.TransportError as e:
            last_exc = e
            if i < attempts - 1:
                logger.warning(
                    "MinerU %s %s 传输失败（%s），重试 %d/%d",
                    method, url, e, i + 1, attempts,
                )
                await asyncio.sleep(1 + i)
    if last_exc is not None:
        raise last_exc
    raise httpx.ConnectError("MinerU 传输请求失败")


async def _poll_result(client: httpx.AsyncClient, headers: dict, batch_id: str) -> dict:
    """轮询批量结果直到 done/failed，返回该文件的解析项。"""
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    while True:
        r = await _request_retry(
            client, "GET", f"{_BASE}/extract-results/batch/{batch_id}", headers=headers
        )
        data = _unwrap(r, "查询结果")
        results = data.get("extract_result") or []
        if results:
            item = results[0]
            state = item.get("state", "")
            if state == "done":
                return item
            if state == "failed":
                detail = item.get("err_msg") or "未知错误"
                raise HTTPException(status_code=502, detail=f"MinerU 解析失败：{detail}")
        if time.monotonic() >= deadline:
            raise HTTPException(status_code=504, detail="MinerU 解析超时，请稍后重试")
        await asyncio.sleep(_POLL_INTERVAL_S)


async def parse_with_mineru(
    content: bytes, filename: str, token: str, session_id: str | None = None
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        # 1. 申请上传链接
        r = await _request_retry(
            client, "POST", f"{_BASE}/file-urls/batch",
            headers=headers,
            json={
                # data_id 是这条 MinerU 任务的业务关联键，直接用 agent 会话 id，
                # 这样 MinerU 侧的任务能对上"哪次简历解析 / 哪个用户"。
                "files": [{"name": filename, "data_id": session_id or uuid.uuid4().hex}],
                "model_version": "vlm",
            },
        )
        data = _unwrap(r, "申请上传链接")
        batch_id = data.get("batch_id")
        upload_urls = data.get("file_urls") or []
        if not batch_id or not upload_urls:
            raise HTTPException(
                status_code=502, detail="MinerU 申请上传链接失败：返回数据不完整"
            )

        # 2. 上传文件（签名链接，不要 Content-Type）
        up = await _request_retry(client, "PUT", upload_urls[0], content=content)
        if up.status_code != 200:
            raise HTTPException(
                status_code=502, detail=f"MinerU 文件上传失败：HTTP {up.status_code}"
            )

        # 3-4. 轮询结果
        item = await _poll_result(client, headers, batch_id)
        zip_url = item.get("full_zip_url")
        if not zip_url:
            raise HTTPException(status_code=502, detail="MinerU 结果缺少下载链接")

        # 5. 下载 zip，解出 full.md
        zr = await _request_retry(client, "GET", zip_url)
        if zr.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"MinerU 结果下载失败：HTTP {zr.status_code}",
            )
        markdown = _extract_full_md(zr.content)

        # 拿到 MinerU 解析的 Markdown，返回交给 md2json agent 转简历 JSON。
        return markdown


def _extract_full_md(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if name.endswith("full.md"):
                return z.read(name).decode("utf-8", errors="replace")
        md_names = [n for n in z.namelist() if n.endswith(".md")]
        if md_names:
            return z.read(md_names[0]).decode("utf-8", errors="replace")
    raise HTTPException(status_code=502, detail="MinerU 结果压缩包里没有 Markdown")


async def parse_resume_document(
    file: UploadFile,
    provider: ProviderConfig,
    store: PDF2ResumeStore,
    request: Request,
    parser: str = "docling",
    mineru_token: str = "",
    session_id: str | None = None,
) -> PDF2ResumeStore:
    """上传校验 → 文档解析 → 交给 run_resume_agent 转骨架 JSON。

    store 承载各步骤状态，供 /api/resume/parse/status 轮询；每个步骤边界检查
    客户端是否断开，断开则 store.cancel() 并抛 CancelledError 中止后续 LLM 调用。
    agent（含 LLM 网络调用）用 to_thread 跑，避免卡住事件循环挡住状态轮询。
    """

    async def check_disconnected() -> None:
        if await request.is_disconnected():
            store.cancel()
            raise asyncio.CancelledError()

    # 1. 文件上传与校验
    store.start_step(Step.UPLOAD)
    # 只允许 .pdf / .docx（老的 .doc 二进制格式 docling 支持有限，让用户另存）
    filename = file.filename or ""
    if not filename.lower().endswith(_ALLOWED_SUFFIXES):
        store.fail_step(Step.UPLOAD, "只支持 .pdf / .docx 格式")
        raise HTTPException(status_code=400, detail="只支持 .pdf / .docx 格式")

    # 只读 5MB+1 字节：超了立刻拒，不会把超大文件整个读进内存。
    content = await file.read(_MAX_FILE_SIZE + 1)
    if len(content) > _MAX_FILE_SIZE:
        store.fail_step(Step.UPLOAD, "文件超过 5MB，请压缩后再上传")
        raise HTTPException(status_code=413, detail="文件超过 5MB，请压缩后再上传")
    store.finish_step(Step.UPLOAD)
    await check_disconnected()

    # 2. 文档解析：MinerU 云解析 or docling 本地
    store.start_step(Step.PARSE)
    if parser == "mineru":
        if not mineru_token:
            store.fail_step(Step.PARSE, "使用 MinerU 需填写 Token")
            raise HTTPException(status_code=400, detail="使用 MinerU 需填写 Token")
        try:
            markdown = await parse_with_mineru(content, filename, mineru_token, session_id)
        except httpx.HTTPError as e:
            # 传输层错误（DNS / TLS 握手 / 超时 / 拒连）会直接抛 httpx 异常，
            # 这里转成可读中文，让前端能看到是「连不上 MinerU」而不是裸 500。
            store.fail_step(Step.PARSE, "MinerU 连接失败")
            raise HTTPException(
                status_code=502,
                detail=f"MinerU 连接失败（{e.__class__.__name__}）：{e}",
            )
    else:
        # docling 按文字层选路径：电子版（PDF 有文字层 / Word）→ 快速直抽零 OCR；
        # 扫描/图片型 PDF → OCR 管线（渲染→版面分析→OCR→TableFormer）。
        is_pdf = filename.lower().endswith(".pdf")
        converter = _ocr_converter if is_pdf and not _has_text_layer(content) else _fast_converter

        # convert 是 CPU 密集的阻塞调用，用 asyncio.to_thread 扔到线程池，
        # 避免卡住 FastAPI 的事件循环。整个 转换→缺页检测→重试 包成一个线程函数，
        # 中间不在线程里碰事件循环。
        def _convert() -> str:
            result = converter.convert(DocumentStream(name=filename, stream=BytesIO(content)))
            doc = result.document
            # 图片型 PDF 的 OCR 偶发丢页（冷启动第一次转换尤甚），缺页重跑一次：
            # 重试时模型已加载，基本必成功。重试也失败就按原结果返回，不无限循环。
            if converter is _ocr_converter and _is_incomplete(doc, content):
                logger.warning("docling OCR 首轮解析缺页（%s），重试一次", filename)
                doc = converter.convert(DocumentStream(name=filename, stream=BytesIO(content))).document
            return doc.export_to_markdown()

        markdown = await asyncio.to_thread(_convert)
    store.finish_step(Step.PARSE)
    await check_disconnected()

    # 3. 合并后的单 agent：先整理标记文本，再调用工具构造 JSON。
    #    LLM 网络调用是阻塞的，放线程里跑，事件循环留着服务状态轮询。
    return await asyncio.to_thread(run_resume_agent, provider, store, markdown, session_id)
