"""MinerU 产物 → 干净的内容块。

这里全部是确定性规则，不调用 LLM：
- 去掉图片/HTML/零宽字符/控制字符；
- 去掉页码、页眉页脚、水印、重复段落、明显 OCR 噪声；
- 保留原文文字（只做空白和 Markdown 语法的规范化），保证后续保真校验。

页眉页脚优先用 content_list 的 page_idx + bbox 判断；没有块级信息时
退化为「同一短文本在全文重复出现」的频率规则。
"""

from __future__ import annotations

import html
import math
import re
from html.parser import HTMLParser

from ..schemas.models import Block, CleanResult, DroppedBlock, MineruResult

_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t ]+")
_HEADING_MD = re.compile(r"^(#{1,6})\s+(.+)$")
_BULLET_MD = re.compile(r"^\s*(?:[-*+•●·▪◦–—]|\d{1,2}[.、)])\s+(.+)$")
_TABLE_MD = re.compile(r"^\s*\|.*\|\s*$")

# 明确的页码/页脚写法；不把孤立的年份、数字当页码（交给重复频率规则判断）
_PAGE_LINE = re.compile(
    r"^\s*(?:第\s*\d{1,4}\s*页(?:\s*[/／]?\s*共\s*\d{1,4}\s*页)?"
    r"|共\s*\d{1,4}\s*页"
    r"|page\s*\d{1,4}\s*(?:of|/)\s*\d{1,4}"
    r"|[-—–]\s*\d{1,4}\s*[-—–]\s*"
    r"|\d{1,4}\s*[/／]\s*\d{1,4})\s*$",
    re.I,
)
_WATERMARK = re.compile(
    # 注意：不要用泛化的 www.xxx.com 判断水印，否则会把个人的网站/作品集误删；
    # 图片 URL 由 _IMAGE_URL 单独处理。
    r"(简历模板|模板下载|模板编号|扫码关注|二维码)",
    re.I,
)
# 浏览器/阅读器打印时带的页脚时间，如 2026/10/24 01:15
_PRINT_TIME = re.compile(
    r"^\s*\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?\s*$"
)
# 图片文件名 + 尺寸，如 f054a265-....jpg (1587×2245)
_IMAGE_FILE = re.compile(
    r"^[\w.\-]+\.(?:jpe?g|png|gif|bmp|webp|tiff?)\s*[（(]\s*\d+\s*[×xX*]\s*\d+\s*[）)]\s*$",
    re.I,
)
# 指向图片的裸 URL（简历网站/作品集链接不是图片，不会被这条命中）
_IMAGE_URL = re.compile(
    r"^https?://\S+\.(?:jpe?g|png|gif|bmp|webp|tiff?)(?:\?\S*)?\s*$",
    re.I,
)
_ONLY_SYMBOLS = re.compile(r"^[\W_]+$", re.UNICODE)
_CJK = re.compile(r"[㐀-鿿]")


class _TableHTMLParser(HTMLParser):
    """把 MinerU 的 table_body HTML 转成按行的文本，尽量保留单元格顺序。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._flush_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._flush_cell()
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _flush_cell(self) -> None:
        if self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row:
            self.rows.append([c for c in self._row if c])
        self._row = None

    def close(self) -> None:
        super().close()
        self._flush_row()


def table_html_to_text(raw: str) -> str:
    parser = _TableHTMLParser()
    try:
        parser.feed(raw or "")
        parser.close()
    except Exception:
        # HTMLParser 对畸形 HTML 很宽容，走到这里基本是空内容
        return ""
    return "\n".join(" | ".join(row) for row in parser.rows if row)


def normalize_text(text: str) -> str:
    """只做不改变语义的规范化：空白、零宽字符、Markdown 图片/链接/HTML。"""
    text = html.unescape(text or "")
    text = _ZERO_WIDTH.sub("", text)
    text = _CONTROL.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _IMAGE_MD.sub("", text)

    def _link(matched: re.Match[str]) -> str:
        label, url = matched.group(1).strip(), matched.group(2).strip()
        if not url or url.startswith("#"):
            return label
        if not label or label == url:
            return url
        return f"{label} {url}"

    text = _LINK_MD.sub(_link, text)
    text = _HTML_TAG.sub("", text)
    text = _SPACES.sub(" ", text)
    return text.strip()


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return tuple(float(v) for v in value[:4])  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def blocks_from_content_list(items: list[dict]) -> list[Block]:
    """把 MinerU content_list.json 转成 Block（保留页码/bbox/标题层级）。"""
    blocks: list[Block] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "text").lower()
        if kind in ("image", "figure"):
            # 简历里的图片只可能是头像/装饰，正文解析不需要；头像不在此阶段处理
            continue

        raw_text = item.get("text") or item.get("content") or ""
        if kind in ("table", "table_body"):
            # 表格必须优先用 table_body 还原单元格边界。MinerU 的 text 字段
            # 有时是把整张表拼成一行，按它解析会把学校/学位/专业/时间粘在一起。
            table_html = item.get("table_body") or item.get("html") or ""
            if isinstance(table_html, str) and table_html.strip():
                converted = table_html_to_text(table_html)
                if converted:
                    raw_text = converted
            block_kind = "table"
        elif kind in ("list", "list_item"):
            block_kind = "list"
        else:
            block_kind = "text"

        text = normalize_text(str(raw_text))
        if not text:
            continue

        level = _as_int(item.get("text_level"))
        if level is not None and level <= 0:
            level = None
        if level is not None:
            block_kind = "heading"

        blocks.append(
            Block(
                id=f"b{len(blocks) + 1:04d}",
                text=text,
                page=_as_int(item.get("page_idx")),
                bbox=_as_bbox(item.get("bbox")),
                level=level,
                kind=block_kind,
            )
        )
    return blocks


def _join_paragraph(lines: list[str]) -> str:
    """把同一段落的换行合并；中文之间直接拼接，中英文之间补一个空格。"""
    if not lines:
        return ""
    out = lines[0].strip()
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if out and _CJK.search(out[-1]) and _CJK.search(line[0]):
            out += line
        else:
            out += " " + line
    return out


def blocks_from_markdown(markdown: str) -> list[Block]:
    """full.md 兜底：按标题/列表/表格/段落切块。"""
    lines = (markdown or "").splitlines()
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = normalize_text(_join_paragraph(paragraph))
        paragraph.clear()
        if text:
            blocks.append(Block(id=f"b{len(blocks) + 1:04d}", text=text, kind="text"))

    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        i += 1

        if not raw:
            flush_paragraph()
            continue

        heading = _HEADING_MD.match(raw)
        if heading:
            flush_paragraph()
            text = normalize_text(heading.group(2))
            if text:
                blocks.append(
                    Block(
                        id=f"b{len(blocks) + 1:04d}",
                        text=text,
                        level=len(heading.group(1)),
                        kind="heading",
                    )
                )
            continue

        if _TABLE_MD.match(raw):
            flush_paragraph()
            table_lines = [raw]
            while i < len(lines) and _TABLE_MD.match(lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1
            text = normalize_text("\n".join(table_lines))
            if text:
                blocks.append(Block(id=f"b{len(blocks) + 1:04d}", text=text, kind="table"))
            continue

        bullet = _BULLET_MD.match(raw)
        if bullet:
            flush_paragraph()
            text = normalize_text(bullet.group(1))
            if text:
                blocks.append(Block(id=f"b{len(blocks) + 1:04d}", text=text, kind="list"))
            continue

        paragraph.append(raw)

    flush_paragraph()
    return blocks


def _text_key(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _is_obvious_noise(text: str) -> str | None:
    """返回丢弃原因；None 表示保留。"""
    if not text:
        return "empty"
    if _PAGE_LINE.match(text):
        return "page_number"
    if _PRINT_TIME.match(text):
        return "print_time"
    if _IMAGE_FILE.match(text):
        return "image_file"
    if _IMAGE_URL.match(text):
        return "image_url"
    if _WATERMARK.search(text):
        return "watermark"
    if _ONLY_SYMBOLS.match(text):
        return "symbols"
    if len(text) <= 1 and not text.isalnum():
        return "ocr_noise"
    if len(text) >= 5 and len(set(text)) == 1:
        return "ocr_repeat"
    if text.count("�") / max(1, len(text)) > 0.2:
        return "ocr_noise"
    return None


def clean_blocks(blocks: list[Block]) -> CleanResult:
    """去噪声、去页眉页脚、去重复块，返回保序的干净块。"""
    kept: list[Block] = []
    dropped: list[DroppedBlock] = []

    # 1) 明显噪声
    for block in blocks:
        text = normalize_text(block.text)
        if not text:
            dropped.append(DroppedBlock(block.id, "empty"))
            continue
        reason = _is_obvious_noise(text)
        if reason:
            dropped.append(DroppedBlock(block.id, reason))
            continue
        block.text = text
        kept.append(block)

    # 2) 页眉页脚：优先 bbox + 页码，其次全篇重复频率
    page_numbers = {b.page for b in kept if b.page is not None}
    page_count = len(page_numbers)
    drop_ids: set[str] = set()

    if page_count >= 2 and any(b.bbox for b in kept):
        by_page: dict[int, list[Block]] = {}
        for b in kept:
            if b.page is not None:
                by_page.setdefault(b.page, []).append(b)

        seen_pages: dict[str, set[int]] = {}
        first_block: dict[str, Block] = {}
        for page, page_blocks in by_page.items():
            with_bbox = [b for b in page_blocks if b.bbox is not None]
            if not with_bbox:
                continue
            top = min(b.bbox[1] for b in with_bbox)  # type: ignore[union-attr]
            bottom = max(b.bbox[3] for b in with_bbox)  # type: ignore[union-attr]
            if bottom <= top:
                continue
            margin = (bottom - top) * 0.12
            for b in with_bbox:
                if b.kind == "heading":
                    continue
                y0, y1 = b.bbox[1], b.bbox[3]  # type: ignore[index]
                if y0 > top + margin and y1 < bottom - margin:
                    continue
                key = _text_key(b.text)
                if not key or len(key) > 80:
                    continue
                seen_pages.setdefault(key, set()).add(page)
                first_block.setdefault(key, b)

        threshold = max(2, math.ceil(page_count * 0.5))
        for key, pages in seen_pages.items():
            if len(pages) < threshold:
                continue
            first = first_block[key]
            # 页码/水印全删；重复的姓名/联系方式/页眉只保留第一次出现
            reason = "page_number" if _PAGE_LINE.match(first.text) else "repeated_header_footer"
            for b in kept:
                if b is not first and _text_key(b.text) == key:
                    drop_ids.add(b.id)
                    dropped.append(DroppedBlock(b.id, reason))

    elif page_count >= 2:
        # 没有 bbox（full.md 兜底）：同一短文本出现 3 次以上视为页眉/页脚
        short_counts: dict[str, list[Block]] = {}
        for b in kept:
            if b.kind == "heading":
                continue
            key = _text_key(b.text)
            if key and len(key) <= 40:
                short_counts.setdefault(key, []).append(b)
        for key, group in short_counts.items():
            if len(group) < 3:
                continue
            for b in group[1:]:
                drop_ids.add(b.id)
                dropped.append(DroppedBlock(b.id, "repeated_header_footer"))

    # 3) 精确重复的长块（同一段内容被解析了两遍）
    seen_text: set[str] = set()
    for b in kept:
        if b.id in drop_ids:
            continue
        key = _text_key(b.text)
        if len(key) < 15:
            continue
        if key in seen_text:
            drop_ids.add(b.id)
            dropped.append(DroppedBlock(b.id, "duplicate"))
        else:
            seen_text.add(key)

    cleaned = [b for b in kept if b.id not in drop_ids]
    return CleanResult(blocks=cleaned, dropped=dropped)


def normalize_document(result: MineruResult) -> CleanResult:
    """MinerU 产物 → 清洗后的块。content_list 优先，full.md 兜底。"""
    blocks = blocks_from_content_list(result.content_list or [])
    if not blocks:
        blocks = blocks_from_markdown(result.markdown or "")
    return clean_blocks(blocks)
