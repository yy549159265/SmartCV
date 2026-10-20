<script setup lang="ts">
/**
 * 应用入口：顶部工具条 + 页面
 *   主页（默认）/ 编辑简历 / 优化简历 / Agent 设置
 *
 * 简历的"从哪来"统一走主页（导入 PDF / 导入 JSON / 新建），编辑页不再提供导入入口。
 * 所有页面读写同一个 Pinia store（stores/resume.ts）—— 单一数据源。
 */
import { ref } from 'vue'
import { siGithub } from 'simple-icons'
import HomePage from '@/pages/HomePage.vue'
import EditorPage from '@/pages/EditorPage.vue'
import OptimizePage from '@/pages/OptimizePage.vue'
import ProviderSettingsPage from '@/pages/ProviderSettingsPage.vue'
import { useResumeStore } from '@/stores/resume'
import { useClickPopover } from '@/composables/useClickPopover'
import { message } from '@/utils/feedback'
import { brandSvg } from '@/data/icons'
import BrandMark from '@/components/BrandMark.vue'
import { themeOverrides } from '@/styles/naive-theme'

const store = useResumeStore()

/** GitHub 仓库跳转图标（头部右侧，新标签打开） */
const githubSvg = brandSvg(siGithub)

/** 清空确认弹层（受控，点外部自动关闭） */
const { show: clearConfirmShow, triggerRef: clearTriggerRef } = useClickPopover()

/* ---------- 顶部页面栏 ---------- */

type PageKey = 'home' | 'editor' | 'optimize' | 'provider'

const currentPage = ref<PageKey>('home')

const PAGES: { key: PageKey; label: string }[] = [
  { key: 'home', label: '主页' },
  { key: 'editor', label: '编辑简历' },
  { key: 'optimize', label: '优化简历' },
  { key: 'provider', label: 'Agent 设置' },
]

/* ---------- 保存 ---------- */

/** 手动保存：立即写入浏览器 localStorage */
function onSave() {
  store.saveToStorage()
  message.success('已保存到浏览器本地（刷新/关闭浏览器后内容仍在）')
}
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <div class="app-shell">
      <!-- 顶部工具条：品牌 + 页面栏 + 数据操作 -->
      <header class="app-header">
        <div class="brand">
          <BrandMark :size="22" />
          <span class="brand-name">SmartCV</span>
        </div>

      <!-- 页面栏 -->
      <nav class="page-tabs">
        <button
          v-for="p in PAGES"
          :key="p.key"
          class="page-tab"
          :class="{ active: currentPage === p.key }"
          @click="currentPage = p.key"
        >
          {{ p.label }}
        </button>
      </nav>

      <div class="header-actions">
        <a
          class="github-link"
          href="https://github.com/yy549159265/SmartCV"
          target="_blank"
          rel="noopener"
          title="GitHub 仓库"
          v-html="githubSvg"
        />
        <n-button size="small" quaternary @click="onSave">保存</n-button>
        <n-popconfirm
          v-model:show="clearConfirmShow"
          positive-text="清空"
          negative-text="取消"
          @positive-click="store.clearAll()"
        >
          <template #trigger>
            <span ref="clearTriggerRef" class="trigger-wrap">
              <n-button size="small" quaternary type="error">清空</n-button>
            </span>
          </template>
          确定清空所有内容吗？
        </n-popconfirm>
      </div>
    </header>

    <!-- 页面主体 -->
    <HomePage v-if="currentPage === 'home'" @enter="currentPage = 'editor'" />
    <EditorPage v-else-if="currentPage === 'editor'" />
    <OptimizePage v-else-if="currentPage === 'optimize'" />
    <ProviderSettingsPage v-else />
    </div>
  </n-config-provider>
</template>

<style scoped>
.app-shell {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--app-bg);
}

.app-header {
  flex: none;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 30px;
  padding: 0 22px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
  z-index: 10;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}
.brand-name {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.01em;
  color: var(--text);
}

/* 页面栏：下划线式导航，不用胶囊底、不用投影 */
.page-tabs {
  display: flex;
  align-items: stretch;
  gap: 24px;
  height: 100%;
}
.page-tab {
  position: relative;
  flex: none;
  padding: 0;
  border: none;
  background: transparent;
  font-size: 13px;
  white-space: nowrap;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 0.16s var(--ease);
}
.page-tab::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
  transition: background 0.16s var(--ease);
}
.page-tab:hover {
  color: var(--text);
}
.page-tab.active {
  color: var(--text);
  font-weight: 600;
}
.page-tab.active::after {
  background: var(--primary);
}

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 2px;
}
/* 触发器包装：给 ref 一个原生元素（n-button 的实例没有 contains） */
.trigger-wrap {
  display: inline-flex;
}
/* GitHub 跳转图标：内联 SVG 1.1em，hover 加深，去掉链接下划线 */
.github-link {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  margin-right: 6px;
  color: var(--text-tertiary);
  text-decoration: none;
  font-size: 1.05em;
  transition: color 0.2s var(--ease);
}
.github-link:hover {
  color: var(--text);
}

/* ---------- 窄屏：页面栏可横向滚动，标题与操作保持单行 ---------- */
@media (max-width: 720px) {
  .app-header {
    gap: 14px;
    padding: 0 14px;
  }
  .page-tabs {
    flex: 1;
    min-width: 0;
    gap: 18px;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }
  .page-tabs::-webkit-scrollbar {
    display: none;
  }
  .page-tab::after {
    bottom: 0;
  }
  .header-actions {
    flex: none;
  }
}
@media (max-width: 560px) {
  .brand-name,
  .github-link {
    display: none;
  }
  /* 两行：品牌 + 操作在上，页面栏独占一行（四个入口不再横向裁切） */
  .app-header {
    flex-wrap: wrap;
    height: auto;
    min-height: 56px;
    gap: 10px;
    padding: 5px 14px 0;
  }
  .page-tabs {
    order: 3;
    flex-basis: 100%;
    height: 40px;
    justify-content: space-between;
    gap: 0;
  }
}
</style>
