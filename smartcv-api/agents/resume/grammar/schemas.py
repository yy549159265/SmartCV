"""全文纠错的结构化输出。

模型只负责指出「哪个坐标的哪段文字错了、完整改成什么」，不返回整份简历。
后端按坐标定位并就地写入，结构和样式完全不动。
"""

from pydantic import BaseModel, Field


class GrammarFix(BaseModel):
    """一个正文文字单元的纠错建议。"""

    s: int | None = Field(None, description="章节序号（0 起）")
    r: int | None = Field(None, description="章节内叶子窗口序号（0 起）")
    c: int | None = Field(None, description="窗口内可改内容序号（0 起）")
    i: int | None = Field(None, description="内容内文字单元序号（0 起）")
    quote: str = Field("", description="该坐标原文开头片段，逐字来自简历，最多 40 字")
    corrected: str = Field("", description="该文字单元修正后的完整正文，不是只写改动片段")
    reason: str = Field("", description="修正了什么：错别字 / 标点 / 语病等")


class GrammarTitleFix(BaseModel):
    """一个章节标题的纠错建议（标题没有 s/r/c/i，用 s 定位章节）。"""

    s: int | None = Field(None, description="章节序号（0 起）")
    original: str = Field("", description="原标题，逐字来自简历")
    corrected: str = Field("", description="修正后的完整标题")
    reason: str = Field("", description="修正了什么")


class GrammarResult(BaseModel):
    """全文纠错的完整结构化结果。"""

    fixes: list[GrammarFix] = Field(default_factory=list, description="正文纠错列表")
    title_fixes: list[GrammarTitleFix] = Field(default_factory=list, description="标题纠错列表")
