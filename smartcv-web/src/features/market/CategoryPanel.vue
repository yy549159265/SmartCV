<script setup lang="ts">
/** 类别面板外壳：汇总卡 + 横向模块条 + 明细插槽，所有类别共用这一层骨架。 */
import { nextTick, ref, watch } from 'vue'
import IconGlyph from '@/components/IconGlyph.vue'
import type { CategoryCard, CategoryModule } from './types'

const props = defineProps<{
  card: CategoryCard
  modules: CategoryModule[]
  activeModuleKey: string
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
}>()

/** 横向标签条：当前标签滚到可视区中间，箭头按可滚距离禁用。 */
const moduleTabsEl = ref<HTMLElement | null>(null)
const tabsCanPrev = ref(false)
const tabsCanNext = ref(false)

function syncTabArrows() {
  const el = moduleTabsEl.value
  if (!el) return
  tabsCanPrev.value = el.scrollLeft > 2
  tabsCanNext.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 2
}

function scrollModuleTabs(direction: -1 | 1) {
  const el = moduleTabsEl.value
  if (!el) return
  el.scrollBy({ left: direction * Math.max(120, el.clientWidth * 0.6), behavior: 'smooth' })
}

function centerActiveModuleTab() {
  const el = moduleTabsEl.value
  const active = el?.querySelector<HTMLElement>('.m-tab.active')
  if (!el || !active) return
  // 用视口坐标算相对位移：offsetLeft 会受 offsetParent 影响，标签条定位后会偏。
  const delta = active.getBoundingClientRect().left - el.getBoundingClientRect().left
  el.scrollLeft += delta - (el.clientWidth - active.offsetWidth) / 2
  syncTabArrows()
}

watch(
  [() => props.modules.map((mod) => mod.key).join('|'), () => props.activeModuleKey],
  () => {
    void nextTick(centerActiveModuleTab)
  },
)
</script>

<template>
  <div class="cat-pane">
    <div class="card-wrap">
      <section
        class="summary-card"
        :class="{ 'is-portrait': card.summary.type === 'portrait' }"
        :data-card="card.key"
      >
        <div class="card-head">
          <span class="icon-tile" aria-hidden="true">
            <IconGlyph :name="card.icon as any" :size="20" />
          </span>
          <div class="card-copy">
            <h2 class="card-title">{{ card.title }}</h2>
            <p class="card-sub">{{ card.subtitle }}</p>
          </div>
          <span class="card-status">{{ card.status }}</span>
        </div>

        <div class="summary-body">
          <slot name="summary">
            <div v-if="card.summary.type === 'steps'" class="summary-steps">
              <div v-for="step in card.summary.steps" :key="step.key" class="summary-step">
                <span class="summary-step-key">{{ step.key }}</span>
                <span class="summary-step-text">{{ step.text }}</span>
              </div>
            </div>
            <template v-else>
              <p v-if="card.summary.lead" class="summary-lead">{{ card.summary.lead }}</p>
              <div v-if="card.summary.meter !== null" class="summary-meter">
                <i :style="{ width: `${card.summary.meter}%` }"></i>
              </div>
              <div v-if="card.summary.stats.length" class="summary-stats">
                <div v-for="stat in card.summary.stats" :key="stat.label" class="summary-stat">
                  <b>{{ stat.value }}</b><span>{{ stat.label }}</span>
                </div>
              </div>
              <div v-if="card.summary.chips.length" class="summary-chips">
                <span v-for="chip in card.summary.chips" :key="chip" class="summary-chip">{{ chip }}</span>
              </div>
            </template>
          </slot>
        </div>

        <p v-if="card.note" class="card-note">{{ card.note }}</p>
      </section>
    </div>

    <div
      v-if="modules.length"
      class="tabs-bar"
      :class="{ 'can-prev': tabsCanPrev, 'can-next': tabsCanNext }"
    >
      <button
        type="button"
        class="tab-arrow"
        aria-label="向左滚动标签"
        :disabled="!tabsCanPrev"
        @click="scrollModuleTabs(-1)"
      >
        <IconGlyph name="chevron-left" :size="14" />
      </button>
      <div ref="moduleTabsEl" class="tabs-viewport" @scroll="syncTabArrows">
        <div class="tabs-track" role="tablist" aria-label="当前类别横向标签">
          <button
            v-for="mod in modules"
            :key="mod.key"
            type="button"
            role="tab"
            class="m-tab"
            :class="{ active: activeModuleKey === mod.key }"
            :aria-selected="activeModuleKey === mod.key"
            @click="emit('select', mod.key)"
          >
            <span class="m-tab-label">{{ mod.tabLabel }}</span>
            <span v-if="mod.meta" class="m-tab-meta">{{ mod.meta }}</span>
          </button>
        </div>
      </div>
      <button
        type="button"
        class="tab-arrow"
        aria-label="向右滚动标签"
        :disabled="!tabsCanNext"
        @click="scrollModuleTabs(1)"
      >
        <IconGlyph name="chevron-right" :size="14" />
      </button>
    </div>

    <div class="pane">
      <div class="pane-body active">
        <slot name="pane" />
      </div>
    </div>
  </div>
</template>

<style scoped src="./category-panel.css"></style>
