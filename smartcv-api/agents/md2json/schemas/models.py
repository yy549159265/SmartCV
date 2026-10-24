"""解析流水线的内部数据结构（不依赖 FastAPI / LangChain，便于单测）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Block:
    """清洗前/后的一个内容块。

    level 有值表示这是一个标题块（来自 content_list 的 text_level 或 Markdown 的 #）；
    page/bbox 只在 content_list 路径里有，用于识别页眉页脚。
    """

    id: str
    text: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    level: int | None = None
    kind: str = "text"  # text | heading | list | table
    meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class DroppedBlock:
    """被清洗规则丢弃的块。只记录 id 和原因，不把正文写进日志/状态。"""

    id: str
    reason: str


@dataclass(slots=True)
class CleanResult:
    blocks: list[Block]
    dropped: list[DroppedBlock] = field(default_factory=list)


@dataclass(slots=True)
class SectionPlan:
    """章节识别结果：标准类型 + 显示标题 + 归入该章节的块。"""

    type: str
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass(slots=True)
class MineruResult:
    """MinerU 解析产物：Markdown 兜底 + 可选的块级 content_list。"""

    markdown: str = ""
    content_list: list[dict] | None = None


@dataclass(slots=True)
class ValidationReport:
    """结构/保真校验结果。只包含 id、计数和覆盖率，不包含用户正文。"""

    coverage: float = 1.0
    total_blocks: int = 0
    unmatched_ids: list[str] = field(default_factory=list)
    missing_tokens: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
