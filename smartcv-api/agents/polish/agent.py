import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig


class PolishedItems(BaseModel):
    """润色结果的结构，与提示词要求的 {"items": [...]} 一致。"""

    items: list[str]

_PROMPT_DIR = Path(__file__).resolve().parent

# 基础提示词只有一份（system_prompt_polish.md，只写"执行框架"：
# 输入结构、行为准则、输出格式、示例），模式规则在代码里追加 ——
# 与 optimize 的 diagnose/optimize agent 同一套做法。
#
# 润色方向、润色方式、是否补充量化数据**完全由前端传入**（<要求> 区块），
# 后端不写死任何方向。模式只决定"执行自由度"：
#   strict  （严谨）——保留原句式、只做必要重构，事实与数字只能来自原文
#   free    （自由）——可大幅重写、扩写、调详略；但不得自行补充量化数据，
#                      除非 <要求> 明确要求（前端勾选「补充量化数据」才会出现）
#   enhance （提示词增强）——独立任务（把口语化需求改写成可执行提示词），
#            沿用独立 md，输出结构相同以复用同一接口。
_SYSTEM_PROMPT = (_PROMPT_DIR / "system_prompt_polish.md").read_text(encoding="utf-8")
_ENHANCE_PROMPT = (_PROMPT_DIR / "system_prompt_polish_enhance.md").read_text(encoding="utf-8")

_MODE_RULES = {
    "strict": (
        "\n\n# 本次润色模式：严谨\n"
        "保留原句式，只做必要重构；事实性数据（数字、规模、奖项等）只能来自原文，"
        "不得补充或编造任何量化数据；输出长度与原文接近，不做大幅扩写。"
    ),
    "free": (
        "\n\n# 本次润色模式：自由\n"
        "可以大幅重组句式与结构、充分扩写、调整详略、补充行业术语，"
        "结合上下文合理推断工作方式、协作角色与产出形态。"
        "但除非 <要求> 明确要求，否则不得自行补充任何量化数据"
        "（包括具体数值、百分比和 XX 占位）。"
    ),
}
_DEFAULT_MODE = "strict"


def _system_prompt(mode: str) -> str:
    """基础提示词 + 模式规则；enhance 是独立任务，用单独一份提示词。"""
    if mode == "enhance":
        return _ENHANCE_PROMPT
    return _SYSTEM_PROMPT + _MODE_RULES.get(mode, _MODE_RULES[_DEFAULT_MODE])

# 系统提示词明确要求不要代码围栏，但个别模型仍会加上，解析前先剥掉
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _to_items(parsed: object) -> list[str]:
    """把解析出来的 JSON 统一成润色后的字符串数组。

    JSON 根是对象 {"items": [...]}，这里剥掉包装；兼容 dict / 其它情况（返回空）。
    """
    if isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            return [str(i) for i in items]
    return []


def _parse_items(content: str) -> list[str]:
    """把模型回复的文本解析成润色后的字符串数组。

    提示词要求直接输出合法 JSON，但模型有时会加代码围栏、或前后带句话，
    这里逐级退让地抠出 {"items": [...]}；实在抠不出来就返回空
    （前端拿到空值会保留原文，比抛错好）。
    """
    text = (content or "").strip()
    if not text:
        return []
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return _to_items(json.loads(text))
    except json.JSONDecodeError:
        # 前后有解释性文字：退化成"取第一个 { 到最后一个 }"
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            return _to_items(json.loads(text[start : end + 1]))
        except json.JSONDecodeError:
            return []


def run_polish_agent(
    provider: ProviderConfig,
    texts: list[str],
    description: str = "",
    mode: str = _DEFAULT_MODE,
    session_id: str | None = None,
    context: str = "",
):
    llm = choose_llm(provider)

    system_prompt = _system_prompt(mode)

    structured_llm = llm.with_structured_output(
        PolishedItems,
        method="json_mode",
        include_raw=True,  # 解析失败时保留原文 {"raw": ..., "parsed": ..., "parsing_error": ...}
    )

    # 三类输入分工明确：
    #   context     参考材料（JD / 简历 / 对话历史…），只读，不参与改写
    #   description 要求（怎么改），可为空；两种模式下的地位见各自提示词
    #   texts       待处理内容，逐行改写，输出条数与之对应
    # 用标签包裹，避免模型把参考材料也当成本次要改写的内容，也降低材料里的
    # 文字被误当成指令的风险。老调用方不传 context/description 时，拼装结果
    # 和以前等价（只是措辞更中性）。
    blocks: list[str] = []
    if context.strip():
        blocks.append(f"<参考材料>\n{context.strip()}\n</参考材料>")
    if description.strip():
        blocks.append(f"<要求>\n{description.strip()}\n</要求>")
    blocks.append("<待处理内容>\n" + "\n".join(texts) + "\n</待处理内容>")
    human_content = "\n\n".join(blocks)

    result = structured_llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ]
    )

    parsed = result.get("parsed")
    if isinstance(parsed, PolishedItems):
        items = [str(i) for i in parsed.items]
    else:
        logging.warning("polish[%s] 结构化解析失败，回退为文本解析：%s", mode, result.get("parsing_error"))
        raw = result.get("raw")
        content = getattr(raw, "content", "")
        items = _parse_items(content if isinstance(content, str) else "")

    logging.info("polish[%s] session=%s 输出 %d 条润色结果", mode, session_id, len(items))
    return items
