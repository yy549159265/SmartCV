"""原文核对与数字核对。

问题包里的每个事实都要能回到用户确认后的画像：

  - 锚点 / 证据引用 → norm_text 后必须在简历文本里找得到；
  - 参考答案里的数字 → 必须能在画像 JSON 里找到，否则降级为 insufficient。

两侧都走 `norm_text`，所以加粗、代码块、空白差异不会造成误判。
"""

import re

from agents.utils.resume import norm_text

# 数字：两位以上（年份、指标），或带单位的单个数字（5%、3 人、2 天、80ms）。
_NUMBER_RE = re.compile(
    r"(?<![\d.])("
    r"\d{2,}(?:\.\d+)?(?:%|万|亿|倍|人|天|小时|分钟|秒|ms|qps|QPS)?"
    r"|\d+(?:\.\d+)?(?:%|万|亿|倍|人|天|小时|分钟|秒|ms|qps|QPS)"
    r")"
)
_DIGITS_RE = re.compile(r"\d+(?:\.\d+)?")


def quote_in_text(quote: str, text: str) -> bool:
    """引用是否能在文本里找到原文（忽略空白与 Markdown 装饰）。"""
    q = norm_text(quote)
    if not q:
        return False
    return q in norm_text(text)


def number_tokens(text: str) -> list[str]:
    """抽取文本里的数字片段，保留单位用于提示。"""
    return [match.group(1) for match in _NUMBER_RE.finditer(text or "")]


def _number_present(token: str, profile_text: str) -> bool:
    digits = _DIGITS_RE.search(token)
    if digits is None:
        return True
    value = re.escape(digits.group(0))
    return re.search(rf"(?<!\d){value}(?!\d)", profile_text) is not None


def unsupported_numbers(answer: str, profile_text: str, *, extra: str = "") -> list[str]:
    """参考答案里在画像中找不到出处的数字（按出现顺序去重）。"""
    haystack = norm_text(f"{profile_text}\n{extra}")
    missing: list[str] = []
    for token in number_tokens(answer):
        if not _number_present(token, haystack):
            if token not in missing:
                missing.append(token)
    return missing


def words(text: str, limit: int) -> str:
    """按字符截断（只用于提示词预算，不用于页面展示）。"""
    value = (text or "").strip()
    return value if len(value) <= limit else value[:limit] + "…"
