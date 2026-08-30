<script setup lang="ts">
/**
 * 页面 4 · Agent 设置
 *
 * 左侧标签页：
 *   1. 供应商设置：配置「优化简历」对话用的模型供应商（localStorage，useStorage 持久化）；
 *   2. md预览：只读展示后端 agent 用的提示词（prompts）与技能（skills）md，分组查看，不可更改。
 */
import { reactive, ref } from 'vue'
import { useStorage } from '@vueuse/core'
import { message } from '@/utils/feedback'
import { getAgentMd, type AgentMdFile, type AgentMdPayload } from '@/api/agent'

const tab = ref<'provider' | 'md'>('provider')

/** 供应商配置（useStorage 自动记忆到 localStorage） */
const settings = useStorage('smartcv-provider-settings', {
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4o-mini',
})

/** 临时编辑副本（点保存才写回 localStorage） */
const draft = reactive({ ...settings.value })

function onSave() {
  settings.value = { ...draft }
  message.success('已保存（保存在浏览器本地）')
}

function onTest() {
  message.info('连接测试功能开发中：接入后端后即可使用')
}

/* ---------- md预览：拉取后端提示词 + 技能（只读） ---------- */
const md = ref<AgentMdPayload>({ prompts: [], skills: [] })
const selected = ref<AgentMdFile | null>(null)
const mdLoaded = ref(false)
const loading = ref(false)

async function openMd() {
  tab.value = 'md'
  if (mdLoaded.value || loading.value) return
  loading.value = true
  try {
    md.value = await getAgentMd()
    mdLoaded.value = true
    selected.value = md.value.prompts[0] ?? md.value.skills[0] ?? null
  } catch (err) {
    message.error(`加载失败：${err instanceof Error ? err.message : String(err)}`)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="agent-page">
    <!-- 左侧标签页 -->
    <aside class="agent-nav">
      <button
        class="nav-item"
        :class="{ active: tab === 'provider' }"
        @click="tab = 'provider'"
      >
        🔌 供应商设置
      </button>
      <button class="nav-item" :class="{ active: tab === 'md' }" @click="openMd">
        📄 md预览
      </button>
    </aside>

    <div class="agent-content">
      <!-- 标签 1 · 供应商设置 -->
      <template v-if="tab === 'provider'">
        <div class="provider-card">
          <h2 class="page-title">🔌 供应商设置</h2>
          <p class="page-desc">
            配置「优化简历」AI 对话使用的模型供应商。配置保存在浏览器本地，后端接入后生效
            （见 <code>src/api/chat.ts</code> 的接入说明）。
          </p>
          <p class="page-desc">仅支持 OpenAI 格式的接口地址与模型名。</p>

          <div class="form">
            <div class="form-row">
              <span class="form-label">接口地址</span>
              <n-input v-model:value="draft.baseUrl" placeholder="https://api.openai.com/v1" style="width: 380px" />
            </div>
            <div class="form-row">
              <span class="form-label">API Key</span>
              <n-input
                v-model:value="draft.apiKey"
                type="password"
                show-password-on="click"
                placeholder="sk-..."
                style="width: 380px"
              />
            </div>
            <div class="form-row">
              <span class="form-label">模型名称</span>
              <n-input v-model:value="draft.model" placeholder="gpt-4o-mini" style="width: 260px" />
            </div>

            <div class="form-actions">
              <n-button type="primary" size="small" @click="onSave">保存</n-button>
              <n-button size="small" quaternary @click="onTest">测试连接</n-button>
            </div>
          </div>
        </div>
      </template>

      <!-- 标签 2 · md预览（只读） -->
      <template v-else>
        <div class="md-layout">
          <div class="md-list">
            <div class="md-group">📝 提示词（prompts）</div>
            <button
              v-for="(f, i) in md.prompts"
              :key="'p' + i"
              class="md-item"
              :class="{ active: selected === f }"
              @click="selected = f"
            >
              {{ f.name }}
            </button>

            <div class="md-group">🧩 技能（skills）</div>
            <button
              v-for="(f, i) in md.skills"
              :key="'s' + i"
              class="md-item"
              :class="{ active: selected === f }"
              @click="selected = f"
            >
              {{ f.name }}
            </button>

            <div v-if="loading" class="md-loading">加载中…</div>
          </div>

          <div class="md-detail">
            <div class="md-detail-head">
              <span class="md-path">{{ selected?.path || '（未选择文件）' }}</span>
              <n-tag size="tiny" round :bordered="false" type="info">只读</n-tag>
            </div>
            <pre class="md-content">{{ selected?.content || '选择左侧文件查看内容' }}</pre>
          </div>
        </div>
      </template>
    </div>
  </main>
</template>

<style scoped>
.agent-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  padding: 16px;
  background: #eef0f4;
}

/* 左侧标签页 */
.agent-nav {
  flex: none;
  width: 148px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  padding: 8px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  font-size: 13px;
  color: #6b7280;
  text-align: left;
  cursor: pointer;
}
.nav-item:hover {
  background: #f1f3f7;
  color: #1f2937;
}
.nav-item.active {
  background: var(--primary);
  color: #fff;
  font-weight: 600;
}

/* 内容区 */
.agent-content {
  flex: 1;
  min-width: 0;
  overflow: auto;
}

/* 供应商设置卡片 */
.provider-card {
  max-width: 640px;
  margin: 0 auto;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  padding: 24px 28px;
}
.page-title {
  margin: 0 0 8px;
  font-size: 16px;
}
.page-desc {
  margin: 0 0 20px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.8;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.form-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.form-label {
  flex: none;
  width: 72px;
  font-size: 13px;
  color: #374151;
}
.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 6px;
}

/* md预览：左列表 + 右内容 */
.md-layout {
  display: flex;
  gap: 12px;
  height: 100%;
}
.md-list {
  flex: none;
  width: 220px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  padding: 10px;
  overflow: auto;
}
.md-group {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  padding: 8px 6px 4px;
}
.md-item {
  display: block;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 12px;
  color: #374151;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.md-item:hover {
  background: #f1f3f7;
}
.md-item.active {
  background: #eef2ff;
  color: var(--primary);
  font-weight: 600;
}
.md-loading {
  padding: 10px 6px;
  font-size: 12px;
  color: #9ca3af;
}
.md-detail {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}
.md-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid #f0f1f4;
}
.md-path {
  font-size: 12px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.md-content {
  flex: 1;
  margin: 0;
  padding: 14px 16px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  color: #1f2937;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fafbfc;
}
</style>
