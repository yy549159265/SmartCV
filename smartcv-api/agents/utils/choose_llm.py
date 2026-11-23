from langchain_openai import ChatOpenAI

from agents.utils.usage import current_meter
from schemas.provider import ProviderConfig


def choose_llm(
    provider: ProviderConfig,
    *,
    temperature: float | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
):
    """按供应商配置构造 ChatOpenAI。

    temperature / timeout / max_retries 是可选覆盖：解析流程里的章节分类要求
    确定性（temperature=0）；市场洞察这类长流水线要设超时，避免供应商卡住
    时整轮调研无限期停在「生成计划」。
    """
    model = provider.model
    overrides: dict = {}
    if temperature is not None:
        overrides["temperature"] = temperature
    if timeout is not None:
        overrides["timeout"] = timeout
    if max_retries is not None:
        overrides["max_retries"] = max_retries

    # 自定义 base_url 时 ChatOpenAI 默认关闭流式 usage；显式打开后，
    # 流式调用也能在回调里拿到 token 数。
    overrides["stream_usage"] = True
    meter = current_meter()
    if meter is not None:
        overrides["callbacks"] = [meter]

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
