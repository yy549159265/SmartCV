<script setup lang="ts">
/** 策略总结：竞争力定位 / 能力差距 / 改进优先级 / 简历优化建议 / 求职风险。 */
import { computed } from 'vue'
import type { EvidenceLink, PaneModule, PanelRow } from '@/types/market'
import { readStrategyPositioning, readStrategySection } from '@/features/market/strategy'
import FindingRow from './FindingRow.vue'
import SourceLinks from './SourceLinks.vue'

const props = defineProps<{
  hasRows: boolean
  emptyText: string
  activeModule: PaneModule | null
  moduleRows: PanelRow[]
  highlightKey: string
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()

const isStructured = computed(() => Boolean(props.activeModule?.data))
const positioning = computed(() => readStrategyPositioning(props.activeModule?.data))
const section = computed(() => readStrategySection(props.activeModule?.key || '', props.activeModule?.data))
</script>

<template>
  <div v-if="!hasRows" class="pane-empty">{{ emptyText }}</div>
  <template v-else>
    <Transition name="mod-swap" mode="out-in">
      <div
        :key="activeModule?.key || 'empty'"
        class="strategy-pane pane-module glass-surface"
        :class="{
          'tip-module': activeModule?.key === 'writing',
          'risk-module': activeModule?.key === 'risks',
        }"
      >
        <template v-if="isStructured">
          <!-- 竞争力定位：三个文字判断 + 两组列表 -->
          <template v-if="activeModule?.key === 'positioning'">
            <article
              v-for="block in positioning.blocks"
              :key="block.key"
              class="sp-block glass-item"
            >
              <span class="sp-block-name">{{ block.label }}</span>
              <p v-if="block.kind === 'text'" class="sp-text">{{ block.texts[0] }}</p>
              <ul v-else class="point-list">
                <li v-for="(text, index) in block.texts" :key="index">
                  <span class="point-mark"></span>
                  <span class="point-body point-text">{{ text }}</span>
                </li>
              </ul>
            </article>
          </template>

          <!-- 四类建议：每条一张卡，字段为空时不渲染 -->
          <template v-else>
            <div v-if="section.count" class="sp-head">
              <span class="sp-count">{{ section.count }} 项</span>
            </div>
            <article v-for="item in section.items" :key="item.key" class="sp-card glass-item">
              <div class="sp-card-head">
                <span class="sp-card-title">{{ item.title }}</span>
                <span v-if="item.badge" class="sp-badge" :class="`tone-${item.tone}`">
                  {{ item.badge }}
                </span>
              </div>

              <div v-for="field in item.fields" :key="field.key" class="sp-field">
                <span class="sp-field-label">{{ field.label }}</span>
                <p v-if="field.kind === 'text'" class="sp-text">{{ field.texts[0] }}</p>
                <ul v-else class="point-list">
                  <li v-for="(text, index) in field.texts" :key="index">
                    <span class="point-mark"></span>
                    <span class="point-body point-text">{{ text }}</span>
                  </li>
                </ul>
              </div>

              <div v-if="item.evidence.length" class="sp-links">
                <SourceLinks
                  :links="linksOf({ evidence: item.evidence })"
                  :more="moreLinks({ evidence: item.evidence })"
                />
              </div>
            </article>
            <div v-if="!section.count" class="pane-empty">
              该模块暂无内容，切换上方卡片查看其他结论。
            </div>
          </template>
        </template>

        <!-- 旧快照：按结论行渲染 -->
        <template v-else>
          <div
            v-if="activeModule?.key === 'writing' || activeModule?.key === 'risks'"
            class="module-head"
          >
            <span class="module-sub">{{ moduleRows.length }} 项</span>
          </div>
          <FindingRow
            v-for="(row, rowIndex) in moduleRows"
            :key="row.key"
            :row="row"
            :index="rowIndex"
            :highlight="highlightKey === row.key"
            :links="linksOf(row)"
            :more="moreLinks(row)"
          />
          <div v-if="!moduleRows.length" class="pane-empty">
            该模块暂无内容，切换上方卡片查看其他结论。
          </div>
        </template>
      </div>
    </Transition>
  </template>
</template>

<style scoped src="./strategy.css"></style>
<style scoped src="./pane-shared.css"></style>
