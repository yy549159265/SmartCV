<script setup lang="ts">
/**
 * 应用入口：顶部工具条 + 页面
 *   主页（默认）/ 编辑简历 / 优化简历 / 高级设置
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
import { brandSvg } from '@/data/icons'
import { themeOverrides } from '@/styles/naive-theme'

/** GitHub 仓库跳转图标（头部右侧，新标签打开） */
const githubSvg = brandSvg(siGithub)

/* ---------- 顶部页面栏 ---------- */

type PageKey = 'home' | 'editor' | 'optimize' | 'provider'

const currentPage = ref<PageKey>('home')

const PAGES: { key: PageKey; label: string }[] = [
  { key: 'home', label: '主页' },
  { key: 'editor', label: '编辑简历' },
  { key: 'optimize', label: '优化简历' },
  { key: 'provider', label: '高级设置' },
]
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <div class="app-shell">
      <!-- 顶部工具条：品牌 + 页面栏 + GitHub -->
      <header class="app-header">
        <div class="brand">
          <img class="brand-icon" src="/favicon.svg" alt="" width="22" height="22" />
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
.brand-icon {
  display: block;
  flex: none;
  width: 22px;
  height: 22px;
}
.brand-name {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.01em;
  color: var(--text);
}

/* 页面栏：下划线式导航，不用胶囊底、不用投影；hover 给一条全高的极浅色带 */
.page-tabs {
  display: flex;
  align-items: stretch;
  gap: 2px;
  height: 100%;
}
.page-tab {
  position: relative;
  flex: none;
  display: inline-flex;
  align-items: center;
  padding: 0 12px;
  margin: 0 2px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 13px;
  white-space: nowrap;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.page-tab::after {
  content: '';
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
  transition: background 0.16s var(--ease);
}
.page-tab:hover {
  color: var(--text);
  background: var(--surface-soft);
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
}
/* GitHub 跳转图标：内联 SVG 1.1em，hover 给一圈浅底，去掉链接下划线 */
.github-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  margin-right: 6px;
  border-radius: 7px;
  color: var(--text-tertiary);
  text-decoration: none;
  font-size: 1.05em;
  transition:
    color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.github-link:hover {
  color: var(--text);
  background: var(--surface-soft);
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
