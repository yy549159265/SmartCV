"""默认模板：只描述章节顺序/标题/样式，不携带任何示例正文。

模板与 agent 放在一起（agents/md2json/template.json），与前端 example/ 目录隔离，
因此不会出现在前端的「示例模板」画廊里。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("smartcv")

_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "template.json"

_DEFAULT = {
    "order": [
        "personal_info", "summary", "education", "work", "internship",
        "project", "skills", "awards", "certificates", "campus", "other",
    ],
    "sections": {
        "personal_info": {"title": "", "style": {"gap": 12}},
        "summary": {"title": "个人介绍", "style": {"gap": 8}},
        "education": {"title": "教育经历", "style": {"gap": 8}},
        "work": {"title": "工作经历", "style": {"gap": 8}},
        "internship": {"title": "实习经历", "style": {"gap": 8}},
        "project": {"title": "项目经历", "style": {"gap": 8}},
        "skills": {"title": "职业技能", "style": {"gap": 8}},
        "awards": {"title": "荣誉奖项", "style": {"gap": 8}},
        "certificates": {"title": "证书", "style": {"gap": 8}},
        "campus": {"title": "校园经历", "style": {"gap": 8}},
        "other": {"title": "", "style": {"gap": 8}},
    },
}


@dataclass(frozen=True)
class Template:
    order: list[str]
    sections: dict[str, dict]

    def spec(self, section_type: str) -> dict:
        return self.sections.get(section_type) or self.sections.get("other") or {}

    def title_for(self, section_type: str, fallback: str) -> str:
        # personal_info 的标题按模板留空（示例模板也是空标题）；
        # other 保留简历里的原标题，避免把未知章节改名。
        if section_type == "other":
            return fallback
        return str(self.spec(section_type).get("title", fallback))

    def style_for(self, section_type: str) -> dict:
        style = self.spec(section_type).get("style")
        return style if isinstance(style, dict) else {}

    def order_index(self, section_type: str) -> int:
        try:
            return self.order.index(section_type)
        except ValueError:
            return len(self.order)


@lru_cache(maxsize=1)
def load_template() -> Template:
    data: dict = _DEFAULT
    try:
        raw = json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("sections"), dict):
            data = {
                "order": raw.get("order") if isinstance(raw.get("order"), list) else _DEFAULT["order"],
                "sections": raw["sections"],
            }
    except FileNotFoundError:
        logger.warning("未找到模板 %s，使用内置默认样式", _TEMPLATE_PATH)
    except Exception as exc:
        logger.warning("模板 %s 读取失败（%s），使用内置默认样式", _TEMPLATE_PATH, exc)
    return Template(order=list(data["order"]), sections=dict(data["sections"]))
