<script setup lang="ts">
/**
 * 左侧 · 组件库（拖拽起点）
 *
 * 组件分三组（都可折叠/展开）：
 *  - 章节：空白章节 + 命名章节预设；
 *  - 布局：窗口布局（＋上/下/左/右 或拖拽排列）+ 结构预设（2列 / 3列 / 2行 / 3行）；
 *  - 内容：7 种通用类型（含占位组件）+ 命名内容预设。
 *
 * 拖拽：用 vue-draggable-plus（内部是 SortableJS）。
 * 这里每个列表配置拖拽分组 pull:'clone'（SortableJS 的 group 选项）：按住卡片拖进画布列表 = 复制一份预设数据，
 * 画布列表在 add 事件里用这份数据生成真实的章节/窗口/内容。
 * 三个拖拽分组名严格分开（smartcv-group / smartcv-row / smartcv-content），
 * 章节、布局、内容各自只能拖进对应的画布列表。
 */
import { ref } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import {
  CONTENT_PRESETS,
  GENERIC_CONTENT_PRESETS,
  GENERIC_SECTION_PRESETS,
  GENERIC_ROW_PRESETS,
  SECTION_PRESETS,
  ROW_PRESETS,
} from '@/data/presets'
import { CONTENT_TYPE_NAMES } from '@/utils/constants'

/** 内容区展示的内容预设（过滤掉 hidden 的） */
const visibleContentPresets = CONTENT_PRESETS.filter((p) => !p.hidden)

/** 主分组折叠状态 */
const chapterCollapsed = ref(false)
const layoutCollapsed = ref(false)
const contentCollapsed = ref(false)

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
</script>

<template>
  <aside class="library">
    <div class="library-header">
      <h2 class="library-title">🧱 组件库</h2>
      <p class="library-sub">按住卡片，拖进中间画布</p>
    </div>

    <div class="library-scroll">
      <!-- ==================== 章节 ==================== -->
      <section class="lib-section">
        <button class="lib-section-title" @click="chapterCollapsed = !chapterCollapsed">
          <span>{{ chapterCollapsed ? '▸' : '▾' }}</span>
          章节
        </button>

        <template v-if="!chapterCollapsed">
          <h4 class="lib-sub-title">通用</h4>
          <VueDraggable v-model="sectionGeneral" v-bind="sectionProps" class="lib-list">
            <div
              v-for="(p, i) in sectionGeneral"
              :key="p.id"
              v-motion
              :initial="{ opacity: 0, y: 8 }"
              :enter="{ opacity: 1, y: 0, transition: { delay: i * 30, duration: 300 } }"
              class="lib-card"
              title="拖到画布空白处，生成新章节"
            >
              <span class="lib-icon">{{ p.icon }}</span>
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>

          <h4 class="lib-sub-title">预设</h4>
          <VueDraggable v-model="sectionPresetList" v-bind="sectionProps" class="lib-list">
            <div
              v-for="(p, i) in sectionPresetList"
              :key="p.id"
              v-motion
              :initial="{ opacity: 0, y: 8 }"
              :enter="{ opacity: 1, y: 0, transition: { delay: i * 30, duration: 300 } }"
              class="lib-card"
              title="拖到画布空白处，生成新章节"
            >
              <span class="lib-icon">{{ p.icon }}</span>
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>
        </template>
      </section>

      <!-- ==================== 布局 ==================== -->
      <section class="lib-section">
        <button class="lib-section-title" @click="layoutCollapsed = !layoutCollapsed">
          <span>{{ layoutCollapsed ? '▸' : '▾' }}</span>
          布局
        </button>

        <template v-if="!layoutCollapsed">
          <h4 class="lib-sub-title">通用</h4>
          <VueDraggable v-model="rowGeneral" v-bind="rowProps" class="lib-list">
            <div
              v-for="(p, i) in rowGeneral"
              :key="p.id"
              v-motion
              :initial="{ opacity: 0, y: 8 }"
              :enter="{ opacity: 1, y: 0, transition: { delay: i * 30, duration: 300 } }"
              class="lib-card row-card"
              title="拖到章节里，用 ＋上/下/左/右 或拖拽排列"
            >
              <span class="lib-icon">{{ p.icon }}</span>
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>

          <h4 class="lib-sub-title">预设</h4>
          <VueDraggable v-model="rowPresetList" v-bind="rowProps" class="lib-list">
            <div
              v-for="(p, i) in rowPresetList"
              :key="p.id"
              v-motion
              :initial="{ opacity: 0, y: 8 }"
              :enter="{ opacity: 1, y: 0, transition: { delay: i * 30, duration: 300 } }"
              class="lib-card row-card"
              title="拖到章节里，生成对应结构的布局"
            >
              <span class="lib-icon">{{ p.icon }}</span>
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>
        </template>
      </section>

      <!-- ==================== 内容 ==================== -->
      <section class="lib-section">
        <button class="lib-section-title" @click="contentCollapsed = !contentCollapsed">
          <span>{{ contentCollapsed ? '▸' : '▾' }}</span>
          内容
        </button>

        <template v-if="!contentCollapsed">
          <h4 class="lib-sub-title">通用</h4>
          <VueDraggable v-model="contentGeneral" v-bind="contentProps" class="lib-list">
            <div
              v-for="(p, i) in contentGeneral"
              :key="p.id"
              v-motion
              :initial="{ opacity: 0, y: 8 }"
              :enter="{ opacity: 1, y: 0, transition: { delay: i * 30, duration: 300 } }"
              class="lib-card"
              title="拖到某个布局窗口内部"
            >
              <span class="lib-icon">{{ p.icon }}</span>
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>

          <h4 class="lib-sub-title">预设</h4>
          <VueDraggable v-model="contentPresetList" v-bind="contentProps" class="lib-list">
            <div
              v-for="(p, i) in contentPresetList"
              :key="p.id"
              v-motion
              :initial="{ opacity: 0, y: 8 }"
              :enter="{ opacity: 1, y: 0, transition: { delay: i * 30, duration: 300 } }"
              class="lib-card"
              title="拖到某个布局窗口内部"
            >
              <span class="lib-icon">{{ p.icon }}</span>
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
              <span class="lib-type">{{ CONTENT_TYPE_NAMES[p.type] }}</span>
            </div>
          </VueDraggable>
        </template>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.library {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  background: #fff;
  border-right: 1px solid var(--border);
}

.library-header {
  padding: 14px 16px 10px;
  border-bottom: 1px solid #f0f1f4;
}

.library-title {
  margin: 0;
  font-size: 15px;
}

.library-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: #9ca3af;
}

.library-scroll {
  flex: 1;
  overflow: auto;
  padding: 12px 12px 24px;
}

.lib-section {
  margin-bottom: 18px;
}

.lib-section-title {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  margin: 0 0 8px;
  padding: 4px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s;
}
.lib-section-title:hover {
  background: #f2f5fa;
}

.lib-sub-title {
  margin: 8px 0 6px;
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  padding-left: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.lib-sub-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #f0f1f4;
}

.lib-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.lib-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e5e9f1;
  border-radius: 8px;
  background: #fbfcfe;
  cursor: grab;
  user-select: none;
  transition:
    border-color 0.15s,
    box-shadow 0.15s,
    transform 0.15s;
}
.lib-card:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(79, 124, 255, 0.12);
  transform: translateY(-1px);
}
.lib-card:active {
  cursor: grabbing;
}

/* 布局卡片：虚线边框，和内容卡片区分 */
.row-card {
  border-style: dashed;
}

.lib-icon {
  flex: none;
  font-size: 20px;
  width: 28px;
  text-align: center;
}

.lib-info {
  flex: 1;
  min-width: 0;
}

.lib-name {
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
}

.lib-desc {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

/* 命名内容预设上的类型角标（如 图标文字 / 列表文字） */
.lib-type {
  flex: none;
  font-size: 10px;
  color: #4f7cff;
  background: #eef3ff;
  border-radius: 4px;
  padding: 1px 6px;
}
</style>
