"""供应商配置实体。

对应前端"供应商设置"页（src/pages/ProviderSettingsPage.vue）用 useStorage
保存的字段：provider / baseUrl / apiKey / model（camelCase，保持一致，
前端把 settings.value 原样放进请求体即可，后端零转换）。
后端拿到后用它构造 LLM client（OpenAI 兼容 / DeepSeek / GLM / 通义 / 自定义）。
"""

from fastapi import Form
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """一次请求携带的 AI 供应商配置。每个字段必填、不能为空（空字符串会校验失败）。"""

    provider: str = Field(min_length=1)  # 供应商类型：openai-compatible / deepseek / zhipu / qwen / custom
    baseUrl: str = Field(min_length=1)  # API 地址（openai 兼容接口的根地址）
    apiKey: str = Field(min_length=1)  # API Key
    model: str = Field(min_length=1)  # 模型名


def provider_config(
    provider: str = Form(...),
    baseUrl: str = Form(...),
    apiKey: str = Form(...),
    model: str = Form(...),
) -> ProviderConfig:
    """把 multipart 表单里的供应商字段收拢成 ProviderConfig 实体。

    上传接口是 multipart：文件不能进 Pydantic 模型（FastAPI 的限制，
    UploadFile 必须独立声明 File(...)），所以供应商配置用依赖函数
    收拢成实体，路由里就能拿到统一的 ProviderConfig。
    字段必填且非空：前端没配齐会返回 422。
    """
    return ProviderConfig(provider=provider, baseUrl=baseUrl, apiKey=apiKey, model=model)
