import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agents.utils.choose_llm import choose_llm
from agents.utils.resume import resume_to_plain_text
from schemas.provider import ProviderConfig


class PolishedItems(BaseModel):
    """润色结果的结构，与提示词要求的 {"items": [...]} 一致。"""

    items: list[str]

_PROMPT_DIR = Path(__file__).resolve().parent

# 提示词是「一份模板 + 若干模式片段」：
#   system_prompt_base.md          模板，固定 6 段：# 角色 / # 输入格式 / # 可以做 /
#                                  # 不能做 / # 输出格式 / # 示例，每段用 {role} 这类
#                                  占位符预留补充位置；`{other}` 放在全文最末尾，
#                                  用来接「不属于这 6 段」的内容。
#   polish_prompt.md               片段，按同样顺序只写这 6 段要补充的内容；
#                                  这 6 段之外的多余段落（如 # 本次润色模式）
#                                  按原顺序追加到 {other}。
#   enhance_prompt.md              同上，增强是一个独立任务。
#   analyze_prompt.md              同上，分析一份简历（职业名称 + 可借鉴的写法）。
# 运行时按模式取片段 → 逐段填进模板。加新模式 = 加一个片段 md，不用改代码。
#
# 润色方向、润色方式、是否补充量化数据**完全由前端传入**（<要求> 区块），
# 后端不写死方向。strict / free 只决定「执行自由度」，写在润色片段的
# 末尾段落里，用 {mode_rules} 二次替换：
#   strict （严谨）——保留原句式、只做必要重构，事实与数字只能来自原文
#   free   （自由）——可大幅重写、扩写、调详略；但不得自行补充量化数据，
#                     除非 <要求> 明确要求（前端勾选「补充量化数据」才会出现）
_BASE_PROMPT = (_PROMPT_DIR / "system_prompt_base.md").read_text(encoding="utf-8")
_MODE_PROMPTS = {
    "polish": (_PROMPT_DIR / "polish_prompt.md").read_text(encoding="utf-8"),
    "enhance": (_PROMPT_DIR / "enhance_prompt.md").read_text(encoding="utf-8"),
    "analyze": (_PROMPT_DIR / "analyze_prompt.md").read_text(encoding="utf-8"),
}

_MODE_TEMPLATE = {
    "strict": "polish",
    "free": "polish",
    "enhance": "enhance",
    "analyze": "analyze",
}

_SLOT_HEADINGS = {
    "{role}": "角色",
    "{input_format}": "输入格式",
    "{can_do}": "可以做",
    "{cannot_do}": "不能做",
    "{output_format}": "输出格式",
    "{examples}": "示例",
}

_MODE_RULES = {
    "strict": (
        "保留原句式，只做必要重构；事实性数据（数字、规模、奖项等）只能来自原文，"
        "不得补充或编造任何量化数据；输出长度与原文接近，不做大幅扩写。"
    ),
    "free": (
        "这是「改写」而非「轻微润色」：禁止只做同义替换、或在原文上小修小补。\n"
        "1. <要求> 是第一优先级：其中给出的方向（更专业 / 更量化 / 更有故事性 / 面向某岗位等）"
        "必须落实到每条输出，必要时调整侧重点、重新组织内容、补充细节。\n"
        "2. 主动远离原文：大幅重组句子、更换句式与措辞、扩写或精简、补充行业术语，"
        "结合 <参考材料> 合理推断工作方式、协作角色与产出形态；"
        "输出不必保留原文的结构与措辞，只需保留「这条在讲什么事」这一事实内核。\n"
        "3. 仍须逐条对应、不增删条目、保留 Markdown 格式；除非 <要求> 明确要求，"
        "否则不得自行补充量化数据（具体数值、百分比、XX 占位）。"
    ),
}
_DEFAULT_MODE = "strict"


def _sections(markdown: str) -> list[tuple[str | None, str]]:
    """把片段 md 按一级标题切成 [(标题, 正文)]，保持原顺序。

    只认行首的 `# `（后接一个空格），所以 `## ` 之类的子标题会原样留在
    上一段的正文里。第一个标题之前的内容记作标题 None。
    """
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("# ") and not line.startswith("##"):
            if heading is not None or "\n".join(body).strip():
                sections.append((heading, "\n".join(body).strip()))
            heading = line[2:].strip()
            body = []
            continue
        body.append(line)
    if heading is not None or "\n".join(body).strip():
        sections.append((heading, "\n".join(body).strip()))
    return sections


def _system_prompt(mode: str) -> str:
    """模板 + 模式片段 + 模式规则，得到本次实际使用的系统提示词。

    片段里属于 6 个标准段的内容按标题填进对应占位符；其余段落不塞进任何
    槽位，按原始顺序（连同自己的 `# 标题`）整体放进模板末尾的 {other}。
    """
    template = _MODE_TEMPLATE.get(mode, _MODE_TEMPLATE[_DEFAULT_MODE])
    sections = _sections(_MODE_PROMPTS[template])

    known = {heading for heading in _SLOT_HEADINGS.values()}
    extras = [
        f"# {heading}\n\n{body}" if heading else body
        for heading, body in sections
        if heading not in known and body
    ]

    prompt = _BASE_PROMPT
    for placeholder, heading in _SLOT_HEADINGS.items():
        body = next((text for name, text in sections if name == heading), "")
        prompt = prompt.replace(placeholder, body)
    prompt = prompt.replace("{other}", "\n\n".join(extras))
    return prompt.replace("{mode_rules}", _MODE_RULES.get(mode, _MODE_RULES[_DEFAULT_MODE]))

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
        include_raw=True,
    )

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


def run_analyze_agent(
    provider: ProviderConfig,
    resume: list[dict],
    session_id: str | None = None,
) -> list[str]:
    """分析一份简历，返回固定 2 条：[职业名称, 可借鉴的写法]。

    简历先转成「不带坐标」的纯结构文本（示例库不需要坐标，坐标会干扰模型
    对内容的判断）；待处理内容给两个空占位，只为对齐提示词里「固定 2 条」的
    输出契约，真正的输入在 <参考材料> 里。
    """
    if not resume:
        raise ValueError("简历内容为空，无法分析")

    resume_text = resume_to_plain_text(resume)
    if not resume_text.strip():
        raise ValueError("简历里没有可分析的文字内容")

    items = run_polish_agent(
        provider,
        ["", ""],
        mode="analyze",
        session_id=session_id,
        context=resume_text,
    )
    normalized = [str(items[i]).strip() if i < len(items) else "" for i in range(2)]
    logging.info(
        "analyze session=%s 方向=%s 借鉴点条数=%d",
        session_id,
        bool(normalized[0]),
        len([line for line in normalized[1].splitlines() if line.strip()]),
    )
    return normalized
