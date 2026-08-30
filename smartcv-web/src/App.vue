<script setup lang="ts">
/**
 * 应用入口：顶部工具条 + 页面
 *   主页（默认）/ 编辑简历 / 优化简历 / Agent 设置
 *
 * 简历的"从哪来"统一走主页（导入 PDF / 导入 JSON / 新建），编辑页不再提供导入入口。
 * 所有页面读写同一个 Pinia store（stores/resume.ts）—— 单一数据源。
 */
import { ref } from 'vue'
import HomePage from '@/pages/HomePage.vue'
import EditorPage from '@/pages/EditorPage.vue'
import OptimizePage from '@/pages/OptimizePage.vue'
import ProviderSettingsPage from '@/pages/ProviderSettingsPage.vue'
import { useResumeStore } from '@/stores/resume'
import { useClickPopover } from '@/composables/useClickPopover'
import { message } from '@/utils/feedback'

const store = useResumeStore()

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
  <div class="app-shell">
    <!-- 顶部工具条：品牌 + 页面栏 + 数据操作 -->
    <header class="app-header">
      <div class="brand">
        <span class="brand-icon">🧱</span>
        SmartCV
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
</template>

<style scoped>
.app-shell {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-header {
  flex: none;
  height: 52px;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid var(--border);
  z-index: 10;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: #1f2937;
}
.brand-icon {
  font-size: 18px;
}

/* 页面栏：主页 / 编辑 / 优化 / 设置 */
.page-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f1f3f7;
  border-radius: 8px;
  padding: 3px;
}
.page-tab {
  padding: 5px 16px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 13px;
  color: #6b7280;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}
.page-tab:hover {
  color: #1f2937;
}
.page-tab.active {
  background: #fff;
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}
/* 触发器包装：给 ref 一个原生元素（n-button 的实例没有 contains） */
.trigger-wrap {
  display: inline-flex;
}
</style>
