"""LLM 输出的规范化简历 IR（语义层）。

这一层只描述「简历里有什么」，不描述「怎么排版」：
- 教育一条记录里，时间/学校/专业/学位是四个独立字段；
- 工作一条记录里，时间/公司/职位/描述是四个独立字段；
- 技能按组拆分，奖项/证书一条一项。

排版由 build.py 的 build_canonical_sections 按固定规则完成，LLM 不碰 Section /
LayoutWindow 这类布局结构，避免它把字段又揉成一行。
"""

from __future__ import annotations

from typing import Any, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _nulls_to_empty(cls, data: Any) -> Any:
        """模型偶尔会输出 null；按字段类型换成 "" / []，不让整份结果作废。"""
        if not isinstance(data, dict):
            return data
        fixed = dict(data)
        for name, field in cls.model_fields.items():
            if name in fixed and fixed[name] is None:
                annotation = field.annotation
                if annotation is str:
                    fixed[name] = ""
                elif get_origin(annotation) is list:
                    fixed[name] = []
        return fixed


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_text_list(value: Any) -> list[str]:
    """把 LLM 常见的「字符串 / 字符串数组 / {text: ...} 数组」统一成字符串数组。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _as_text(
                item.get("text")
                or item.get("name")
                or item.get("value")
                or item.get("title")
            )
        else:
            text = _as_text(item)
        if text:
            result.append(text)
    return result


class Personal(_Model):
    name: str = ""
    job_title: str = ""
    phone: str = ""
    email: str = ""
    location: str = ""
    website: str = ""
    extra: list[str] = Field(default_factory=list)

    @field_validator("extra", mode="before")
    @classmethod
    def _extra(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class EducationItem(_Model):
    start: str = ""
    end: str = ""
    time: str = ""  # 兼容模型仍输出整段时间的情况
    school: str = ""
    major: str = ""
    degree: str = ""
    details: list[str] = Field(default_factory=list)

    @field_validator("details", mode="before")
    @classmethod
    def _details(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class WorkItem(_Model):
    start: str = ""
    end: str = ""
    time: str = ""
    company: str = ""
    title: str = ""
    description: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("description", "tags", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class ProjectItem(_Model):
    start: str = ""
    end: str = ""
    time: str = ""
    name: str = ""
    role: str = ""
    description: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("description", "tags", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class SkillGroup(_Model):
    group: str = ""
    items: list[str] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class CampusItem(_Model):
    start: str = ""
    end: str = ""
    time: str = ""
    organization: str = ""
    role: str = ""
    description: list[str] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _description(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class OtherSection(_Model):
    title: str = ""
    items: list[str] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: Any) -> list[str]:
        return _as_text_list(value)


class CanonicalResume(_Model):
    personal: Personal = Field(default_factory=Personal)
    summary: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    work: list[WorkItem] = Field(default_factory=list)
    internship: list[WorkItem] = Field(default_factory=list)
    project: list[ProjectItem] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    campus: list[CampusItem] = Field(default_factory=list)
    other: list[OtherSection] = Field(default_factory=list)

    @field_validator("personal", mode="before")
    @classmethod
    def _personal(cls, value: Any) -> Any:
        return value or {}

    @field_validator("summary", "awards", "certificates", mode="before")
    @classmethod
    def _text_lists(cls, value: Any) -> list[str]:
        return _as_text_list(value)

    @field_validator("education", "work", "internship", "project", "campus", mode="before")
    @classmethod
    def _model_lists(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return value
        return []

    @field_validator("other", mode="before")
    @classmethod
    def _other(cls, value: Any) -> Any:
        """兼容模型把未知章节写成字符串数组的情况，不丢掉这些内容。"""
        if value is None:
            return []
        if isinstance(value, str):
            return [{"title": "其他", "items": [value]}]
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, list):
            return []
        result: list[dict] = []
        loose: list[str] = []
        for item in value:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str) and item.strip():
                loose.append(item.strip())
        if loose:
            result.append({"title": "其他", "items": loose})
        return result

    @field_validator("skills", mode="before")
    @classmethod
    def _skills(cls, value: Any) -> Any:
        """兼容 LLM 把技能写成 ["Python", "Java"] 或 [{name, items}] 的情况。"""
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            return []
        result: list[dict] = []
        for item in value:
            if isinstance(item, str):
                result.append({"group": "", "items": [item]})
            elif isinstance(item, dict):
                fixed = dict(item)
                if "group" not in fixed:
                    fixed["group"] = fixed.get("category") or fixed.get("name") or ""
                if "items" not in fixed:
                    fixed["items"] = fixed.get("skills") or fixed.get("list") or []
                result.append(fixed)
        return result

    def has_content(self) -> bool:
        p = self.personal
        return bool(
            any(
                [
                    p.name,
                    p.job_title,
                    p.phone,
                    p.email,
                    p.location,
                    p.website,
                    p.extra,
                ]
            )
            or self.summary
            or self.education
            or self.work
            or self.internship
            or self.project
            or self.skills
            or self.awards
            or self.certificates
            or self.campus
            or self.other
        )


# LLM 偶尔会用近义键名；在进入 Pydantic 之前统一一下，减少无谓的回退。
_TOP_ALIASES = {
    "personal_info": "personal",
    "personalinfo": "personal",
    "basic_info": "personal",
    "basicinfo": "personal",
    "contact": "personal",
    "summary_text": "summary",
    "self_evaluation": "summary",
    "work_experience": "work",
    "workexperience": "work",
    "experience": "work",
    "internships": "internship",
    "internship_experience": "internship",
    "projects": "project",
    "project_experience": "project",
    "skill": "skills",
    "technical_skills": "skills",
    "award": "awards",
    "honors": "awards",
    "honor_awards": "awards",
    "certificate": "certificates",
    "certifications": "certificates",
    "campus_experience": "campus",
    "others": "other",
    # 模型偶尔会把键名翻译成中文；保留这些兜底，避免整份结果作废
    "个人信息": "personal",
    "基本信息": "personal",
    "联系方式": "personal",
    "自我评价": "summary",
    "个人介绍": "summary",
    "自我介绍": "summary",
    "个人优势": "summary",
    "教育经历": "education",
    "教育背景": "education",
    "工作经历": "work",
    "工作经验": "work",
    "实习经历": "internship",
    "项目经历": "project",
    "项目经验": "project",
    "职业技能": "skills",
    "专业技能": "skills",
    "技能": "skills",
    "荣誉奖项": "awards",
    "获奖经历": "awards",
    "证书": "certificates",
    "资格证书": "certificates",
    "校园经历": "campus",
    "社团经历": "campus",
    "其他": "other",
    "其他信息": "other",
}


def normalize_payload(data: Any) -> dict:
    """把 LLM 返回的原始 dict 规范成 CanonicalResume 能吃的形状。"""
    if not isinstance(data, dict):
        return {}
    # 有些模型会包一层 {resume: {...}} / {data: {...}}
    for key in ("resume", "data", "result"):
        nested = data.get(key)
        if isinstance(nested, dict) and not data.get("personal"):
            data = nested
            break

    fixed: dict[str, Any] = {}
    for key, value in data.items():
        raw_key = str(key).strip()
        normalized = raw_key.lower().replace(" ", "_").replace("-", "_")
        target = _TOP_ALIASES.get(normalized, raw_key)
        if target not in fixed:
            fixed[target] = value
    return fixed
