"""简历结构化输出的实体类。

与 agents/skill/md2json/schema.md 的字段定义一一对应。
作为 response_format 传给 create_agent，让模型输出受约束的结构化 JSON，
再解析成强类型对象返回，保证输出稳定。
"""

from __future__ import annotations
from typing import Literal, Optional

from pydantic import BaseModel, Field

TextAlign = Literal["left", "center", "right"]
SectionLayout = Literal["horizontal", "vertical"]
ContentType = Literal["iconText", "twoColumn", "timeRange", "tag", "listText", "image", "spacer"]
ListStyle = Literal["bullet", "ordered"]
ImageShape = Literal["circle", "rounded", "original"]


class BaseStyle(BaseModel):
    """章节与内容共有的样式字段。"""

    fontSize: Optional[float] = None
    color: Optional[str] = None
    lineHeight: Optional[float] = None
    textAlign: Optional[TextAlign] = None


class SectionStyle(BaseStyle):
    """章节样式：比内容多 titleSize / gap / spaceBefore。"""

    titleSize: Optional[float] = None
    gap: Optional[float] = None
    spaceBefore: Optional[float] = None


class ContentStyle(BaseStyle):
    """内容样式：比章节多一个可覆盖继承块间距的 gap。"""

    gap: Optional[float] = None


class ListItem(BaseModel):
    """列表文字型的一条列表项。"""

    text: str
    indent: Optional[int] = Field(default=0, ge=0, le=2)


class ContentData(BaseModel):
    """内容的内容：所有类型共用一个对象，各类型只读自己需要的字段。"""

    icon: Optional[str] = None  # iconText
    text: Optional[str] = None  # iconText
    columns: Optional[list[str]] = None  # twoColumn
    separator: Optional[str] = None  # twoColumn
    start: Optional[str] = None  # timeRange
    end: Optional[str] = None  # timeRange
    tags: Optional[list[str]] = None  # tag / iconText 附加标签
    listType: Optional[ListStyle] = None  # listText
    items: Optional[list[ListItem]] = None  # listText
    image: Optional[str] = None  # image：完整 dataURL
    imageSize: Optional[float] = None  # image
    imageShape: Optional[ImageShape] = None  # image
    imageAlign: Optional[TextAlign] = None  # image


class Content(BaseModel):
    """内容：布局窗口内部的内容单元。"""

    id: str
    kind: Literal["content"] = "content"
    type: ContentType
    content: ContentData = Field(default_factory=ContentData)
    style: ContentStyle = Field(default_factory=ContentStyle)
    tight: Optional[bool] = None


class LayoutWindow(BaseModel):
    """布局窗口：叶子窗口放 contents，容器窗口放 rows（可递归嵌套）。"""

    id: str
    layout: SectionLayout
    contents: list[Content] = Field(default_factory=list)
    rows: Optional[list["LayoutWindow"]] = None
    tight: Optional[bool] = None


class Section(BaseModel):
    """章节（页面级）：简历的一节。"""

    id: str
    kind: Literal["section"] = "section"
    title: str = ""
    style: SectionStyle = Field(default_factory=SectionStyle)
    rows: list[LayoutWindow] = Field(default_factory=list)
    pageBreakBefore: Optional[bool] = None


class Resume(BaseModel):
    """整份简历。结构化输出要求 JSON 根是对象，所以用 sections 包一层，
    转给前端时再剥掉，拿到 Section[]。"""

    sections: list[Section]



