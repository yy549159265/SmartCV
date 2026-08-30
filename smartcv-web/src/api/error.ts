/**
 * 后端统一响应格式：{ code, message, data }（见 smartcv-api/schemas/response.py）。
 *   code    0 = 成功，非 0 = 失败（一般就是 HTTP 状态码，如 422/501）
 *   message 成功时 "ok"，失败时给人看的中文说明
 *   data    成功时为业务数据，失败时为 null
 * HTTP 状态码仍保留意义：2xx 成功、4xx/5xx 失败。
 */

export async function apiErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { message?: string }
    if (typeof body.message === 'string' && body.message) return body.message
  } catch {
    // body 不是合法 JSON，忽略，用兜底消息
  }
  return `${fallback}：${res.status}`
}

/** 统一解包：非 2xx 或 code != 0 直接抛错，否则返回 data。 */
export async function unwrap<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) throw new Error(await apiErrorMessage(res, fallback))
  const body = (await res.json()) as { code?: number; message?: string; data?: T }
  if (body.code !== 0) throw new Error(body.message || fallback)
  return body.data as T
}
