<script setup lang="ts">
import { ref } from 'vue'
import { siGithub } from 'simple-icons'
import HomePage from '@/pages/HomePage.vue'
import EditorPage from '@/pages/EditorPage.vue'
import ReviewPage from '@/pages/ReviewPage.vue'
import InterviewPage from '@/pages/InterviewPage.vue'
import MarketInsightsPage from '@/pages/MarketInsightsPage.vue'
import ReferenceExamplesPage from '@/pages/ReferenceExamplesPage.vue'
import ProviderSettingsPage from '@/pages/ProviderSettingsPage.vue'
import { brandSvg } from '@/data/icons'
import { themeOverrides } from '@/styles/naive-theme'

const githubSvg = brandSvg(siGithub)

type PageKey =
  | 'home'
  | 'editor'
  | 'review'
  | 'interview'
  | 'market'
  | 'references'
  | 'provider'

const currentPage = ref<PageKey>('home')

const settingsTab = ref<'provider' | 'backup' | 'market' | 'interview' | 'md'>('provider')

function onNav(page: PageKey) {
  if (page === 'provider') settingsTab.value = 'provider'
  currentPage.value = page
}

function openBackupSettings() {
  settingsTab.value = 'backup'
  currentPage.value = 'provider'
}

const examplePrefillJson = ref('')

function onConvertToExample(json: string) {
  examplePrefillJson.value = json
  currentPage.value = 'references'
}

const PAGES: { key: PageKey; label: string }[] = [
  { key: 'home', label: '主页' },
  { key: 'editor', label: '编辑简历' },
  { key: 'review', label: '优化简历' },
  { key: 'interview', label: '模拟面试' },
  { key: 'market', label: '市场洞察' },
  { key: 'references', label: '优秀示例' },
  { key: 'provider', label: '高级设置' },
]
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <div class="app-shell">
      <header class="app-header">
        <div class="brand">
          <img class="brand-icon" src="/favicon.svg" alt="" width="24" height="24" />
          <span class="brand-name">SmartCV</span>
        </div>

        <nav class="page-tabs" aria-label="主导航">
          <button
            v-for="p in PAGES"
            :key="p.key"
            class="page-tab"
            :class="{ active: currentPage === p.key }"
            :aria-current="currentPage === p.key ? 'page' : undefined"
            @click="onNav(p.key)"
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

    <!--
      市场洞察跑的是 SSE 长连接，组件销毁就等于断开连接、本轮调研被后端取消。
      只把这一页放进 keep-alive：切到其它页签时组件实例保留，调研继续在后台跑，
      切回来结果和进度都还在；其它页面照旧每次进入重建。
    -->
    <div class="app-view">
      <KeepAlive include="MarketInsightsPage">
        <HomePage v-if="currentPage === 'home'" @enter="currentPage = 'editor'" />
        <EditorPage
          v-else-if="currentPage === 'editor'"
          @open-settings="openBackupSettings"
        />
        <ReviewPage
          v-else-if="currentPage === 'review'"
          @open-library="currentPage = 'references'"
          @convert-to-example="onConvertToExample"
        />
        <InterviewPage
          v-else-if="currentPage === 'interview'"
          @navigate="currentPage = $event"
        />
        <MarketInsightsPage v-else-if="currentPage === 'market'" />
        <ReferenceExamplesPage
          v-else-if="currentPage === 'references'"
          :prefill-json="examplePrefillJson"
          @prefill-consumed="examplePrefillJson = ''"
        />
        <ProviderSettingsPage v-else :initial-tab="settingsTab" />
      </KeepAlive>
    </div>
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

.app-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.app-view > * {
  flex: 1;
  min-height: 0;
  animation: view-in var(--dur-3) var(--ease-out) both;
}
@keyframes view-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.app-header {
  flex: none;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 0 24px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
  z-index: 10;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
  align-self: stretch;
  padding-right: 22px;
  border-right: 1px solid var(--border-faint);
}
.brand-icon {
  display: block;
  flex: none;
  width: 24px;
  height: 24px;
  border-radius: 6px;
}
.brand-name {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.005em;
  color: var(--text);
}

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
  padding: 0 13px;
  margin: 0 1px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    color var(--dur-2) var(--ease),
    background-color var(--dur-2) var(--ease);
}
.page-tab::after {
  content: '';
  position: absolute;
  left: 13px;
  right: 13px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--primary);
  transform: scaleX(0);
  transform-origin: center;
  transition: transform var(--dur-3) var(--ease-out);
}
.page-tab:hover {
  color: var(--text);
  background: var(--surface-soft);
}
.page-tab.active {
  color: var(--text);
  font-weight: 600;
  background: transparent;
}
.page-tab.active:hover {
  background: var(--surface-soft);
}
.page-tab.active::after {
  transform: scaleX(1);
}

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
}
.github-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  text-decoration: none;
  font-size: 1.05em;
  transition:
    color var(--dur-2) var(--ease),
    background-color var(--dur-2) var(--ease),
    transform var(--dur-1) var(--ease);
}
.github-link:hover {
  color: var(--text);
  background: var(--surface-soft);
}
.github-link:active {
  transform: translateY(1px);
}

@media (max-width: 720px) {
  .app-header {
    gap: 12px;
    padding: 0 14px;
  }
  .brand {
    padding-right: 14px;
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
  .brand {
    padding-right: 0;
    border-right: none;
  }
  .app-header {
    flex-wrap: wrap;
    height: auto;
    min-height: 56px;
    gap: 10px;
    padding: 6px 14px 0;
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
