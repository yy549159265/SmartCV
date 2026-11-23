<script setup lang="ts">
/** 动态方面：基本情况 / 核心内容 / 重点方向 / 具体表现 / 优势 / 问题 / 趋势 / 结论。 */
import { computed } from 'vue'
import type { EvidenceLink } from '@/types/market'
import { readAspectSection } from '@/features/market/aspect'
import SourceLinks from './SourceLinks.vue'

const props = defineProps<{
  moduleKey: string
  data?: Record<string, unknown>
  linksOf: (row: { evidence?: string[] }) => EvidenceLink[]
  moreLinks: (row: { evidence?: string[] }) => number
}>()

const view = computed(() => readAspectSection(props.moduleKey, props.data))
const isEmpty = computed(() => !view.value.summary && !view.value.blocks.length)
</script>

<template>
  <Transition name="mod-swap" mode="out-in">
    <div :key="moduleKey" class="aspect-pane pane-module glass-surface">
      <div v-if="isEmpty" class="pane-empty">该模块暂无内容，切换上方卡片查看其他结论。</div>

      <template v-else>
        <div v-if="view.total || view.evidence.length" class="ap-head">
          <span v-if="view.total" class="ap-count">{{ view.total }} 条结论</span>
          <SourceLinks
            :links="linksOf({ evidence: view.evidence })"
            :more="moreLinks({ evidence: view.evidence })"
          />
        </div>

        <p v-if="view.summary" class="ap-lead">{{ view.summary }}</p>

        <article v-for="block in view.blocks" :key="block.key" class="ap-block glass-item">
          <div v-if="view.showLabels" class="ap-block-head">
            <span class="ap-block-name">{{ block.label }}</span>
          </div>

          <template v-if="block.kind === 'text'">
            <p v-for="(text, index) in block.texts" :key="index" class="ap-text">{{ text }}</p>
          </template>
          <ul v-else class="point-list">
            <li v-for="(text, index) in block.texts" :key="index">
              <span class="point-mark"></span>
              <span class="point-body point-text">{{ text }}</span>
            </li>
          </ul>
        </article>
      </template>
    </div>
  </Transition>
</template>

<style scoped src="./pane-shared.css"></style>
<style scoped src="./aspect.css"></style>
