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

# 每种模式各对应一份系统提示词：
#   strict  （严谨）——规则锁死：只重构表达，数字照用原文、不得凭空造数，克制、篇幅短
#   free    （自由）——像直接问网页版 AI：自主判断怎么写最好，充分重写，可补充数据，按用户思路走
#   enhance （提示词增强）——把用户口语化的修改需求改写成可执行的提示词，可参考 JD
# 前两者差别在"改写自由度"；enhance 是另一种任务，输出仍是 {"items": [...]} 以复用同一接口。
_MODE_PROMPTS = {
    "strict": (_PROMPT_DIR / "system_prompt_polish_strict.md").read_text(encoding="utf-8"),
    "free": (_PROMPT_DIR / "system_prompt_polish_free.md").read_text(encoding="utf-8"),
    "enhance": (_PROMPT_DIR / "system_prompt_polish_enhance.md").read_text(encoding="utf-8"),
}
_DEFAULT_MODE = "strict"

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

    system_prompt = _MODE_PROMPTS.get(mode) or _MODE_PROMPTS[_DEFAULT_MODE]

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
    # 如果解析对象失败，退回到手动解析
    if isinstance(parsed, PolishedItems):
        items = [str(i) for i in parsed.items]
    else:
        logging.warning("polish[%s] 结构化解析失败，回退为文本解析：%s", mode, result.get("parsing_error"))
        raw = result.get("raw")
        content = getattr(raw, "content", "")
        items = _parse_items(content if isinstance(content, str) else "")

    logging.info("polish[%s] session=%s 输出 %d 条润色结果", mode, session_id, len(items))
    return items
