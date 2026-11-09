let seq = 0

export function uid(): string {
  seq += 1
  return `b-${Date.now().toString(36)}-${seq.toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}
