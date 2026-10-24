"""MinerU 产物 → 简历 JSON 的解析入口。

整个解析只有两处需要“智能”：清洗和语义结构化，都放在这个文件里：
- 清洗调用 utils.normalize 的确定性规则（不调模型）；
- 结构化只调用一次 llm.invoke，让模型把简历规范成语义字段 JSON
  （CanonicalResume，提示词见 system_prompt_md2json.md），不做任何排版。
排版、兜底分章、校验都是 utils 里的纯代码，模型不参与。

流程：CLEAN → SEGMENT → CONVERT → VALIDATE。

- 模型不可用、超时或输出不合法时，回退到确定性分章 + 规则转换；
- 步骤状态写进 PDF2ResumeStore，供 /api/resume/parse/status 轮询；
  store 只存进度，不存简历正文，请求结束即删除。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

from .schemas.canonical import CanonicalResume, normalize_payload
from .schemas.models import Block, MineruResult
from .schemas.resume import Section
from .schemas.store import PDF2ResumeStore, Step
from .utils.build import build_canonical_sections, build_sections
from .utils.normalize import normalize_document
from .utils.sections import merge_sections, split_sections
from .utils.template import load_template
from .utils.validate import validate_sections

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_md2json.md").read_text(
    encoding="utf-8"
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# 结构化输出比较重，给足时间；但也不能让一次解析无限挂着
_TIMEOUT_S = 120


def blocks_to_markdown(blocks: list[Block]) -> str:
    """把清洗后的块还原成紧凑 Markdown，保留标题层级、列表和表格行。

    只用于喂给大模型，不再参与最终的文本保真判断。
    """
    lines: list[str] = []
    for block in blocks:
        text = (block.text or "").strip()
        if not text:
            continue

        if block.kind == "heading" or block.level:
            level = block.level if block.level and block.level > 0 else 1
            title = text.lstrip("#").strip()
            if title:
                lines.append(f"{'#' * min(level, 6)} {title}")
        elif block.kind == "list":
            for raw in text.splitlines():
                item = raw.strip().lstrip("-*+•●·▪◦–—").strip()
                if item:
                    lines.append(f"- {item}")
        else:
            # table 的文本已经是 “A | B | C” 形式，按原样保留
            lines.extend(line for line in text.splitlines() if line.strip())

        lines.append("")

    return "\n".join(lines).strip()


def parse_json_object(text: str) -> dict:
    """从模型回复里取出 JSON 对象；失败返回 {}。"""
    raw = (text or "").strip()
    if not raw:
        return {}
    fenced = _FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def structure_resume(
    provider: ProviderConfig | None,
    blocks: list[Block],
    *,
    session_id: str | None = None,
) -> CanonicalResume | None:
    """调用一次 llm.invoke，把简历块规范成 CanonicalResume；失败返回 None。"""
    if provider is None or not blocks:
        return None

    markdown = blocks_to_markdown(blocks)
    if not markdown:
        return None

    try:
        llm = choose_llm(provider, temperature=0, timeout=_TIMEOUT_S)
        response = llm.invoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=f"<resume>\n{markdown}\n</resume>"),
            ]
        )
        content = response.content
        if isinstance(content, list):
            # 少数 OpenAI 兼容网关会返回 content blocks
            content = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            )
        elif not isinstance(content, str):
            content = str(content)
        payload = parse_json_object(content)
        if not payload:
            logger.warning("简历规范化：模型未返回合法 JSON session=%s", session_id)
            return None
        canonical = CanonicalResume.model_validate(normalize_payload(payload))
    except Exception as exc:  # 网络/鉴权/超时/校验失败都走确定性兜底
        logger.warning(
            "简历规范化失败（%s），回退确定性流水线 session=%s",
            exc.__class__.__name__,
            session_id,
        )
        return None

    if not canonical.has_content():
        logger.warning("简历规范化：模型返回空内容 session=%s", session_id)
        return None

    logger.info(
        "简历规范化：教育 %d、工作 %d、实习 %d、项目 %d、技能 %d、奖项 %d、其他 %d session=%s",
        len(canonical.education),
        len(canonical.work),
        len(canonical.internship),
        len(canonical.project),
        len(canonical.skills),
        len(canonical.awards),
        len(canonical.other),
        session_id,
    )
    return canonical


def run_parse_pipeline(
    result: MineruResult,
    store: PDF2ResumeStore,
    provider: ProviderConfig | None = None,
    session_id: str | None = None,
) -> list[Section]:
    """MinerU 产物 → 简历 Section[]。异常会把对应步骤标 failed。"""
    # 1) 清洗：去页眉页脚/页码/乱码/重复段落
    store.start_step(Step.CLEAN)
    try:
        clean = normalize_document(result)
    except Exception as exc:
        logger.exception("简历清洗失败 session=%s", session_id)
        store.fail_step(Step.CLEAN, "简历文本清洗失败")
        raise RuntimeError("简历文本清洗失败") from exc
    store.finish_step(Step.CLEAN)
    logger.info("简历清洗：保留 %d 块，丢弃 %d 块", len(clean.blocks), len(clean.dropped))

    # 2) 章节识别：优先让模型做语义规范化；失败再走确定性分章
    store.start_step(Step.SEGMENT)
    canonical: CanonicalResume | None = None
    plans = None
    try:
        if provider is not None:
            canonical = structure_resume(provider, clean.blocks, session_id=session_id)

        if canonical is None:
            # 模型不可用时不再额外调一次 LLM 分类标题：
            # 精确别名匹配不上的章节保留为 other，原文和原标题都不会丢。
            plans = merge_sections(split_sections(clean.blocks))
    except Exception as exc:
        logger.exception("简历章节识别失败 session=%s", session_id)
        store.fail_step(Step.SEGMENT, "简历章节识别失败")
        raise RuntimeError("简历章节识别失败") from exc
    store.finish_step(Step.SEGMENT)
    if canonical is not None:
        logger.info("简历章节：使用大模型规范化结果")
    else:
        logger.info("简历章节：确定性识别 %d 个", len(plans or []))

    # 3) 转 JSON：纯代码排版；模型只提供语义字段
    store.start_step(Step.CONVERT)
    try:
        template = load_template()
        sections = []
        if canonical is not None:
            try:
                sections = build_canonical_sections(canonical, template)
            except Exception:
                # 排版代码有问题也不应该让整次上传失败
                logger.exception("简历 JSON：规范化排版失败 session=%s", session_id)
                sections = []
        if not sections:
            # 模型返回了内容但排不出章节 / 没有模型：退回确定性路径，保证有结果
            if canonical is not None:
                logger.warning("简历 JSON：规范化结果为空，回退确定性流水线 session=%s", session_id)
            plans = plans or merge_sections(split_sections(clean.blocks))
            sections = build_sections(plans, template)
    except Exception as exc:
        logger.exception("简历 JSON 构建失败 session=%s", session_id)
        store.fail_step(Step.CONVERT, "简历 JSON 构建失败")
        raise RuntimeError("简历 JSON 构建失败") from exc
    store.finish_step(Step.CONVERT)

    # 4) 校验：覆盖率与关键信息是否丢失（只记计数/ID，不记正文）
    store.start_step(Step.VALIDATE)
    try:
        # canonical 路径没有规则切分出的 plans，传 None 只校验正文块
        report = validate_sections(clean.blocks, plans, sections)
    except Exception as exc:
        # 校验只是兜底，失败不应该让已经生成的结果作废
        logger.warning("简历校验异常（%s），跳过校验", exc.__class__.__name__)
        report = None
    if report is not None:
        logger.info(
            "简历校验：%d 个章节，%d 块正文，覆盖率 %.1f%%，未匹配 %d 块",
            len(sections),
            report.total_blocks,
            report.coverage * 100,
            len(report.unmatched_ids),
        )
        for warning in report.warnings:
            logger.warning("简历校验：%s", warning)
    store.finish_step(Step.VALIDATE)

    return sections
