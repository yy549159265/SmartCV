/**
 * 模拟面试语音识别设置：识别方式与 DeepSeek 接口参数。
 *
 * 只保存在当前浏览器；输入框的麦克风会按这里选中的方式工作。
 */

import { useStorage } from '@vueuse/core'

export type AsrMode = 'sherpa' | 'deepseek'

export interface AsrSettings {
  /** 识别方式，默认保持原有的 sherpa-onnx 实时识别。 */
  mode: AsrMode
  /** DeepSeek 非实时识别参数；只有 mode === 'deepseek' 时使用。 */
  deepseek: {
    baseUrl: string
    apiKey: string
  }
}

/** DeepSeek 单次录音上限，接口本身支持 120 秒，这里按产品要求收紧到 60 秒。 */
export const DEEPSEEK_MAX_SECONDS = 60
export const DEFAULT_DEEPSEEK_BASE_URL = 'https://api.deepseek.com'

export interface AsrModeOption {
  value: AsrMode
  label: string
  hint: string
}

export const ASR_MODE_OPTIONS: AsrModeOption[] = [
  {
    value: 'sherpa',
    label: 'sherpa-onnx',
    hint: '边说边识别，文字实时写进输入框；音频不落盘，识别结果不保存录音',
  },
  {
    value: 'deepseek',
    label: 'DeepSeek 非实时',
    hint: `点击麦克风开始录音，结束后上传音频再识别；单次最长 ${DEEPSEEK_MAX_SECONDS} 秒`,
  },
]

export const asrSettings = useStorage<AsrSettings>(
  'smartcv-interview-asr',
  {
    mode: 'sherpa',
    deepseek: { baseUrl: DEFAULT_DEEPSEEK_BASE_URL, apiKey: '' },
  },
  undefined,
  { mergeDefaults: true },
)

/**
 * DeepSeek ASR 接口：POST {baseUrl}/v1/tools/asr。
 * Base URL 允许填到 /v1，此时不再重复拼一层。
 */
export function deepSeekAsrEndpoint(baseUrl: string): string {
  const base = (baseUrl.trim() || DEFAULT_DEEPSEEK_BASE_URL).replace(/\/+$/, '')
  return /\/v1$/.test(base) ? `${base}/tools/asr` : `${base}/v1/tools/asr`
}

/** 录音计时展示：秒 → mm:ss。 */
export function asrClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}
