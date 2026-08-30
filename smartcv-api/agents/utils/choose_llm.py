from langchain_openai import ChatOpenAI

from schemas.provider import ProviderConfig


def choose_llm(provider: ProviderConfig):

    return ChatOpenAI(
        model=provider.model,
        base_url=provider.baseUrl,
        api_key=provider.apiKey,
    )
