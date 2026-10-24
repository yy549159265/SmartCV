from langchain_openai import ChatOpenAI

from schemas.provider import ProviderConfig


def choose_llm(
    provider: ProviderConfig,
    *,
    temperature: float | None = None,
    timeout: float | None = None,
):
    """按供应商配置构造 ChatOpenAI。

    temperature / timeout 是可选覆盖：解析流程里的章节分类要求确定性
    （temperature=0），普通对话沿用供应商默认值。
    """
    model = provider.model
    overrides: dict = {}
    if temperature is not None:
        overrides["temperature"] = temperature
    if timeout is not None:
        overrides["timeout"] = timeout

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
            **overrides,
        )

    return ChatOpenAI(
        model=model,
        base_url=provider.baseUrl,
        api_key=provider.apiKey,
        **overrides,
    )
