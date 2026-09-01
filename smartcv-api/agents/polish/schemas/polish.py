"""润色结构化输出的实体类。

作为 response_format 传给 create_agent，让模型输出受约束的结构化 JSON，
再解析成强类型对象返回，保证输出稳定（条数/顺序与输入一致）。
"""

from pydantic import BaseModel, Field


class PolishedItems(BaseModel):
    """润色结果：一条输入对应一条输出，顺序与输入一致。"""

    items: list[str] = Field(default_factory=list)
