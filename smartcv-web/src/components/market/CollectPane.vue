<script setup lang="ts">
import IconGlyph from '@/components/IconGlyph.vue'
import type { CollectDistribution, CollectGroup, EvidenceLink, PanelRow } from '@/types/market'
import { linkTitle } from '@/utils/market'

defineProps<{
  groups: CollectGroup[]
  distribution: CollectDistribution | null
  view: string
  distKey: string
  distView: 'site' | 'dim'
  open: Record<string, boolean>
  highlightKey: string
  hasRows: boolean
  emptyText: string
  sourcesOf: (row: PanelRow) => EvidenceLink[]
  sourceCountOf: (row: PanelRow) => number
  numTitle: (row: PanelRow) => string
}>()

const emit = defineEmits<{
  (e: 'toggle', key: string): void
  (e: 'update:distView', value: 'site' | 'dim'): void
}>()
</script>

<template>
  <div v-if="!hasRows" class="pane-empty">{{ emptyText }}</div>
  <template v-else>
    <Transition name="mod-swap" mode="out-in">
      <div v-if="view === distKey" key="dist" class="dist-block glass-surface">
        <template v-if="distribution">
          <div class="dist-head">
            <span class="cgroup-count">
              {{ distribution.total }} 页 · {{ distribution.sites }} 个站点 · {{ distribution.dims.length }} 个维度
            </span>
            <div class="dist-switch" role="group" aria-label="来源分布视图">
              <button
                type="button"
                class="dist-switch-btn"
                :class="{ active: distView === 'site' }"
                :aria-pressed="distView === 'site'"
                title="按站点展示"
                @click="emit('update:distView', 'site')"
              >
                <IconGlyph name="globe" :size="14" />
              </button>
              <button
                type="button"
                class="dist-switch-btn"
                :class="{ active: distView === 'dim' }"
                :aria-pressed="distView === 'dim'"
                title="按维度展示"
                @click="emit('update:distView', 'dim')"
              >
                <IconGlyph name="layers" :size="14" />
              </button>
            </div>
          </div>

          <Transition name="mod-swap" mode="out-in">
            <div v-if="distView === 'site'" key="site" class="dist-rows">
              <div
                v-for="row in distribution.siteRows"
                :key="row.key"
                class="dist-row"
                :title="`${row.label}：${row.count} 页，占 ${row.pct}%`"
              >
                <span class="dist-name">{{ row.label }}</span>
                <span class="dist-track" aria-hidden="true"><i :style="{ width: `${row.pct}%` }"></i></span>
                <span class="dist-count">{{ row.count }}</span>
              </div>
              <div
                v-if="distribution.rest"
                class="dist-row"
                :title="`${distribution.rest.label}：${distribution.rest.count} 页，占 ${distribution.rest.pct}%`"
              >
                <span class="dist-name empty">{{ distribution.rest.label }}</span>
                <span class="dist-track" aria-hidden="true"><i :style="{ width: `${distribution.rest.pct}%` }"></i></span>
                <span class="dist-count">{{ distribution.rest.count }}</span>
              </div>
            </div>

            <div v-else key="dim" class="dist-dims">
              <div
                v-for="row in distribution.dims"
                :key="row.key"
                class="dist-row"
                :title="`${row.label}：${row.count} 页，占 ${row.pct}%`"
              >
                <span class="dist-name">{{ row.label }}</span>
                <span class="dist-track" aria-hidden="true"><i :style="{ width: `${row.pct}%` }"></i></span>
                <span class="dist-count">{{ row.count }}</span>
              </div>
            </div>
          </Transition>
        </template>
        <div v-else class="pane-empty">来源索引生成中，完成后这里会显示按站点和维度的来源分布。</div>
      </div>
      <div v-else :key="view" class="collect-groups">
        <section v-for="group in groups" :key="group.id" class="cgroup glass-surface">
          <div class="cgroup-head">
            <span class="cgroup-count">{{ group.rows.length }} 个站点</span>
            <span class="cgroup-pages">{{ group.got }}/{{ group.planned }} 页</span>
          </div>
          <div class="rows">
            <div
              v-for="row in group.rows"
              :key="row.key"
              class="collect-item glass-item"
              :class="{
                open: open[row.key],
                hl: highlightKey === row.key,
              }"
            >
              <button
                type="button"
                class="crow"
                :aria-expanded="open[row.key] ? 'true' : 'false'"
                @click="emit('toggle', row.key)"
              >
                <div class="crow-main">
                  <div class="crow-top">
                    <span class="crow-name">{{ row.rawSite || row.site }}</span>
                    <span class="crow-num" :title="numTitle(row)">
                      已采 {{ row.got || 0 }}/{{ row.total || 0 }} 页<template v-if="row.skipped"> · 未采 {{ row.skipped }}</template>
                    </span>
                    <IconGlyph name="chevron-down" :size="12" class="crow-chevron" />
                  </div>
                  <div class="crow-bar">
                    <i :style="{ width: `${row.total ? Math.round(((row.got || 0) / row.total) * 100) : 0}%` }"></i>
                  </div>
                </div>
              </button>
              <div v-if="open[row.key]" class="crow-detail">
                <div class="crow-detail-head">
                  <span>{{ group.label }} · {{ row.rawSite || row.site }}</span>
                  <span v-if="sourceCountOf(row)">{{ sourceCountOf(row) }} 个来源页面</span>
                  <span v-else>来源索引待回填</span>
                </div>
                <p v-if="row.skipped" class="crow-detail-skip">
                  {{ row.skipped }} 页未采到：{{ (row.skipReasons || []).join('、') || '抓取失败且没有可用摘要' }}
                </p>
                <a
                  v-for="link in sourcesOf(row)"
                  :key="link.id"
                  class="csrc"
                  :href="link.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  :title="linkTitle(link)"
                >
                  <span class="csrc-id">{{ link.id }}</span>
                  <span class="csrc-title">{{ link.title }}</span>
                  <span class="csrc-meta">
                    <template v-if="link.userTag">补充 · </template>{{ link.site || '未知站点' }}
                  </span>
                </a>
                <p v-if="!sourcesOf(row).length" class="crow-detail-empty">
                  {{
                    row.skipped
                      ? '该站点没有采到可用页面。'
                      : '采集完成后，这里会列出该维度抓到的页面标题、发布日期和原文链接。'
                  }}
                </p>
                <p v-else-if="sourceCountOf(row) > 12" class="crow-detail-empty">
                  还有 {{ sourceCountOf(row) - 12 }} 个页面未展开，可在来源编号里继续查看。
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </Transition>
  </template>
</template>

<style scoped src="./collect.css"></style>
<style scoped src="./pane-shared.css"></style>
