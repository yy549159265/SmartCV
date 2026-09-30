import json
import logging
import re
from pathlib import Path

from langchain.agents import create_agent

from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_polish.md").read_text(encoding="utf-8")

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
    session_id: str | None = None,
):
    llm = choose_llm(provider)

    # 这里不用 response_format=PolishedItems：那会让 langchain 把结构化输出伪装成
    # 一次 function call 发给模型（tools=[PolishedItems]、tool_choice=required）。
    # 模型返回的 arguments 只要是坏 JSON（中文文本里没转义的引号、参数被截断等）
    # 或工具名对不上，langchain 就会保留 assistant 的 tool_calls 却不补 tool 应答，
    # 下一轮请求被 DeepSeek 以 "assistant message with 'tool_calls' must be followed
    # by tool messages" 400 拒绝。提示词本来就要求直接输出合法 JSON，改成自己解析更稳。
    agent = create_agent(
        model=llm,
        tools=[],
    )

    # description 是用户填的润色思路（前端可为空）：填了就一并交给模型当风格参考，
    # 没填就只传要点，和加这个字段之前完全一致。
    hint = description.strip()
    items_block = "\n".join(texts)
    if hint:
        human_content = f"我的润色思路：{hint}\n\n请按上面的思路润色以下简历要点：\n{items_block}"
    else:
        human_content = f"请润色以下简历要点：\n{items_block}"

    result = agent.invoke(
        {
            "messages": [
                {"type": "system", "content": _SYSTEM_PROMPT},
                {"type": "human", "content": human_content},
            ]
        },
        # session_id 通过 configurable 传给 agent，同一会话的多次调用才能串成一条会话
        config={"recursion_limit": 20, "configurable": {"session_id": session_id}},
    )

    # 不再有 structured_response（没走 response_format），直接解析模型回复的 JSON 文本
    content = result["messages"][-1].content
    items = _parse_items(content if isinstance(content, str) else "")
    logging.info("polish-agent 输出 %d 条润色结果", len(items))
    return items
