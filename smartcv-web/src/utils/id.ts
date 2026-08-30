/**
 * 生成全局唯一的内容 id
 * 用「时间戳 + 自增序号 + 随机串」拼出来，保证拖拽复制时不会重复。
 */

let seq = 0

export function uid(): string {
  seq += 1
  return `b-${Date.now().toString(36)}-${seq.toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}
