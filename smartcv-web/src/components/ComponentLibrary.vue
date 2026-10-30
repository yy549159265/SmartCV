<script setup lang="ts">
/**
 * 顶部 · 组件库（横向展开式面板，位于编辑画布上方）
 *
 * 一级分类三个（Tab 切换）：
 *  - 章节：空白章节 + 命名章节预设（个人简介 / 教育经历 / 工作经历 / 项目经历 / 专业技能…）；
 *  - 布局：空白布局 + 结构预设（2列 / 3列 / 2行 / 3行），卡片带结构示意图；
 *  - 组件：基础组件（通用内容类型）+ 内容预设，两个二级 Tab，支持搜索。
 *
 * 添加方式两种：
 *  - 点击卡片 = 快速添加（章节 → 画布末尾；布局 → 当前选中章节；内容 → 当前选中窗口）；
 *  - 拖拽 = 精确定位（拖到画布指定位置）。
 *
 * 拖拽用 vue-draggable-plus（内部 SortableJS），三个分组名严格分开
 * （smartcv-group / smartcv-row / smartcv-content），与画布各列表一一对应，
 * 拖拽机制与既有实现完全一致，未做任何改动。
 */
import { computed, ref } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import {
  CONTENT_PRESETS,
  GENERIC_CONTENT_PRESETS,
  GENERIC_SECTION_PRESETS,
  GENERIC_ROW_PRESETS,
  SECTION_PRESETS,
  ROW_PRESETS,
  type ContentPreset,
  type LayoutWindowPreset,
  type RowPreset,
  type SectionPreset,
} from '@/data/presets'
import { CONTENT_TYPE_NAMES } from '@/utils/constants'
import IconGlyph from '@/components/IconGlyph.vue'
import { useResumeStore } from '@/stores/resume'
import { message } from '@/utils/feedback'

const store = useResumeStore()

/** 内容区展示的内容预设（过滤掉 hidden 的） */
const visibleContentPresets = CONTENT_PRESETS.filter((p) => !p.hidden)

/** 面板收起状态：收起后画布获得更多空间 */
const collapsed = ref(false)

/** 一级分类（图标与主页功能介绍区共用同一套 IconGlyph 资源） */
type TabKey = 'section' | 'layout' | 'content'
const TABS: { key: TabKey; label: string; icon: 'layout-list' | 'columns-2' | 'shapes' }[] = [
  { key: 'section', label: '章节', icon: 'layout-list' },
  { key: 'layout', label: '布局', icon: 'columns-2' },
  { key: 'content', label: '组件', icon: 'shapes' },
]
const activeTab = ref<TabKey>('section')

/** 组件二级 Tab：基础组件 / 内容预设 */
const contentSub = ref<'basic' | 'preset'>('basic')
/** 搜索关键字（匹配名称与说明） */
const contentQuery = ref('')

/* ---------- 拖拽配置（与画布各列表同组；pull:clone = 拖出去复制一份） ---------- */
const sectionProps = { group: { name: 'smartcv-group', pull: 'clone' as const, put: false }, sort: false, animation: 150 }
const rowProps = { group: { name: 'smartcv-row', pull: 'clone' as const, put: false }, sort: false, animation: 150 }
const contentProps = { group: { name: 'smartcv-content', pull: 'clone' as const, put: false }, sort: false, animation: 150 }

/** 各列表的预设数据（只读，拖拽克隆不会修改它们） */
const sectionGeneral = ref(GENERIC_SECTION_PRESETS)
const sectionPresetList = ref(SECTION_PRESETS)
const rowGeneral = ref(GENERIC_ROW_PRESETS)
const rowPresetList = ref(ROW_PRESETS)
const contentGeneral = ref(GENERIC_CONTENT_PRESETS)
const contentPresetList = ref(visibleContentPresets)

/** 搜索过滤：组件/预设卡片按名称与说明匹配（列表本身不动，拖拽数据不受影响） */
const matchQuery = (name: string, desc: string) => {
  const q = contentQuery.value.trim().toLowerCase()
  if (!q) return true
  return name.toLowerCase().includes(q) || desc.toLowerCase().includes(q)
}

/* ---------- 点击添加（拖拽之外的快捷通道，全部走 store 既有 action） ---------- */

/** 章节预设点击：追加到画布末尾并选中 */
function onSectionClick(p: SectionPreset) {
  store.addSection(p)
  message.success(`已添加「${p.name}」`)
}

/** 布局预设点击：加到当前选中章节的末尾并选中（选中窗口/内容时用其所属章节） */
function onRowClick(p: RowPreset) {
  const s = store.selectedSection ?? store.selectedRow?.section ?? store.selectedContent?.section
  if (!s) {
    message.warning('先在画布中选中一个章节，再添加布局')
    return
  }
  const row = store.addRowFromPreset(s.id, p)
  if (row) {
    store.select(row.id)
    message.success(`已添加「${p.name}」`)
  }
}

/** 内容预设点击：加到当前选中的布局窗口（没有则用选中章节的最后一片窗口；再没有就新建） */
function onContentClick(p: ContentPreset) {
  const target = store.selectedContent ?? store.selectedRow
  if (target) {
    store.addContent(target.section.id, target.row.id, p)
    message.success(`已添加「${p.name}」`)
    return
  }
  const s = store.selectedSection
  if (s) {
    // addContent 内部会自动落到容器窗口的最后一片叶子，这里只需要顶层最后一行
    if (s.rows.length > 0) {
      store.addContent(s.id, s.rows[s.rows.length - 1].id, p)
    } else {
      const row = store.addRow(s.id)
      if (row) store.addContent(s.id, row.id, p)
    }
    message.success(`已添加「${p.name}」`)
    return
  }
  message.warning('先在画布中选中一个章节或布局窗口，再添加组件')
}

/**
 * 卡片悬停提示：名称、说明和两种添加方式都必须能从 title 里看到。
 */
function cardTip(p: { name: string; desc: string }, where: string) {
  return `${p.name} · ${p.desc}｜点击添加；或拖到${where}`
}

/** 章节预设卡片：统计自带的模块数（含嵌套子窗口里的内容），作为「包含模块」提示 */
const moduleCount = (p: SectionPreset) =>
  (p.rows ?? []).reduce(function count(n: number, r: LayoutWindowPreset): number {
    return n + (r.contents?.length ?? 0) + (r.rows ?? []).reduce(count, 0)
  }, 0)

/** 布局卡片的结构示意图样式：按列/行数取不同 class */
const rowDiagramClass = (p: RowPreset) => {
  if (p.columns === 2) return 'd-2col'
  if (p.columns === 3) return 'd-3col'
  if (p.rows === 2) return 'd-2row'
  if (p.rows === 3) return 'd-3row'
  return 'd-blank'
}
</script>

<template>
  <section class="library">
    <!-- 单行工具栏：与「编辑画布」工具栏同高同格式（图标块 + 粗标题 + 分类 Tab + 提示/收起） -->
    <div class="library-header">
      <span class="library-title-icon"><IconGlyph name="layout-template" :size="15" /></span>
      <h2 class="library-title">组件库</h2>
      <nav v-show="!collapsed" class="library-tabs">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="library-tab"
          :class="{ active: activeTab === t.key }"
          @click="activeTab = t.key"
        >
          <IconGlyph :name="t.icon" :size="13" />
          {{ t.label }}
        </button>
      </nav>
      <span class="library-hint">点击添加，或拖到画布指定位置</span>
      <span class="library-spacer" />
      <button
        class="library-collapse"
        :title="collapsed ? '展开组件库' : '收起组件库'"
        @click="collapsed = !collapsed"
      >
        <IconGlyph :name="collapsed ? 'chevron-down' : 'chevron-up'" :size="14" />
      </button>
    </div>

    <!-- ==================== 面板主体 ==================== -->
    <div v-show="!collapsed" class="library-body">
      <!-- ---------- 章节 ---------- -->
      <div v-if="activeTab === 'section'" class="lib-pane">
        <VueDraggable v-model="sectionGeneral" v-bind="sectionProps" class="section-grid">
          <button
            v-for="p in sectionGeneral"
            :key="p.id"
            class="sec-card sec-card-blank"
            :title="cardTip(p, '画布空白处')"
            @click="onSectionClick(p)"
          >
            <span class="sec-icon" v-html="p.icon" />
            <span class="sec-info">
              <span class="sec-name">{{ p.name }}</span>
              <span class="sec-desc">{{ p.desc }}</span>
            </span>
          </button>
        </VueDraggable>

        <VueDraggable v-model="sectionPresetList" v-bind="sectionProps" class="section-grid">
          <button
            v-for="p in sectionPresetList"
            :key="p.id"
            class="sec-card"
            :title="cardTip(p, '画布空白处')"
            @click="onSectionClick(p)"
          >
            <span class="sec-icon" v-html="p.icon" />
            <span class="sec-info">
              <span class="sec-name">{{ p.name }}</span>
              <span class="sec-desc">{{ p.desc }}</span>
            </span>
            <span class="sec-modules">{{ moduleCount(p) }} 个模块</span>
          </button>
        </VueDraggable>
      </div>

      <!-- ---------- 布局 ---------- -->
      <div v-else-if="activeTab === 'layout'" class="lib-pane">
        <VueDraggable v-model="rowGeneral" v-bind="rowProps" class="layout-grid">
          <button
            v-for="p in rowGeneral"
            :key="p.id"
            class="layout-card layout-card-blank"
            :title="cardTip(p, '章节内')"
            @click="onRowClick(p)"
          >
            <span class="layout-diagram d-blank" />
            <span class="layout-info">
              <span class="layout-name">{{ p.name }}</span>
              <span class="layout-desc">{{ p.desc }}</span>
            </span>
          </button>
        </VueDraggable>

        <VueDraggable v-model="rowPresetList" v-bind="rowProps" class="layout-grid">
          <button
            v-for="p in rowPresetList"
            :key="p.id"
            class="layout-card"
            :title="cardTip(p, '章节内')"
            @click="onRowClick(p)"
          >
            <!-- 结构示意图：列布局 = 竖条并排，行布局 = 横条堆叠（条数 = 列/行数） -->
            <span class="layout-diagram" :class="rowDiagramClass(p)">
              <i v-for="n in (p.columns ?? p.rows ?? 0)" :key="n" />
            </span>
            <span class="layout-info">
              <span class="layout-name">{{ p.name }}</span>
              <span class="layout-desc">{{ p.desc }}</span>
            </span>
          </button>
        </VueDraggable>
      </div>

      <!-- ---------- 组件 ---------- -->
      <div v-else class="lib-pane">
        <div class="content-toolbar">
          <div class="content-subtabs">
            <button
              class="content-subtab"
              :class="{ active: contentSub === 'basic' }"
              @click="contentSub = 'basic'"
            >
              组件
            </button>
            <button
              class="content-subtab"
              :class="{ active: contentSub === 'preset' }"
              @click="contentSub = 'preset'"
            >
              预设
            </button>
          </div>
          <label class="content-search">
            <IconGlyph name="search" :size="12" />
            <input v-model="contentQuery" type="text" placeholder="搜索组件…" />
          </label>
        </div>

        <VueDraggable v-if="contentSub === 'basic'" v-model="contentGeneral" v-bind="contentProps" class="content-grid">
          <button
            v-for="p in contentGeneral"
            v-show="matchQuery(p.name, p.desc)"
            :key="p.id"
            class="content-card"
            :title="cardTip(p, '某个布局窗口内部')"
            @click="onContentClick(p)"
          >
            <span class="content-icon" v-html="p.icon" />
            <span class="content-info">
              <span class="content-name">{{ p.name }}</span>
              <span class="content-desc">{{ p.desc }}</span>
            </span>
          </button>
        </VueDraggable>

        <VueDraggable v-else v-model="contentPresetList" v-bind="contentProps" class="content-grid">
          <button
            v-for="p in contentPresetList"
            v-show="matchQuery(p.name, p.desc)"
            :key="p.id"
            class="content-card"
            :title="cardTip(p, '某个布局窗口内部')"
            @click="onContentClick(p)"
          >
            <span class="content-icon" v-html="p.icon" />
            <span class="content-info">
              <span class="content-name">{{ p.name }}</span>
              <span class="content-desc">{{ p.desc }}</span>
            </span>
            <span class="content-type">{{ CONTENT_TYPE_NAMES[p.type] }}</span>
          </button>
        </VueDraggable>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ============================================================
 * 面板骨架：横向条带，位于编辑画布上方
 * ============================================================ */
.library {
  flex: none;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
  /* 作为容器查询参照：编辑列被拖窄时，头部按实际宽度收缩而不是把文字挤成竖排 */
  container-type: inline-size;
}

/* 单行工具栏：与画布工具栏同高（40px）、同 padding、同标题/图标规格 */
.library-header {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border);
}
.library-title-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--primary-soft);
  color: var(--primary);
}
.library-title {
  flex: none;
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  white-space: nowrap;
  color: var(--text);
}
/* 一级分类 Tab：与主页功能介绍区同款图标 */
.library-tabs {
  display: flex;
  flex: none;
  gap: 4px;
  margin-left: 12px;
}
/* 提示放在标题/Tab 同一侧（与编辑画布工具栏一致），窄列时收缩省略 */
.library-hint {
  flex: 0 1 auto;
  margin-left: 10px;
  font-size: 11.5px;
  color: var(--text-tertiary);
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.library-spacer {
  flex: 1;
}
.library-collapse {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    border-color 0.14s var(--ease),
    color 0.14s var(--ease);
}
.library-collapse:hover {
  background: var(--surface-soft);
  border-color: var(--border);
  color: var(--text);
}
.library-tab {
  display: flex;
  align-items: center;
  flex: none;
  gap: 6px;
  height: 28px;
  padding: 0 12px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.library-tab .icon-glyph {
  opacity: 0.7;
}
.library-tab:hover {
  background: var(--surface-soft);
  color: var(--text);
}
.library-tab.active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}
.library-tab.active .icon-glyph {
  opacity: 1;
}

/* ============================================================
 * 面板主体：横向滚动 + 卡片网格
 * ============================================================ */
.library-body {
  padding: 12px 14px 14px;
  max-height: 240px;
  overflow: auto;
}

.lib-pane {
  padding-top: 12px;
}

/* ---------- 章节：紧凑卡片网格 ---------- */
.section-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(176px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.section-grid:first-child {
  margin-top: 0;
}
.sec-card {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--panel-bg);
  text-align: left;
  cursor: grab;
  user-select: none;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease),
    transform 0.14s var(--ease),
    box-shadow 0.14s var(--ease);
}
.sec-card:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px -8px rgba(28, 33, 48, 0.18);
}
.sec-card:active {
  cursor: grabbing;
  transform: translateY(0);
}
/* 空白章节：独立入口，虚线边框 + 加号感 */
.sec-card-blank {
  border-style: dashed;
  background: var(--primary-faint);
}
.sec-card-blank:hover {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.sec-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: var(--surface-soft);
  font-size: 16px;
  line-height: 1;
}
.sec-card-blank .sec-icon {
  background: var(--panel-bg);
}
.sec-icon :deep(svg) {
  width: 1em;
  height: 1em;
  display: block;
}
.sec-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.sec-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.sec-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* 模块数角标：行内徽标（不用绝对定位，避免压住卡片名称） */
.sec-modules {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--primary-soft);
  font-size: 9.5px;
  line-height: 1.5;
  color: var(--primary-hover);
  white-space: nowrap;
}

/* ---------- 布局：结构示意图卡片 ---------- */
.layout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.layout-grid:first-child {
  margin-top: 0;
}
.layout-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--panel-bg);
  text-align: left;
  cursor: grab;
  user-select: none;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease),
    transform 0.14s var(--ease),
    box-shadow 0.14s var(--ease);
}
.layout-card:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px -8px rgba(28, 33, 48, 0.18);
}
.layout-card:active {
  cursor: grabbing;
  transform: translateY(0);
}
/* 空白布局：独立入口，虚线 */
.layout-card-blank {
  border-style: dashed;
  background: var(--primary-faint);
}
.layout-card-blank:hover {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.layout-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.layout-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.layout-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 结构示意图：白条小盒子组成的微型线框图（竖条 = 列布局，横条 = 行布局） */
.layout-diagram {
  flex: none;
  display: flex;
  gap: 3px;
  width: 42px;
  height: 32px;
  padding: 4px;
  border-radius: 7px;
  background: var(--surface-soft);
}
.layout-diagram i {
  flex: 1;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--border-strong);
  border-radius: 3px;
  background: var(--panel-bg);
}
/* 第一格用主色淡底强调「结构起点」 */
.layout-diagram i:first-child {
  border-color: rgba(71, 83, 199, 0.45);
  background: var(--primary-soft);
}
.d-2col,
.d-3col {
  flex-direction: row;
}
.d-2row,
.d-3row {
  flex-direction: column;
}
/* 空白布局：虚线空框，突出「从零开始」 */
.d-blank {
  border: 1.5px dashed var(--border-strong);
  background: transparent;
}
.d-blank i {
  display: none;
}

/* ---------- 组件：二级 Tab + 搜索 + 分组网格 ---------- */
.content-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.content-subtabs {
  display: flex;
  gap: 2px;
  flex: none;
  padding: 2px;
  border-radius: 8px;
  background: var(--surface-soft);
}
.content-subtab {
  height: 24px;
  padding: 0 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.content-subtab:hover {
  color: var(--text);
}
.content-subtab.active {
  background: var(--panel-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.08);
}
.content-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  max-width: 240px;
  height: 28px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-bg);
  color: var(--text-tertiary);
  transition: border-color 0.14s var(--ease), box-shadow 0.14s var(--ease);
}
.content-search:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(71, 83, 199, 0.12);
  color: var(--primary);
}
.content-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 12px;
  color: var(--text);
}
.content-search input::placeholder {
  color: var(--text-tertiary);
}

.content-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 8px;
}
.content-card {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--panel-bg);
  text-align: left;
  cursor: grab;
  user-select: none;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease),
    transform 0.14s var(--ease),
    box-shadow 0.14s var(--ease);
}
.content-card:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px -8px rgba(28, 33, 48, 0.18);
}
.content-card:active {
  cursor: grabbing;
  transform: translateY(0);
}
.content-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--surface-soft);
  font-size: 15px;
  line-height: 1;
}
.content-icon :deep(svg) {
  width: 1em;
  height: 1em;
  display: block;
}
.content-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.content-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.content-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
/* 类型角标：行内徽标（同模块数角标，不压文字） */
.content-type {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--primary-soft);
  font-size: 9.5px;
  line-height: 1.5;
  color: var(--primary-hover);
  white-space: nowrap;
}

/* ============================================================
 * 编辑列被拖窄：先让提示让位，再收紧 Tab，标题与分类保持单行
 * ============================================================ */
@container (max-width: 520px) {
  .library-hint {
    display: none;
  }
  .library-tabs {
    margin-left: 6px;
    gap: 2px;
  }
  .library-tab {
    padding: 0 8px;
  }
}

/* ============================================================
 * 窄屏：网格更紧凑
 * ============================================================ */
@media (max-width: 760px) {
  .library-hint {
    display: none;
  }
  .library-body {
    max-height: 200px;
  }
}
</style>
