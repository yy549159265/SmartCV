<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { usePagination } from '@/composables/usePagination'
import { previewZoom } from '@/composables/usePreviewZoom'
import { contentWidth, pageHeight, pageWidth } from '@/composables/usePageSize'
import { PAGE_PADDING } from '@/utils/constants'
import { pageRunSpecs, type PageUnit, type RunSpec } from '@/utils/pagination'
import PreviewSection from './PreviewSection.vue'
import { useResumeStore } from '@/stores/resume'
import type { Section } from '@/types'

const store = useResumeStore()

const measureFlowEl = ref<HTMLElement | null>(null)
usePagination(measureFlowEl)

const pageStyle = computed(() => ({
  width: `${pageWidth.value}px`,
  minHeight: `${pageHeight.value}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: previewZoom.value,
}))

const measureStyle = computed(() => ({ width: `${contentWidth.value}px` }))

const pages = computed(() =>
  store.pagePlan.pages.map((page) =>
    pageRunSpecs(
      page.unitIds
        .map((id) => store.unitById(id))
        .filter((u): u is PageUnit => u !== undefined),
    )
      .map((spec) => ({ spec, section: store.sectionById(spec.sectionId) }))
      .filter((x): x is { spec: RunSpec; section: Section } => x.section !== undefined),
  ),
)

const pageStackEl = ref<HTMLElement | null>(null)

watch(
  () => store.selectedId,
  async (id) => {
    pageStackEl.value?.querySelectorAll('.preview-flash').forEach((el) => el.classList.remove('preview-flash'))
    if (!id) return
    await nextTick()
    const selector = store.selectedSection
      ? `[data-section-id="${id}"]`
      : store.selectedContent
        ? `[data-content-id="${id}"]`
        : store.selectedRow
          ? `[data-row-id="${id}"]`
          : null
    if (!selector || !pageStackEl.value) return
    const matches = pageStackEl.value.querySelectorAll<HTMLElement>(selector)
    matches.forEach((el) => el.classList.add('preview-flash'))
    if (matches.length > 0) {
      matches[0].scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
    }
  },
)
</script>

<template>
  <aside class="preview">
    <div class="preview-toolbar">
      <span class="preview-title">实时预览</span>
      <n-tag size="small" round :bordered="false" type="primary">
        {{ store.pagePlan.pages.length }} 页
      </n-tag>
      <div class="preview-spacer" />
      <span class="preview-zoom-hint">缩放 {{ Math.round(previewZoom * 100) }}%（顶部工具栏调整）</span>
    </div>

    <div class="preview-scroll">
      <div ref="measureFlowEl" class="measure-flow" :style="measureStyle">
        <PreviewSection
          v-for="g in store.resume"
          :key="g.id"
          :section="g"
          :data-section-id="g.id"
          :data-forced="g.pageBreakBefore ? 'true' : undefined"
        />
      </div>

      <div ref="pageStackEl" class="page-stack">
        <div v-for="(page, i) in pages" :key="i" class="page-slot">
          <div class="a4-page" :style="pageStyle">
            <template v-for="(x, fi) in page" :key="`${x.spec.sectionId}:${x.spec.rowFrom}:${x.spec.rowTo}`">
              <PreviewSection
                :section="x.section!"
                :data-section-id="x.section!.id"
                :row-from="x.spec.rowFrom"
                :row-to="x.spec.rowTo"
                :show-title="x.spec.hasTitle"
                :top-pad="x.spec.topPad"
                :bottom-pad="x.spec.bottomPad"
                :space-before="x.spec.spaceBefore"
              />
            </template>
            <span class="page-number">{{ i + 1 }} / {{ pages.length }}</span>
          </div>
        </div>
        <div v-if="pages.length === 0" class="preview-empty">
          <div>📄</div>
          <p>暂无内容<br />去画布添加内容吧</p>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  background: var(--surface-sunken);
}

.preview-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
}
.preview-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}
.preview-spacer {
  flex: 1;
}
.preview-zoom-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.preview-scroll {
  flex: 1;
  overflow: auto;
  padding: var(--doc-workspace-pad);
  position: relative;
  background: var(--doc-workspace);
}

.measure-flow {
  position: absolute;
  top: 0;
  left: -9999px;
  visibility: hidden;
}

.page-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--doc-page-gap);
}

.a4-page {
  position: relative;
  background: var(--doc-paper);
  box-shadow: var(--doc-paper-shadow);
}

.page-number {
  position: absolute;
  bottom: 12px;
  right: 16px;
  font-size: 11px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.preview-empty {
  margin-top: 80px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12.5px;
}
.preview-empty div {
  font-size: 40px;
  margin-bottom: 8px;
}
</style>
