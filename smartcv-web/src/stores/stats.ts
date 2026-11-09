import { defineStore } from 'pinia'
import { getStats, incrementStats } from '@/api/stats'

export const useStatsStore = defineStore('stats', {
  state: () => ({
    pdf: 0,
    json: 0,
    loaded: false,
  }),

  actions: {
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
