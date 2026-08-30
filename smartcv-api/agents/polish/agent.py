import logging
from pathlib import Path

from langchain.agents import create_agent

from agents.polish.polish import PolishedItems
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt_polish.md").read_text(encoding="utf-8")


def _to_items(structured_response: object) -> list[str]:
    """把结构化输出统一成润色后的字符串数组。

    结构化输出的 JSON 根是对象 {"items": [...]}，这里剥掉包装；
    兼容 Pydantic 对象 / 原始 dict / 缺失三种情况。
    """
    if isinstance(structured_response, PolishedItems):
        return [str(i) for i in structured_response.items]
    if isinstance(structured_response, dict):
        items = structured_response.get("items")
        if isinstance(items, list):
            return [str(i) for i in items]
    return []


def run_polish_agent(
    provider: ProviderConfig,
    texts: list[str],
    session_id: str | None = None,
):
    llm = choose_llm(provider)

    agent = create_agent(
        model=llm,
        tools=[],
        response_format=PolishedItems,
        debug=True,
    )
    result = agent.invoke(
        {
            "messages": [
                {"type": "system", "content": _SYSTEM_PROMPT},
                {"type": "human", "content": "\n".join(texts)},
            ]
        },
        # session_id 通过 configurable 传给 agent，同一会话的多次调用才能串成一条会话
        config={"recursion_limit": 20, "configurable": {"session_id": session_id}},
    )

    items = _to_items(result.get("structured_response"))
    logging.info("polish-agent 输出 %d 条润色结果", len(items))
    return items
