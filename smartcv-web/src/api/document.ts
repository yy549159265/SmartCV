import { getProviderSettings, missingProviderFields } from '@/api/provider'
import { unwrap } from '@/api/error'
import { apiFetch } from '@/api/http'
import { getAgentSessionId } from '@/api/session'

export interface ParseStep {
  name: string
  status: 'pending' | 'running' | 'done' | 'failed'
}

export interface ParseProgress {
  state: 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | 'unknown'
  error: string | null
  steps: ParseStep[]
}

function pollStatus(onProgress?: (p: ParseProgress) => void, signal?: AbortSignal) {
  let stopped = false
  let timer: ReturnType<typeof setInterval> | null = null
  async function tick() {
    if (stopped) return
    try {
      const res = await apiFetch('/api/resume/parse/status', { signal })
      const data = await unwrap<ParseProgress>(res, '状态查询失败')
      onProgress?.(data)
    } catch {
    }
  }
  timer = setInterval(tick, 1000)
  tick()
  return {
    stop() {
      stopped = true
      if (timer) clearInterval(timer)
    },
  }
}

export async function parseResumeFile(
  file: File,
  opts?: { parser?: 'docling' | 'mineru'; mineruToken?: string },
  onProgress?: (p: ParseProgress) => void,
  signal?: AbortSignal,
): Promise<unknown> {
  const p = getProviderSettings()
  const missing = missingProviderFields(p)
  if (missing.length) {
    throw new Error(`请先在「高级设置」填齐：${missing.join('、')}`)
  }

  if (file.size > 5 * 1024 * 1024) {
    throw new Error('文件超过 5MB，请压缩后再上传')
  }

  const parser = opts?.parser ?? 'docling'
  if (parser === 'mineru' && !opts?.mineruToken?.trim()) {
    throw new Error('请填写 MinerU Token（官网 API 管理页创建）')
  }

  const form = new FormData()
  form.append('file', file)
  form.append('provider', p.provider ?? '')
  form.append('baseUrl', p.baseUrl ?? '')
  form.append('apiKey', p.apiKey ?? '')
  form.append('model', p.model ?? '')
  form.append('parser', parser)
  if (parser === 'mineru') {
    form.append('mineruToken', opts?.mineruToken ?? '')
  }

  getAgentSessionId()

  const poll = pollStatus(onProgress, signal)
  try {
    const res = await apiFetch('/api/resume/parse', { method: 'POST', body: form, signal })
    return unwrap<unknown>(res, '解析失败')
  } finally {
    poll.stop()
  }
}
