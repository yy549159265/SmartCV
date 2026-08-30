/**
 * "导入文档（PDF / Word）"接口
 *
 * 后端：POST /api/resume/parse（见 smartcv-api/main.py）
 *   入参：multipart 表单
 *         file                    —— 上传的简历文档（PDF / .docx）
 *         parser                  —— 解析引擎：docling（本地，默认）/ mineru（云 API）
 *         mineruToken             —— 选 mineru 时的 API Token
 *         provider/baseUrl/apiKey/model —— 供应商配置（后端据此调 LLM 解析）
 *   出参：统一响应 { code, message, data }，data 为与 importResume 兼容的简历数据
 *        （顶层为章节数组 Section[]）
 *
 * 过程反馈：POST 是同步的，解析期间前端通过 onProgress 回调拿到进度。
 * 方法：发 POST（不等完成）的同时每 ~1s 轮询 GET /api/resume/parse/status，
 * 每次轮询回调 onProgress({ state, error, steps })；POST 返回或失败即停止轮询。
 * 供应商配置未填齐：前端先拦截提示（不发请求）；后端 422 兜底，错误取 message。
 */
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

/** 轮询解析状态；POST 返回或失败时调用返回的 stop() 停止。 */
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
      // 轮询失败/被中止就忽略，POST 的返回才是准的
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
  // 发请求前先查配置齐不齐，省一次无效请求，且提示是中文
  const p = getProviderSettings()
  const missing = missingProviderFields(p)
  if (missing.length) {
    throw new Error(`请先在「供应商设置」填齐：${missing.join('、')}`)
  }

  // 文件大小限制 5MB（与后端一致），前端先拦，省得上传大文件
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

  // 先确保会话 id 已生成：GET /status 通过同一个 X-Agent-Session-Id 头定位到 store
  getAgentSessionId()

  // 发 POST（不等完成），同时每 ~1s 轮询状态；POST 结束（成功/失败）即停轮询
  const poll = pollStatus(onProgress, signal)
  try {
    const res = await apiFetch('/api/resume/parse', { method: 'POST', body: form, signal })
    return unwrap<unknown>(res, '解析失败')
  } finally {
    poll.stop()
  }
}
