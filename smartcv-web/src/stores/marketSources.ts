import { defineStore } from 'pinia'
import { useDocumentsStore } from '@/stores/documents'

/**
 * 市场洞察的「信息来源」：用户补充的网址 + 方向标签 + 备注。
 *
 * 归属和简历一样放在浏览器本地：备份文件夹里的 market-sources.json 是唯一
 * 数据源，localStorage 只是未绑定文件夹 / 读取失败时的缓存。任何增删改都会
 * 先更新内存与缓存，再同步写回 JSON 文件。
 */

export type SourceDirection = 'jobs' | 'trend' | 'other'

export interface MarketSourceEntry {
  id: string
  url: string
  direction: SourceDirection
  note: string
  createdAt: number
}

export interface MarketSourcesPayload {
  version: 1
  updatedAt: number
  entries: MarketSourceEntry[]
}

export const DIRECTION_OPTIONS: { value: SourceDirection; label: string }[] = [
  { value: 'jobs', label: '招聘矩阵' },
  { value: 'trend', label: '技术趋势' },
  { value: 'other', label: '其他' },
]

const LS_KEY = 'smartcv-market-sources'
const DIRECTIONS = new Set<SourceDirection>(['jobs', 'trend', 'other'])

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function makeId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 补全协议并校验；非法地址返回空串，交给界面提示。 */
export function normalizeSourceUrl(raw: string): string {
  const input = raw.trim()
  if (!input) return ''
  const withScheme = /^https?:\/\//i.test(input) ? input : `https://${input}`
  try {
    const url = new URL(withScheme)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return ''
    return url.toString()
  } catch {
    return ''
  }
}

export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function normalizeEntries(raw: unknown): MarketSourceEntry[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object' && Array.isArray((raw as { entries?: unknown }).entries)
      ? ((raw as { entries: unknown[] }).entries)
      : []
  const result: MarketSourceEntry[] = []
  const seen = new Set<string>()
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const url = normalizeSourceUrl(text(record.url))
    if (!url || seen.has(url)) continue
    seen.add(url)
    const rawDirection = text(record.direction)
    result.push({
      id: text(record.id) || makeId(),
      url,
      direction: DIRECTIONS.has(rawDirection as SourceDirection)
        ? (rawDirection as SourceDirection)
        : 'other',
      note: text(record.note),
      createdAt: Number(record.createdAt) || Date.now(),
    })
  }
  return result
}

function payloadTime(raw: unknown): number {
  if (!raw || typeof raw !== 'object') return 0
  const value = Number((raw as { updatedAt?: unknown }).updatedAt)
  return Number.isFinite(value) ? value : 0
}

function readLocalPayload(): unknown {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writeLocalPayload(payload: MarketSourcesPayload): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(payload))
  } catch {
    /* 隐私模式 / 配额不足：缓存失败不影响内存状态 */
  }
}

// 连续增删时把写入排成队列：每次都写最新状态，又不会让两次文件写互相覆盖。
let writeQueue: Promise<void> = Promise.resolve()
let queuedWrites = 0
// 同一时刻只跑一次读取；后到的调用等同一个 Promise，而不是拿到空数据就走。
let loadTask: Promise<void> | null = null

export const useMarketSourcesStore = defineStore('marketSources', {
  state: () => ({
    entries: [] as MarketSourceEntry[],
    loaded: false,
    loading: false,
    saving: false,
    /** 最近一次写入是否落到备份库的 JSON 文件。 */
    savedToFolder: false,
  }),

  getters: {
    /** 后端请求用的扁平标签结构，字段名与 MarketRequest.extraUrls 对齐。 */
    payloadEntries: (state) =>
      state.entries.map((entry) => ({
        url: entry.url,
        direction: entry.direction,
        note: entry.note,
      })),
  },

  actions: {
    /**
     * 载入来源库。备份文件夹可读时以文件为准，但本地缓存更新（上次写入失败）
     * 时优先保留本地并回写文件，保证界面和 JSON 始终一致。
     */
    load(force = false): Promise<void> {
      if (loadTask) return loadTask
      if (this.loaded && !force) return Promise.resolve()
      this.loading = true
      loadTask = this.loadInner().finally(() => {
        this.loading = false
        this.loaded = true
        loadTask = null
      })
      return loadTask
    },

    async loadInner(): Promise<void> {
      const documents = useDocumentsStore()
      const localPayload = readLocalPayload()
      const filePayload =
        documents.isBound && documents.status === 'ready'
          ? await documents.readMarketSources()
          : null

      if (filePayload && payloadTime(filePayload) >= payloadTime(localPayload)) {
        this.entries = normalizeEntries(filePayload)
        this.savedToFolder = true
        // 用文件里的时间戳回填缓存，下次文件读不到时还能还原同一份数据。
        writeLocalPayload({
          version: 1,
          updatedAt: payloadTime(filePayload),
          entries: this.entries.map((entry) => ({ ...entry })),
        })
        return
      }

      this.entries = normalizeEntries(localPayload)
      // 文件还没有内容，或本地缓存更新：把同一份数据同时写回缓存和文件。
      if (documents.isBound && documents.status === 'ready') {
        const payload = this.buildPayload()
        writeLocalPayload(payload)
        this.savedToFolder = await documents.writeMarketSources(payload)
      } else {
        this.savedToFolder = false
      }
    },

    buildPayload(): MarketSourcesPayload {
      return {
        version: 1,
        updatedAt: Date.now(),
        entries: this.entries.map((entry) => ({ ...entry })),
      }
    },

    async writeFile(): Promise<boolean> {
      const documents = useDocumentsStore()
      // 未授权时只留在浏览器缓存，等用户回到设置页或重新授权后再补写文件，
      // 避免在用户只是想改个标签时突然弹出文件夹权限请求。
      if (!documents.isBound || documents.status !== 'ready') return false
      return documents.writeMarketSources(this.buildPayload())
    },

    /** 写缓存 + 同步 JSON 文件；文件未绑定时只保留浏览器缓存。 */
    persist(): Promise<void> {
      queuedWrites += 1
      this.saving = true
      const run = async () => {
        writeLocalPayload(this.buildPayload())
        this.savedToFolder = await this.writeFile()
      }
      const task = writeQueue.then(run, run).finally(() => {
        queuedWrites -= 1
        if (queuedWrites === 0) this.saving = false
      })
      writeQueue = task.catch(() => undefined)
      return task
    },

    async add(input: { url: string; direction: SourceDirection; note: string }): Promise<boolean> {
      const url = normalizeSourceUrl(input.url)
      if (!url) return false
      // 备注是采集时分流和筛选的依据，空备注的网址不落库。
      if (!input.note.trim()) return false
      if (this.entries.some((entry) => entry.url === url)) return false
      this.entries = [
        ...this.entries,
        {
          id: makeId(),
          url,
          direction: input.direction,
          note: input.note.trim(),
          createdAt: Date.now(),
        },
      ]
      await this.persist()
      return true
    },

    async update(
      id: string,
      input: { url: string; direction: SourceDirection; note: string },
    ): Promise<boolean> {
      const url = normalizeSourceUrl(input.url)
      if (!url) return false
      if (!input.note.trim()) return false
      if (this.entries.some((entry) => entry.id !== id && entry.url === url)) return false
      this.entries = this.entries.map((entry) =>
        entry.id === id
          ? {
              ...entry,
              url,
              direction: input.direction,
              note: input.note.trim(),
            }
          : entry,
      )
      await this.persist()
      return true
    },

    async remove(id: string): Promise<void> {
      this.entries = this.entries.filter((entry) => entry.id !== id)
      await this.persist()
    },
  },
})
