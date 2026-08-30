/**
 * 读取"供应商设置"页保存的配置（localStorage，key 与 ProviderSettingsPage 一致）。
 * 所有 AI 请求（上传解析 / 润色 / 对话）都带上它，后端据此调 LLM。
 */
export interface ProviderSettings {
  provider?: string
  baseUrl?: string
  apiKey?: string
  model?: string
}

export function getProviderSettings(): ProviderSettings {
  try {
    return JSON.parse(localStorage.getItem('smartcv-provider-settings') ?? '{}') as ProviderSettings
  } catch {
    return {}
  }
}

/** 返回没填的字段名列表（空数组 = 配置完整） */
export function missingProviderFields(p: ProviderSettings): string[] {
  const missing: string[] = []
  if (!p.provider) missing.push('供应商')
  if (!p.baseUrl) missing.push('接口地址')
  if (!p.apiKey) missing.push('API Key')
  if (!p.model) missing.push('模型名称')
  return missing
}
