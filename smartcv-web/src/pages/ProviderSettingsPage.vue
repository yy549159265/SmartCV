<script setup lang="ts">
/**
 * 页面 4 · 高级设置
 *
 * 左侧标签页：
 *   1. OpenAI 设置：配置「优化简历」对话用的模型供应商（localStorage，useStorage 持久化）；
 *   2. 提示词预览：只读展示后端 agent 用的提示词（prompts）与技能（skills）md，
 *      按 Markdown 排版渲染（只读，不可更改）。
 */
import { computed, reactive, ref } from 'vue'
import { useStorage } from '@vueuse/core'
import { message } from '@/utils/feedback'
import { getAgentMd, type AgentMdFile, type AgentMdPayload } from '@/api/agent'
import { renderMarkdown } from '@/utils/markdown'
import IconGlyph from '@/components/IconGlyph.vue'

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

/* ---------- 提示词预览：拉取后端提示词 + 技能（只读） ---------- */
const md = ref<AgentMdPayload>({ prompts: [], skills: [] })
const selected = ref<AgentMdFile | null>(null)
const mdLoaded = ref(false)
const loading = ref(false)

/** 技能文档开头常带 YAML 元信息（name / description），只作为文件属性，不参与正文渲染 */
function stripFrontmatter(src: string): string {
  return src.replace(/^---\r?\n[\s\S]*?\r?\n-{3,}\s*(?:\r?\n|$)/, '')
}

/** 当前文件的 Markdown 渲染结果（经过 markdown-it 转义，防 XSS） */
const mdHtml = computed(() =>
  renderMarkdown(stripFrontmatter(selected.value?.content ?? '')),
)

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
  <main class="settings-page">
    <div class="settings-shell">
      <div class="settings-grid">
        <!-- 左侧：设置项导航 -->
        <aside class="settings-nav">
          <div class="nav-caption">配置项</div>
          <button
            class="nav-item"
            :class="{ active: tab === 'provider' }"
            @click="tab = 'provider'"
          >
            <span class="nav-icon"><IconGlyph name="sliders-horizontal" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">OpenAI 设置</span>
              <span class="nav-hint">接口地址与模型</span>
            </span>
          </button>
          <button class="nav-item" :class="{ active: tab === 'md' }" @click="openMd">
            <span class="nav-icon"><IconGlyph name="book-open" :size="16" /></span>
            <span class="nav-copy">
              <span class="nav-label">提示词预览</span>
              <span class="nav-hint">提示词与技能文档</span>
            </span>
          </button>
        </aside>

        <!-- 右侧：设置内容（切换标签时轻入场） -->
        <section :key="tab" class="settings-panel">
          <!-- 标签 1 · OpenAI 设置 -->
          <template v-if="tab === 'provider'">
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">OpenAI 设置</h2>
                <p class="panel-desc">
                  支持任何兼容 OpenAI 格式的接口地址与模型名。保存后，优化对话与提示词增强都会使用这里的配置。
                </p>
              </div>
              <span class="panel-badge">
                <span class="badge-dot" aria-hidden="true"></span>
                OpenAI 兼容
              </span>
            </div>

            <div class="form">
              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">接口地址</span>
                  <span class="field-hint">Base URL，需兼容 OpenAI 接口格式</span>
                </div>
                <div class="field-control">
                  <n-input
                    v-model:value="draft.baseUrl"
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
              </div>

              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">API Key</span>
                  <span class="field-hint">只写入当前浏览器，不会上传到其他服务</span>
                </div>
                <div class="field-control">
                  <n-input
                    v-model:value="draft.apiKey"
                    type="password"
                    show-password-on="click"
                    placeholder="sk-..."
                  />
                </div>
              </div>

              <div class="field-row">
                <div class="field-info">
                  <span class="field-label">模型名称</span>
                  <span class="field-hint">例如 gpt-4o-mini、gpt-4.1</span>
                </div>
                <div class="field-control">
                  <n-input v-model:value="draft.model" placeholder="gpt-4o-mini" />
                </div>
              </div>
            </div>

            <footer class="panel-foot">
              <p class="foot-note">配置保存后立即生效，并按当前浏览器分别保存。</p>
              <div class="foot-actions">
                <n-button size="small" quaternary @click="onTest">测试连接</n-button>
                <n-button size="small" type="primary" @click="onSave">保存设置</n-button>
              </div>
            </footer>
          </template>

          <!-- 标签 2 · 提示词预览（只读，Markdown 渲染） -->
          <template v-else>
            <div class="panel-head">
              <div class="panel-head-copy">
                <h2 class="panel-title">提示词预览</h2>
                <p class="panel-desc">
                  只读展示后端 Agent 加载的提示词与技能文档，内容按 Markdown 排版渲染。
                </p>
              </div>
              <span class="panel-badge">
                <IconGlyph name="shield-check" :size="13" />
                只读
              </span>
            </div>

            <div class="md-layout">
              <!-- 文件列表：提示词 / 技能 两组 -->
              <aside class="md-list">
                <template v-if="loading">
                  <span v-for="i in 5" :key="i" class="sk sk-item"></span>
                </template>
                <template v-else>
                  <div class="md-group">
                    <span>提示词</span>
                    <span class="md-count">{{ md.prompts.length }}</span>
                  </div>
                  <button
                    v-for="(f, i) in md.prompts"
                    :key="'p' + i"
                    class="md-item"
                    :class="{ active: selected === f }"
                    @click="selected = f"
                  >
                    <IconGlyph name="file-text" :size="14" class="md-item-icon" />
                    <span class="md-item-name">{{ f.name }}</span>
                  </button>

                  <div class="md-group">
                    <span>技能</span>
                    <span class="md-count">{{ md.skills.length }}</span>
                  </div>
                  <button
                    v-for="(f, i) in md.skills"
                    :key="'s' + i"
                    class="md-item"
                    :class="{ active: selected === f }"
                    @click="selected = f"
                  >
                    <IconGlyph name="file-text" :size="14" class="md-item-icon" />
                    <span class="md-item-name">{{ f.name }}</span>
                  </button>
                </template>
              </aside>

              <!-- 文档区 -->
              <div class="md-viewer">
                <div class="md-viewer-head">
                  <span class="md-path">{{ selected?.path || '未选择文件' }}</span>
                  <span v-if="selected" class="md-type">Markdown</span>
                </div>

                <div v-if="loading" class="md-doc">
                  <div class="doc-skeleton">
                    <span class="sk sk-title"></span>
                    <span v-for="i in 6" :key="i" class="sk sk-line" :class="{ short: i % 3 === 0 }"></span>
                  </div>
                </div>
                <div v-else-if="selected" class="md-doc">
                  <div class="md-doc-inner" v-html="mdHtml"></div>
                </div>
                <div v-else class="md-empty">
                  <span class="md-empty-icon"><IconGlyph name="file-text" :size="20" /></span>
                  <p class="md-empty-text">选择左侧文件查看内容</p>
                </div>
              </div>
            </div>
          </template>
        </section>
      </div>
    </div>
  </main>
</template>

<style scoped>
/* ---------- 页面骨架 ---------- */
.settings-page {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--app-bg);
}
.settings-shell {
  max-width: 1560px;
  margin: 0 auto;
  padding: 24px 28px 56px;
}

/* ---------- 两栏：导航 + 内容 ---------- */
.settings-grid {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  animation: settings-rise 0.32s var(--ease) 0.04s both;
}
.settings-nav {
  flex: none;
  width: 230px;
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.03);
}
.nav-caption {
  padding: 8px 10px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.nav-item:hover {
  background: var(--surface-soft);
}
.nav-item.active {
  background: var(--primary-soft);
}
/* 选中项左侧一道短竖线：比整块高亮更克制 */
.nav-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 2px;
  border-radius: 2px;
  background: transparent;
  transition: background 0.16s var(--ease);
}
.nav-item.active::before {
  background: var(--primary);
}
.nav-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.nav-item:hover .nav-icon {
  color: var(--text-secondary);
}
.nav-item.active .nav-icon {
  background: var(--panel-bg);
  color: var(--primary);
}
.nav-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.nav-label {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  color: var(--text-secondary);
}
.nav-item.active .nav-label {
  color: var(--primary-hover);
  font-weight: 600;
}
.nav-hint {
  font-size: 11px;
  line-height: 1.4;
  color: var(--text-tertiary);
}
.nav-item.active .nav-hint {
  color: var(--primary);
  opacity: 0.66;
}

/* ---------- 内容面板 ---------- */
.settings-panel {
  flex: 1;
  min-width: 0;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.03);
  overflow: hidden;
  animation: panel-in 0.24s var(--ease) both;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.panel-head-copy {
  flex: 1 1 240px;
  min-width: 0;
}
.panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.panel-desc {
  margin: 5px 0 0;
  max-width: 620px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-tertiary);
}
.panel-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--primary-faint);
  border: 1px solid var(--primary-soft);
  font-size: 11px;
  font-weight: 500;
  color: var(--primary-hover);
  white-space: nowrap;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

/* ---------- OpenAI 设置表单：左标签 + 右控件，发丝线分隔 ---------- */
.form {
  padding: 0 22px;
}
.field-row {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
  padding: 16px 0;
  border-bottom: 1px solid var(--border);
}
.field-row:last-child {
  border-bottom: none;
}
.field-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding-top: 7px;
}
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.field-hint {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.field-control {
  min-width: 0;
  max-width: 880px;
}
.field-control :deep(.n-input) {
  background: var(--surface-soft);
  border-radius: 9px;
  transition:
    background-color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.field-control :deep(.n-input:hover) {
  background: var(--panel-bg);
}
.field-control :deep(.n-input--focus) {
  background: var(--panel-bg);
  box-shadow: 0 0 0 3px rgba(71, 83, 199, 0.1);
}

.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 22px;
  border-top: 1px solid var(--border);
  background: var(--surface-soft);
}
.foot-note {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

/* ---------- 提示词预览 ---------- */
.md-layout {
  display: flex;
  height: calc(100vh - 300px);
  min-height: 380px;
  max-height: 760px;
}
.md-list {
  flex: none;
  width: 236px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px;
  overflow: auto;
  background: var(--surface-soft);
  border-right: 1px solid var(--border);
}
.md-group {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 9px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.md-group:first-of-type {
  padding-top: 4px;
}
.md-count {
  font-weight: 500;
  color: var(--text-tertiary);
}
.md-item {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 7px 9px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.md-item:hover {
  background: var(--panel-bg);
}
.md-item.active {
  background: var(--panel-bg);
  box-shadow:
    0 1px 2px rgba(28, 33, 48, 0.05),
    0 6px 16px -12px rgba(28, 33, 48, 0.28);
}
.md-item-icon {
  flex: none;
  color: var(--text-tertiary);
  transition: color 0.16s var(--ease);
}
.md-item.active .md-item-icon {
  color: var(--primary);
}
.md-item-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-secondary);
}
.md-item.active .md-item-name {
  color: var(--primary-hover);
  font-weight: 600;
}

.md-viewer {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
}
.md-viewer-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border);
}
.md-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--surface-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: var(--text-secondary);
}
.md-type {
  margin-left: auto;
  flex: none;
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.md-doc {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 28px 40px 56px;
}
.md-doc-inner {
  max-width: 820px;
  margin: 0 auto;
}

/* Markdown 排版：标题、正文、列表、代码、引用、表格 */
.md-doc-inner :deep(h1),
.md-doc-inner :deep(h2),
.md-doc-inner :deep(h3),
.md-doc-inner :deep(h4) {
  color: var(--text);
  line-height: 1.35;
}
.md-doc-inner :deep(h1) {
  margin: 0 0 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.md-doc-inner :deep(h2) {
  margin: 28px 0 10px;
  font-size: 16px;
  font-weight: 600;
}
.md-doc-inner :deep(h3) {
  margin: 22px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.md-doc-inner :deep(h4) {
  margin: 18px 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
.md-doc-inner :deep(p) {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.85;
  color: var(--text-secondary);
}
.md-doc-inner :deep(ul),
.md-doc-inner :deep(ol) {
  margin: 6px 0 14px;
  padding-left: 1.45em;
}
.md-doc-inner :deep(li) {
  margin: 4px 0;
  line-height: 1.75;
  color: var(--text-secondary);
}
.md-doc-inner :deep(li::marker) {
  color: var(--text-tertiary);
}
.md-doc-inner :deep(strong) {
  font-weight: 600;
  color: var(--text);
}
.md-doc-inner :deep(a) {
  color: var(--primary);
  text-decoration: none;
  border-bottom: 1px solid rgba(71, 83, 199, 0.25);
  transition: border-color 0.16s var(--ease);
}
.md-doc-inner :deep(a:hover) {
  border-bottom-color: var(--primary);
}
.md-doc-inner :deep(code) {
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--surface-soft);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.88em;
  color: var(--primary-hover);
}
.md-doc-inner :deep(pre) {
  margin: 10px 0 16px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
  overflow: auto;
}
.md-doc-inner :deep(pre.hljs) {
  background: var(--surface-soft);
}
.md-doc-inner :deep(pre code) {
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text);
}
.md-doc-inner :deep(blockquote) {
  margin: 12px 0 16px;
  padding: 10px 14px;
  border-left: 3px solid var(--primary);
  border-radius: 0 8px 8px 0;
  background: var(--primary-faint);
  color: var(--text-secondary);
}
.md-doc-inner :deep(blockquote p:last-child) {
  margin-bottom: 0;
}
.md-doc-inner :deep(table) {
  width: 100%;
  margin: 10px 0 18px;
  border-collapse: collapse;
  font-size: 12px;
}
.md-doc-inner :deep(th),
.md-doc-inner :deep(td) {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.md-doc-inner :deep(th) {
  background: var(--surface-soft);
  font-weight: 600;
  color: var(--text);
}
.md-doc-inner :deep(td) {
  color: var(--text-secondary);
}
.md-doc-inner :deep(hr) {
  margin: 24px 0;
  border: none;
  border-top: 1px solid var(--border);
}
.md-doc-inner :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}

.md-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-tertiary);
}
.md-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
}
.md-empty-text {
  margin: 0;
  font-size: 12.5px;
}

/* 加载骨架：列表条目 + 文档行 */
.sk {
  display: block;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--surface-sunken) 25%,
    var(--surface-soft) 37%,
    var(--surface-sunken) 63%
  );
  background-size: 400% 100%;
  animation: sk-shimmer 1.4s ease infinite;
}
.sk-item {
  height: 28px;
  margin-bottom: 6px;
}
.doc-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 780px;
  margin: 0 auto;
}
.sk-title {
  width: 42%;
  height: 24px;
  margin-bottom: 8px;
}
.sk-line {
  width: 100%;
  height: 12px;
}
.sk-line.short {
  width: 64%;
}

/* ---------- 动效 ---------- */
@keyframes settings-rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes panel-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@keyframes sk-shimmer {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}

/* ---------- 窄屏 ---------- */
@media (max-width: 920px) {
  .settings-shell {
    padding: 20px 16px 44px;
  }
  .settings-grid {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .settings-panel {
    width: 100%;
  }
  .settings-nav {
    position: static;
    width: 100%;
    flex-direction: row;
    gap: 4px;
    overflow-x: auto;
  }
  .nav-caption {
    display: none;
  }
  .nav-item {
    flex: 1 0 176px;
    width: auto;
  }
  .field-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }
  .field-info {
    padding-top: 0;
  }
  .md-layout {
    height: calc(100vh - 340px);
    min-height: 360px;
  }
}
@media (max-width: 760px) {
  .md-layout {
    flex-direction: column;
    height: auto;
    max-height: none;
  }
  .md-viewer {
    flex: none;
    height: 62vh;
    min-height: 360px;
  }
  .md-list {
    flex-direction: row;
    align-items: center;
    width: 100%;
    overflow-x: auto;
    padding: 10px 12px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .md-group {
    display: none;
  }
  .md-item {
    flex: none;
    width: auto;
    max-width: 220px;
    padding: 6px 11px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--panel-bg);
  }
  .md-item.active {
    border-color: var(--primary-soft);
    background: var(--primary-soft);
    box-shadow: none;
  }
  .md-doc {
    padding: 20px 20px 40px;
  }
}
</style>
