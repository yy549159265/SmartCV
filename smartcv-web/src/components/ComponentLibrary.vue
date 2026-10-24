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

/**
 * 卡片悬停提示：组件库被拖窄后名字/说明都会收起（只剩图标），
 * 名字、说明和拖拽用法都必须还能从 title 里看到。
 */
function cardTip(p: { name: string; desc: string }, action: string) {
  return `${p.name} · ${p.desc}｜${action}`
}
</script>

<template>
  <aside class="library">
    <div class="library-header">
      <h2 class="library-title">组件库</h2>
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
              v-for="p in sectionGeneral"
              :key="p.id"
              class="lib-card"
              :title="cardTip(p, '拖到画布空白处，生成新章节')"
            >
              <span class="lib-icon" v-html="p.icon" />
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>

          <h4 class="lib-sub-title">预设</h4>
          <VueDraggable v-model="sectionPresetList" v-bind="sectionProps" class="lib-list">
            <div
              v-for="p in sectionPresetList"
              :key="p.id"
              class="lib-card"
              :title="cardTip(p, '拖到画布空白处，生成新章节')"
            >
              <span class="lib-icon" v-html="p.icon" />
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
              v-for="p in rowGeneral"
              :key="p.id"
              class="lib-card row-card"
              :title="cardTip(p, '拖到章节里，用 ＋上/下/左/右 或拖拽排列')"
            >
              <span class="lib-icon" v-html="p.icon" />
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>

          <h4 class="lib-sub-title">预设</h4>
          <VueDraggable v-model="rowPresetList" v-bind="rowProps" class="lib-list">
            <div
              v-for="p in rowPresetList"
              :key="p.id"
              class="lib-card row-card"
              :title="cardTip(p, '拖到章节里，生成对应结构的布局')"
            >
              <span class="lib-icon" v-html="p.icon" />
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
              v-for="p in contentGeneral"
              :key="p.id"
              class="lib-card"
              :title="cardTip(p, '拖到某个布局窗口内部')"
            >
              <span class="lib-icon" v-html="p.icon" />
              <div class="lib-info">
                <div class="lib-name">{{ p.name }}</div>
                <div class="lib-desc">{{ p.desc }}</div>
              </div>
            </div>
          </VueDraggable>

          <h4 class="lib-sub-title">预设</h4>
          <VueDraggable v-model="contentPresetList" v-bind="contentProps" class="lib-list">
            <div
              v-for="p in contentPresetList"
              :key="p.id"
              class="lib-card"
              :title="cardTip(p, '拖到某个布局窗口内部')"
            >
              <span class="lib-icon" v-html="p.icon" />
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
  background: var(--panel-bg);
  border-right: 1px solid var(--border);
  /* 列宽可拖动：把侧栏本身作为容器，拖窄后自动进入"只显示图标"模式 */
  container-type: inline-size;
}

.library-header {
  padding: 18px 16px 14px;
  border-bottom: 1px solid var(--border);
}

.library-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text);
}

.library-sub {
  margin: 5px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-tertiary);
}

.library-scroll {
  flex: 1;
  overflow: auto;
  padding: 14px 10px 28px;
}

.lib-section {
  margin-bottom: 20px;
}

.lib-section-title {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  margin: 0 0 8px;
  padding: 5px 6px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease);
}
.lib-section-title:hover {
  background: var(--surface-soft);
}
.lib-section-title > span {
  width: 10px;
  color: var(--text-tertiary);
  font-size: 10px;
}

.lib-sub-title {
  margin: 10px 0 6px;
  padding: 0 6px;
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.lib-sub-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}

.lib-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 拖拽项：无边框、无投影的行式条目，悬停只换一层浅底色 */
.lib-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 8px;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: grab;
  user-select: none;
  transition: background 0.14s var(--ease);
}
.lib-card:hover {
  background: var(--surface-soft);
}
.lib-card:active {
  cursor: grabbing;
  background: var(--primary-faint);
}

/* 布局卡片：一层极浅的内衬，和内容卡片区分（不用刺眼的虚线框） */
.row-card {
  background: var(--surface-soft);
}
.row-card:hover {
  background: var(--primary-faint);
}

.lib-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  font-size: 18px;
  line-height: 1.2;
  text-align: center;
}
/* 类型图标可能是 emoji，也可能是内联 SVG（如「列表文字」）；SVG 按 1em 对齐文字 */
.lib-icon :deep(svg) {
  display: block;
  width: 1em;
  height: 1em;
}

.lib-info {
  flex: 1;
  min-width: 0;
}

.lib-name {
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1.45;
  color: var(--text);
}

.lib-desc {
  margin-top: 1px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--text-tertiary);
}

/* 命名内容预设上的类型角标（如 图标文字 / 列表文字） */
.lib-type {
  flex: none;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--primary-soft);
  font-size: 10px;
  line-height: 1.6;
  color: var(--primary-hover);
}

/* ============================================================
 * 压缩模式：组件库列被拖窄后只显示图标
 *
 * 名字、说明、类型角标都收起，卡片排成图标方格；
 * 拖拽用法与名字仍在卡片的 title（悬浮提示）里，不会丢信息。
 * 阈值 190px ≈ 名字/说明开始大量折行的宽度。
 * ============================================================ */
@container (max-width: 190px) {
  .library-header {
    padding: 14px 10px 10px;
  }
  /* 副标题（"按住卡片，拖进中间画布"）在窄栏里会折成三行，直接收起 */
  .library-sub {
    display: none;
  }
  .library-scroll {
    padding: 10px 6px 20px;
  }
  .lib-section-title {
    justify-content: center;
    padding: 5px 4px;
  }
  .lib-sub-title {
    justify-content: center;
    padding: 0 2px;
  }
  /* 小组标题右侧的延长线在窄栏里没有意义 */
  .lib-sub-title::after {
    display: none;
  }
  /* 一列图标 → 自动换行的图标方格 */
  .lib-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(34px, 1fr));
    gap: 4px;
  }
  .lib-card,
  .row-card {
    justify-content: center;
    padding: 7px 4px;
    gap: 0;
  }
  .lib-info,
  .lib-type {
    display: none;
  }
  .lib-icon {
    width: 100%;
  }
}
</style>
