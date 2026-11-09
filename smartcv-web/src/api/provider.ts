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

export function missingProviderFields(p: ProviderSettings): string[] {
  const missing: string[] = []
  if (!p.provider) missing.push('供应商')
  if (!p.baseUrl) missing.push('接口地址')
  if (!p.apiKey) missing.push('API Key')
  if (!p.model) missing.push('模型名称')
  return missing
}
