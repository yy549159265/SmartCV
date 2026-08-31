from langchain_openai import ChatOpenAI

from schemas.provider import ProviderConfig


def choose_llm(provider: ProviderConfig):
    model = provider.model

    # DeepSeek 推理模型默认会开思考模式，拖慢工具调用；这里显式关闭思考，并固定 tool_choice
    if "deepseek" in (model or "").lower():
        return ChatOpenAI(
            model=model,
            base_url=provider.baseUrl,
            api_key=provider.apiKey,
            model_kwargs={
                "tool_choice": "auto",
            },
            extra_body={"thinking": {"type": "disabled"}},
        )

    return ChatOpenAI(
        model=model,
        base_url=provider.baseUrl,
        api_key=provider.apiKey,
    )
