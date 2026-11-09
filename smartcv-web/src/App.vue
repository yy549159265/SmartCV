<script setup lang="ts">
import { ref } from 'vue'
import { siGithub } from 'simple-icons'
import HomePage from '@/pages/HomePage.vue'
import EditorPage from '@/pages/EditorPage.vue'
import ReviewPage from '@/pages/ReviewPage.vue'
import ReferenceExamplesPage from '@/pages/ReferenceExamplesPage.vue'
import ProviderSettingsPage from '@/pages/ProviderSettingsPage.vue'
import { brandSvg } from '@/data/icons'
import { themeOverrides } from '@/styles/naive-theme'

const githubSvg = brandSvg(siGithub)

type PageKey = 'home' | 'editor' | 'review' | 'references' | 'provider'

const currentPage = ref<PageKey>('home')

const settingsTab = ref<'provider' | 'backup' | 'md'>('provider')

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
  { key: 'references', label: '优秀示例' },
  { key: 'provider', label: '高级设置' },
]
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <div class="app-shell">
      <header class="app-header">
        <div class="brand">
          <img class="brand-icon" src="/favicon.svg" alt="" width="22" height="22" />
          <span class="brand-name">SmartCV</span>
        </div>

      <nav class="page-tabs">
        <button
          v-for="p in PAGES"
          :key="p.key"
          class="page-tab"
          :class="{ active: currentPage === p.key }"
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
    <ReferenceExamplesPage
      v-else-if="currentPage === 'references'"
      :prefill-json="examplePrefillJson"
      @prefill-consumed="examplePrefillJson = ''"
    />
    <ProviderSettingsPage v-else :initial-tab="settingsTab" />
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
