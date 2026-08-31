/**
 * 导出统计仓库（Pinia）：全局累计的 PDF / JSON 导出次数。
 *
 * 数据来自后端 /api/stats（存文件、跨容器重建保留）。主页挂载时 load() 一次，
 * 导出成功时 inc(kind) 更新；接口失败静默，不打扰导出流程。
 */
import { defineStore } from 'pinia'
import { getStats, incrementStats } from '@/api/stats'

export const useStatsStore = defineStore('stats', {
  state: () => ({
    /** 导出 PDF 次数 */
    pdf: 0,
    /** 导出 JSON 次数 */
    json: 0,
    /** 是否已从后端拉过（避免每次进主页都请求） */
    loaded: false,
  }),

  actions: {
    /** 拉取一次最新计数；失败静默（页面照常显示 0）。 */
    async load() {
      try {
        const stats = await getStats()
        this.pdf = stats.pdf
        this.json = stats.json
      } catch (err) {
        console.error('加载导出统计失败', err)
      }
      this.loaded = true
    },

    /** 某类型导出成功计数 +1；失败静默。 */
    async inc(kind: 'pdf' | 'json') {
      try {
        const stats = await incrementStats(kind)
        this.pdf = stats.pdf
        this.json = stats.json
      } catch (err) {
        console.error('更新导出统计失败', err)
      }
    },
  },
})
