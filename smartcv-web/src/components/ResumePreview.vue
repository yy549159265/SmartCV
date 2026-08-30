<script setup lang="ts">
/**
 * 右侧 · 实时预览（A4 成品效果）
 *
 * 数据和编辑画布完全同源（同一个 store.resume），任何修改立刻同步到这里。
 *
 * 分页原理（详见 composables/usePagination.ts）：
 *   1. 本组件里有一个"隐藏测量层"，把全部章节连续渲染一遍（与 A4 内容区等宽）；
 *   2. usePagination 测量每个章节的高度，把分页方案写入 store.pagePlan；
 *   3. 下方 A4 纸张按方案分页渲染；画布的红线也按方案绘制 —— 三处永远一致。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { usePagination } from '@/composables/usePagination'
import { previewZoom, ZOOM_LEVELS } from '@/composables/usePreviewZoom'
import { CONTENT_WIDTH, PAGE_HEIGHT, PAGE_PADDING, PAGE_WIDTH } from '@/utils/constants'
import { pageRunSpecs, type PageUnit, type RunSpec } from '@/utils/pagination'
import PreviewSection from './PreviewSection.vue'
import { useResumeStore } from '@/stores/resume'
import type { Section } from '@/types'

const store = useResumeStore()

/* ---------- 隐藏测量层：连续渲染全部章节，用于测量高度算分页 ---------- */
const measureFlowEl = ref<HTMLElement | null>(null)
usePagination(measureFlowEl)

/* ---------- 缩放：与优化页共用 previewZoom，两边字号永远一致 ---------- */

/** A4 纸张样式：固定 A4 尺寸 + 页边距 + 缩放 */
const pageStyle = computed(() => ({
  width: `${PAGE_WIDTH}px`,
  minHeight: `${PAGE_HEIGHT}px`,
  padding: `${PAGE_PADDING}px`,
  zoom: previewZoom.value,
}))

/* ---------- 分页渲染：把每页的单元 id 还原成若干"连续同章节片段"(RunSpec) ---------- */
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

/* ---------- 选中高亮：画布点了章节/内容后，预览里对应的渲染块持续闪烁提示位置 ---------- */
const pageStackEl = ref<HTMLElement | null>(null)

watch(
  () => store.selectedId,
  async (id) => {
    // 先清掉上次的高亮
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
    // 滚到第一个匹配块，让用户能看见它在哪一页
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
      <n-button-group size="tiny">
        <n-button
          v-for="z in ZOOM_LEVELS"
          :key="z"
          :type="previewZoom === z ? 'primary' : 'default'"
          ghost
          @click="previewZoom = z"
        >
          {{ Math.round(z * 100) }}%
        </n-button>
      </n-button-group>
    </div>

    <div class="preview-scroll">
      <!-- 隐藏测量层：position 绝对定位移出可视区，visibility 隐藏但仍占布局 -->
      <div ref="measureFlowEl" class="measure-flow" :style="{ width: `${CONTENT_WIDTH}px` }">
        <PreviewSection
          v-for="g in store.resume"
          :key="g.id"
          :section="g"
          :data-section-id="g.id"
          :data-forced="g.pageBreakBefore ? 'true' : undefined"
        />
      </div>

      <!-- 分页后的 A4 纸张 -->
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
  background: #e8eaee;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid var(--border);
}
.preview-title {
  font-weight: 600;
  font-size: 14px;
}
.preview-spacer {
  flex: 1;
}

.preview-scroll {
  flex: 1;
  overflow: auto;
  padding: 20px 12px 60px;
  position: relative;
}

/* 隐藏测量层：移出可视区域，不影响滚动布局 */
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
  gap: 24px;
}

.a4-page {
  position: relative;
  background: #fff;
  box-shadow:
    0 1px 3px rgba(15, 23, 42, 0.08),
    0 8px 24px rgba(15, 23, 42, 0.1);
}

.page-number {
  position: absolute;
  bottom: 12px;
  right: 16px;
  font-size: 11px;
  color: #9ca3af;
  pointer-events: none;
}

.preview-empty {
  margin-top: 80px;
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
}
.preview-empty div {
  font-size: 40px;
  margin-bottom: 8px;
}
</style>
