"""全文纠错 agent：一次结构化调用 → 代码校验 → 按坐标就地写回。

和 optimize 的区别：
- 不需要诊断/审查/总结多 agent 协作，纠错规则是确定的；
- 模型只返回「坐标 + 完整改后文字」，不返回整份简历；
- 代码负责核对坐标、原文片段、是否新增数字等，校验不过的进 skipped，
  绝不写入；通过的就地替换文字，JSON 结构 / 样式 / 布局完全不动。

前端复用优化流程的「修改前后对比」弹窗：把改前快照和这里返回的 resume
交给 pendingDiff，用户确认后一次性写回，撤销也仍是一步 Ctrl+Z。
"""

import copy
import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from agents.resume.grammar.schemas import GrammarResult
from agents.utils.choose_llm import choose_llm
from agents.utils.resume import (
    describe_location,
    locate_unit,
    norm_text,
    resume_to_marked_text,
    write_text_unit,
)
from schemas.provider import ProviderConfig

logger = logging.getLogger("smartcv")

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_grammar.md").read_text(encoding="utf-8")

# 系统提示词要求不要代码围栏，个别模型仍会加，解析前先剥掉
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?")
_MARKDOWN_MARKS = re.compile(r"[*`~]")
# 纯日期 / 时间范围行（listText 里的时间不算 range 单元，需要按文本兜底识别）
_DATE_RANGE_CHARS = re.compile(r"[0-9./年月日\-–—~至至今现在()（）]+")
_DATE_SEPARATOR = re.compile(r"[-–—~至]")
# 只去掉空白，用于识别日期 / 时间范围（核对 quote 统一走 utils/resume.py 的 norm_text）
_WHITESPACE = re.compile(r"\s+")


def _is_int(value: object) -> bool:
    """bool 是 int 的子类，坐标里的 true/false 不能当成 0/1。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _clean_corrected(value: str) -> str:
    return str(value or "").strip()


def _looks_like_date_range(text: str) -> bool:
    """整段就是一个日期 / 时间范围（含 listText 里的时间行）。"""
    compact = _WHITESPACE.sub("", text or "")
    if not compact or len(compact) > 40:
        return False
    if not re.search(r"\d", compact) or not _DATE_SEPARATOR.search(compact):
        return False
    return bool(_DATE_RANGE_CHARS.fullmatch(compact))


def _new_numbers(old: str, corrected: str) -> list[str]:
    """纠错不允许新增数字：日期、指标、版本号、电话都可能是事实。"""
    old_numbers = set(_NUMBER.findall(old or ""))
    return [n for n in _NUMBER.findall(corrected or "") if n not in old_numbers]


def _guard_change(old: str, corrected: str, *, title: bool = False) -> str:
    """检查一条纠错是否仍属于「纠错」范围；返回空串 = 通过。"""
    old = old or ""
    corrected = corrected or ""
    if not corrected.strip():
        return "修正结果为空"
    if corrected.strip() == old.strip():
        return "修正后与原文相同"
    if "\n" in corrected or "\r" in corrected:
        return "纠错结果不能包含换行"

    # 原文没有 Markdown 装饰时，不允许模型加回来；这些符号会原样显示在简历里
    if _MARKDOWN_MARKS.search(corrected) and not _MARKDOWN_MARKS.search(old):
        return "纠错结果不能包含 Markdown 标记"

    added_numbers = _new_numbers(old, corrected)
    if added_numbers:
        return f"纠错不能新增数字：{'、'.join(added_numbers[:3])}"
    if "http" in corrected.lower() and "http" not in old.lower():
        return "纠错不能新增链接"
    if "@" in corrected and "@" not in old:
        return "纠错不能新增邮箱"

    compact_old = norm_text(old)
    compact_new = norm_text(corrected)
    if compact_old == compact_new:
        # 只改了空白（例如中英文之间补空格），这是允许的
        return ""
    if not compact_new:
        return "修正结果为空"

    # 长度和相似度兜底：防止模型借纠错之名整段重写 / 删掉后半段
    if len(compact_new) > len(compact_old) * 2 + 20:
        return "改动幅度超出纠错范围"
    if title:
        if abs(len(compact_new) - len(compact_old)) > 2:
            return "标题纠错不允许增删信息"
        if len(compact_old) >= 4 and SequenceMatcher(None, compact_old, compact_new).ratio() < 0.6:
            return "标题改动幅度超出纠错范围"
    else:
        if len(compact_old) >= 16 and len(compact_new) < len(compact_old) * 0.5:
            return "改动幅度超出纠错范围"
        if len(compact_old) >= 10 and SequenceMatcher(None, compact_old, compact_new).ratio() < 0.45:
            return "改动幅度超出纠错范围"
    return ""


def _location(resume: list[dict], s, r, c, i) -> str:
    """给 skipped / changes 生成人能看懂的位置说明。"""
    if not _is_int(s) or not (0 <= s < len(resume)):
        return "未知位置"
    if all(_is_int(v) for v in (r, c, i)):
        return describe_location(
            resume, {"kind": "text", "s": s, "r": r, "c": c, "i": i}
        )
    return (resume[s].get("title") or "").strip() or f"第 {s + 1} 章"


def _skip(skipped: list[dict], *, level: str, location: str, before: str, after: str, reason: str) -> None:
    skipped.append(
        {
            "level": level,
            "location": location,
            "before": before,
            "after": after,
            "reason": reason,
        }
    )


def _apply_fix(
    resume: list[dict],
    fix,
    changes: list[dict],
    skipped: list[dict],
    seen: set[tuple[int, int, int, int]],
) -> None:
    coords = (fix.s, fix.r, fix.c, fix.i)
    if not all(_is_int(v) for v in coords):
        _skip(
            skipped,
            level="text",
            location=_location(resume, fix.s, None, None, None),
            before="",
            after=fix.corrected,
            reason="坐标不完整",
        )
        return

    s, r, c, i = coords
    key = (s, r, c, i)
    located = locate_unit(resume, s, r, c, i)
    if located is None:
        _skip(
            skipped,
            level="text",
            location=_location(resume, s, r, c, i),
            before="",
            after=fix.corrected,
            reason="坐标不存在",
        )
        return
    if key in seen:
        _skip(
            skipped,
            level="text",
            location=_location(resume, s, r, c, i),
            before=located[3],
            after=fix.corrected,
            reason="同一位置重复纠错，只应用第一条",
        )
        return

    content, unit_type, unit_index, old = located
    if unit_type == "range" or _looks_like_date_range(old):
        _skip(
            skipped,
            level="text",
            location=_location(resume, s, r, c, i),
            before=old,
            after=fix.corrected,
            reason="日期 / 时间范围不参与纠错",
        )
        return

    quote = (fix.quote or "").strip()
    if not quote:
        _skip(
            skipped,
            level="text",
            location=_location(resume, s, r, c, i),
            before=old,
            after=fix.corrected,
            reason="缺少原文片段，无法核对",
        )
        return
    if not norm_text(old).startswith(norm_text(quote)):
        _skip(
            skipped,
            level="text",
            location=_location(resume, s, r, c, i),
            before=old,
            after=fix.corrected,
            reason="原文片段对不上",
        )
        return

    corrected = _clean_corrected(fix.corrected)
    reason = _guard_change(old, corrected)
    if reason:
        _skip(
            skipped,
            level="text",
            location=_location(resume, s, r, c, i),
            before=old,
            after=corrected,
            reason=reason,
        )
        return

    write_text_unit(content, unit_type, unit_index, corrected)
    seen.add(key)
    changes.append(
        {
            "level": "text",
            "location": _location(resume, s, r, c, i),
            "before": old,
            "after": corrected,
            "reason": (fix.reason or "").strip() or "语法 / 拼写纠错",
        }
    )


def _apply_title_fix(
    resume: list[dict],
    fix,
    changes: list[dict],
    skipped: list[dict],
    seen: set[int],
) -> None:
    s = fix.s
    if not _is_int(s) or not (0 <= s < len(resume)):
        _skip(
            skipped,
            level="title",
            location="未知位置",
            before="",
            after=fix.corrected,
            reason="章节序号不存在",
        )
        return
    if s in seen:
        _skip(
            skipped,
            level="title",
            location=(resume[s].get("title") or "").strip() or f"第 {s + 1} 章标题",
            before=(resume[s].get("title") or "").strip(),
            after=fix.corrected,
            reason="同一标题重复纠错，只应用第一条",
        )
        return

    section = resume[s]
    old = (section.get("title") or "").strip()
    location = old or f"第 {s + 1} 章标题"
    if not old:
        _skip(
            skipped,
            level="title",
            location=location,
            before="",
            after=fix.corrected,
            reason="原标题为空，不自动新增标题",
        )
        return

    original = (fix.original or "").strip()
    if not original or not norm_text(old).startswith(norm_text(original)):
        _skip(
            skipped,
            level="title",
            location=location,
            before=old,
            after=fix.corrected,
            reason="原标题对不上",
        )
        return

    corrected = _clean_corrected(fix.corrected)
    reason = _guard_change(old, corrected, title=True)
    if reason:
        _skip(
            skipped,
            level="title",
            location=location,
            before=old,
            after=corrected,
            reason=reason,
        )
        return

    section["title"] = corrected
    seen.add(s)
    changes.append(
        {
            "level": "title",
            "location": location,
            "before": old,
            "after": corrected,
            "reason": (fix.reason or "").strip() or "标题纠错",
        }
    )


def apply_grammar_result(resume: list[dict], result: GrammarResult) -> dict:
    """把结构化纠错应用到简历副本，返回 {resume, changes, skipped, stats}。

    单独抽出来便于不经过 LLM 直接验证坐标与校验逻辑。
    """
    out = copy.deepcopy(resume)
    changes: list[dict] = []
    skipped: list[dict] = []
    seen_units: set[tuple[int, int, int, int]] = set()
    seen_titles: set[int] = set()

    for fix in result.fixes:
        _apply_fix(out, fix, changes, skipped, seen_units)
    for fix in result.title_fixes:
        _apply_title_fix(out, fix, changes, skipped, seen_titles)

    markdown = resume_to_marked_text(resume, title_with_coord=True)
    checked_units = sum(1 for line in markdown.splitlines() if line.startswith("[s:"))
    title_fixed = sum(1 for change in changes if change["level"] == "title")
    return {
        "resume": out,
        "changes": changes,
        "skipped": skipped,
        "stats": {
            "checkedUnits": checked_units,
            "fixed": len(changes),
            "skipped": len(skipped),
            "titleFixed": title_fixed,
        },
    }


def _parse_result(raw: object) -> GrammarResult:
    """把 with_structured_output 的结果统一成 GrammarResult；解析失败返回空结果。"""
    if isinstance(raw, GrammarResult):
        return raw
    if isinstance(raw, dict):
        try:
            return GrammarResult.model_validate(raw)
        except Exception:
            return GrammarResult()

    content = getattr(raw, "content", "")
    text = content.strip() if isinstance(content, str) else ""
    if not text:
        return GrammarResult()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return GrammarResult()
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return GrammarResult()
    try:
        return GrammarResult.model_validate(payload)
    except Exception:
        return GrammarResult()


def run_grammar_agent(
    provider: ProviderConfig,
    resume: list[dict],
    session_id: str | None = None,
) -> dict:
    """跑全文纠错：一次结构化调用 + 代码校验，返回纠错后的简历与改动清单。"""
    if not resume:
        return apply_grammar_result(resume, GrammarResult())

    markdown = resume_to_marked_text(resume, title_with_coord=True)
    llm = choose_llm(provider)
    structured_llm = llm.with_structured_output(
        GrammarResult,
        method="json_mode",
        include_raw=True,
    )
    raw_result = structured_llm.invoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"<简历>\n{markdown}\n</简历>"),
        ]
    )

    parsed = _parse_result(raw_result.get("parsed"))
    if not parsed.fixes and not parsed.title_fixes:
        raw = raw_result.get("raw")
        parsed = _parse_result(raw)
        if raw_result.get("parsing_error"):
            logger.warning("grammar 结构化解析失败，尝试文本解析：%s", raw_result.get("parsing_error"))

    result = apply_grammar_result(resume, parsed)
    logger.info(
        "grammar session=%s 修正 %d 处（标题 %d），跳过 %d 处",
        session_id,
        result["stats"]["fixed"],
        result["stats"]["titleFixed"],
        result["stats"]["skipped"],
    )
    return result
