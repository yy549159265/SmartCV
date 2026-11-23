"""招聘关键词处理：各招聘平台适配器共用。

平台按整串精确匹配岗位名，完整岗位名（如 `agent 应用工程师`）几乎检索不到；
这里把规划输出的 queries 提炼成 2～3 个方向关键词，并补中英混排的空格变体。
"""

import re

_CJK_EN_BOUNDARY = re.compile(r"(?<=[A-Za-z0-9])(?=[一-鿿])|(?<=[一-鿿])(?=[A-Za-z])")

# 平台按整串精确匹配，岗位名里的级别词、职位后缀和泛化修饰词会让命中变成 0。
_LEVEL_WORDS = ("高级", "资深", "初级", "中级", "专家级", "senior", "junior", "sr.", "jr.")
_IGNORED_WORDS = (
    "应用工程师",
    "开发工程师",
    "工程师",
    "专家",
    "架构师",
    "研究员",
    "负责人",
    "主管",
    "总监",
    "专员",
    "经理",
    "设计师",
    "助理",
    "实习生",
    "程序员",
    "技术人员",
    "岗位",
)
# 「应用」「开发」只有在「应用工程师 / 开发工程师」这类后缀里才删，单独出现时是方向词
# （如「AI 应用」「软件开发」），必须保留。
_GENERIC_KEYWORDS = {"程序", "程序员", "开发", "研发", "工程师", "技术人员", "软件", "软件工程师"}
_DEFAULT_DIRECTION = "软件开发"
_KEYWORD_SEP = re.compile(r"[\s,，、/|+]+")
_MAX_KEYWORDS = 3


def clean(value: object, limit: int = 0) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if limit else text


def job_keywords(queries: list[str], fallback: str) -> str:
    """从规划检索词里提炼 2～3 个平台关键词。

    规划模型偶尔仍会把完整岗位名当关键词（如 `agent 应用工程师`）；这里按
    词表做确定性清理：去掉级别词和职位后缀，最多保留 3 个词。清理后只剩
    「程序员」「开发」这类泛称时补默认方向「软件开发」。
    """
    raw = next((str(query).strip() for query in queries if str(query or "").strip()), "") or fallback
    text = clean(raw)
    for word in _LEVEL_WORDS:
        text = re.sub(re.escape(word), " ", text, flags=re.IGNORECASE)
    for word in _IGNORED_WORDS:
        text = re.sub(re.escape(word), " ", text, flags=re.IGNORECASE)
    words = [part for part in _KEYWORD_SEP.split(clean(text)) if part]
    keyword = " ".join(words[:_MAX_KEYWORDS])
    if not keyword or keyword in _GENERIC_KEYWORDS:
        return _DEFAULT_DIRECTION
    return keyword


def keyword_variants(keyword: str) -> list[str]:
    """给出检索词候选：原词 + 中英之间补空格的写法；少于两个字的不参与。"""
    variants: list[str] = []

    def add(text: str) -> None:
        text = clean(text)
        if len(text) >= 2 and text not in variants:
            variants.append(text)

    add(keyword)
    add(_CJK_EN_BOUNDARY.sub(" ", clean(keyword)))
    return variants
