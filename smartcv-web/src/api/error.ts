export async function apiErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { message?: string }
    if (typeof body.message === 'string' && body.message) return body.message
  } catch {
  }
  return `${fallback}：${res.status}`
}

export async function unwrap<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) throw new Error(await apiErrorMessage(res, fallback))
  const body = (await res.json()) as { code?: number; message?: string; data?: T }
  if (body.code !== 0) throw new Error(body.message || fallback)
  return body.data as T
}
