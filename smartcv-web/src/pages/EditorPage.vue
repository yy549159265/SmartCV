<script setup lang="ts">
/**
 * 页面 1 · 编辑简历：顶部工具栏 + 两栏布局（宽度可拖动调整）
 *   左：组件库（ComponentLibrary，横向面板）+ 编辑画布（EditCanvas）
 *   右：实时预览（ResumePreview）
 *
 * 顶部工具栏：简历名字、撤销/重做、预览缩放、纸面宽度。
 * 列宽：两栏之间有一条分隔条（ColumnDivider），按住左右拖动改变列宽；
 * 双击恢复默认，宽度用 VueUse 的 useStorage 记忆在浏览器本地。
 * 两栏读写的是同一个 Pinia store（stores/resume.ts）—— 单一数据源。
 */
import { computed, ref, watch, watchEffect } from 'vue'
import { useStorage, useWindowSize } from '@vueuse/core'
import ComponentLibrary from '@/components/ComponentLibrary.vue'
import EditCanvas from '@/components/EditCanvas.vue'
import ResumePreview from '@/components/ResumePreview.vue'
import ColumnDivider from '@/components/ColumnDivider.vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { previewZoom, ZOOM_LEVELS } from '@/composables/usePreviewZoom'
import {
  PAGE_WIDTH_MAX,
  PAGE_WIDTH_MIN,
  PAGE_WIDTH_PRESETS,
  pageHeight,
  pageWidth,
} from '@/composables/usePageSize'
import { resumeName } from '@/composables/useResumeName'
import { useResumeStore } from '@/stores/resume'
import { useDocumentsStore } from '@/stores/documents'
import { supportsDirectoryPicker } from '@/utils/fs/directoryHandle'
import { formatRelativeTime } from '@/utils/time'
import { sanitizeFileTitle } from '@/utils/filename'
import { dialog, message } from '@/utils/feedback'

const emit = defineEmits<{ 'open-settings': [] }>()

const store = useResumeStore()
const documents = useDocumentsStore()
/** 浏览器是否支持选择文件夹（Chrome / Edge） */
const supportsFolder = supportsDirectoryPicker()

/* ---------- 左列宽度（useStorage：自动记忆到 localStorage） ---------- */

const DEFAULTS = { editor: 640 }
const LIMITS = { editor: { min: 440, max: 1200 } }

const editorWidth = useStorage('smartcv-layout-editor', DEFAULTS.editor)

/** 把宽度变化限制在合理范围内 */
function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function onResizeEditor(dx: number) {
  editorWidth.value = clamp(editorWidth.value + dx, LIMITS.editor.min, LIMITS.editor.max)
}
function onResetEditor() {
  editorWidth.value = DEFAULTS.editor
}

/* ---------- 窗口变窄时自动收缩编辑列（只缩不放，用户拖过的宽度永远优先） ---------- */

const { width: viewportWidth } = useWindowSize()

watchEffect(() => {
  // 给预览至少留 480px；窗口更窄时按最小编辑列宽处理
  const max = viewportWidth.value - 480
  if (max < editorWidth.value) {
    editorWidth.value = Math.max(LIMITS.editor.min, max)
  }
})

/** 两栏布局样式：左列固定宽度，预览弹性占满剩余空间 */
const mainStyle = computed(() => ({
  gridTemplateColumns: `${editorWidth.value}px 8px minmax(0, 1fr)`,
}))

/* ---------- 顶部工具栏 ---------- */

/** 撤销/重做是否可用（看两个历史栈） */
const canUndo = computed(() => store.undoStack.length > 0)
const canRedo = computed(() => store.redoStack.length > 0)

/** 纸面宽度弹层是否展开 */
const widthMenuShow = ref(false)

/* ---------- 简历库（备份文件夹） ---------- */

/** 简历库弹层是否展开 */
const libraryShow = ref(false)

/** 简历名字输入框的本地草稿：失焦 / 回车时才提交，避免每敲一个字就改文件名 */
const nameDraft = ref(resumeName.value)
watch(resumeName, (value) => {
  nameDraft.value = value
})

const librarySubtitle = computed(() => {
  switch (documents.status) {
    case 'unsupported':
      return '当前浏览器不支持文件夹'
    case 'unbound':
      return '尚未选择文件夹'
    case 'needs-permission':
      return '需要授权后才能读取'
    case 'denied':
      return '文件夹权限被拒绝'
    case 'ready':
      return `${documents.files.length} 份简历`
    default:
      return ''
  }
})

/** 列表里的文件是否是当前正在编辑的那份 */
function isCurrentFile(name: string): boolean {
  return documents.currentFile?.toLowerCase() === name.toLowerCase()
}

function onNameInput(event: Event) {
  nameDraft.value = (event.target as HTMLInputElement).value
}

function onNameEnter(event: KeyboardEvent) {
  ;(event.target as HTMLInputElement).blur()
}

/** 重名时问用户：保留两份 / 覆盖 / 取消 */
function askRenameConflict(conflict: string): Promise<'unique' | 'overwrite' | 'cancel'> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (value: 'unique' | 'overwrite' | 'cancel') => {
      if (settled) return
      settled = true
      resolve(value)
    }
    dialog.warning({
      title: '文件夹里已有同名简历',
      content: `「${conflict}」已经存在。保留两份会自动加序号；覆盖会替换原文件。`,
      positiveText: '保留两份',
      negativeText: '覆盖原文件',
      onPositiveClick: () => finish('unique'),
      onNegativeClick: () => finish('overwrite'),
      onClose: () => finish('cancel'),
      onMaskClick: () => finish('cancel'),
    })
  })
}

/** 提交简历名字：改名会同步重命名备份文件夹里的 JSON */
async function commitResumeName() {
  const clean = sanitizeFileTitle(nameDraft.value, '我的简历')
  nameDraft.value = clean
  if (clean === resumeName.value) return

  const previous = resumeName.value

  // 文件已存在但权限过期：先在用户的这次操作里申请权限，否则改名只会改显示名
  if (documents.isBound && documents.currentFile && documents.status !== 'ready') {
    const granted = await documents.ensurePermission()
    if (!granted) {
      message.warning('没有备份文件夹权限，名字暂未修改；请先在简历库里授权')
      nameDraft.value = previous
      return
    }
    await documents.refreshFiles()
  }

  const result = await documents.renameCurrent(clean)
  if (result.ok) return

  if (!result.conflict) {
    resumeName.value = previous
    nameDraft.value = previous
    return
  }

  const choice = await askRenameConflict(result.conflict)
  if (choice === 'cancel') {
    // renameCurrent 已经把显示名改成新名字了，这里恢复旧名字（旧文件本身没动）
    await documents.renameCurrent(previous)
    nameDraft.value = resumeName.value
    return
  }

  const retry = await documents.renameCurrent(clean, { conflict: choice })
  if (!retry.ok) {
    await documents.renameCurrent(previous)
    nameDraft.value = resumeName.value
  }
}

watch(libraryShow, (show) => {
  if (show) void documents.refreshIfReady()
})

async function onOpenFile(name: string) {
  if (isCurrentFile(name)) {
    libraryShow.value = false
    return
  }
  const ok = await documents.openFile(name)
  if (ok) libraryShow.value = false
}

async function onNewDocument() {
  const result = await documents.createBlank()
  if (result === 'ok') {
    nameDraft.value = resumeName.value
    libraryShow.value = false
  }
}

async function onRefreshLibrary() {
  await documents.refreshFiles()
  if (documents.status === 'ready') message.success('列表已刷新')
}

async function onBindFromLibrary() {
  const ok = await documents.bindFolder()
  if (ok) message.success(`已连接备份文件夹：${documents.folderName}`)
}

async function onAuthorizeFromLibrary() {
  const ok = await documents.ensurePermission()
  if (ok) {
    await documents.refreshFiles()
    message.success('已获得文件夹读写权限')
  } else {
    message.warning('未获得文件夹权限，请在浏览器提示中允许后重试')
  }
}

function openBackupSettings() {
  libraryShow.value = false
  emit('open-settings')
}
</script>

<template>
  <main class="editor-page">
    <!-- 顶部工具栏：简历名字 + 撤销/重做 + 预览缩放 + 纸面宽度 -->
    <header class="editor-toolbar">
      <div class="editor-name-box">
        <span class="editor-name-label">简历名字：</span>
        <input
          class="editor-name"
          :value="nameDraft"
          placeholder="给简历起个名字"
          title="简历名字：备份文件夹里的 JSON 与导出的 PDF 都会以这个名字命名"
          @input="onNameInput"
          @blur="commitResumeName"
          @keydown.enter="onNameEnter"
        />
        <!-- 简历库：列出备份文件夹里的所有 JSON，点一下切换编辑 -->
        <n-popover
          v-model:show="libraryShow"
          trigger="click"
          placement="bottom-start"
          :width="320"
        >
          <template #trigger>
            <button
              type="button"
              class="editor-library-btn"
              :class="{ bound: documents.isBound, open: libraryShow }"
              title="简历库：切换备份文件夹里的简历"
            >
              <IconGlyph name="folder" :size="14" />
              <span v-if="documents.files.length" class="editor-library-count">
                {{ documents.files.length }}
              </span>
              <IconGlyph name="chevron-down" :size="11" />
            </button>
          </template>

          <div class="library-menu">
            <div class="library-head">
              <div class="library-head-copy">
                <span class="library-title">{{ documents.folderName || '简历库' }}</span>
                <span class="library-sub">{{ librarySubtitle }}</span>
              </div>
              <button
                v-if="documents.status === 'ready'"
                type="button"
                class="library-icon-btn"
                title="刷新列表"
                @click="onRefreshLibrary"
              >
                <IconGlyph name="refresh-cw" :size="13" />
              </button>
            </div>

            <!-- 还没选文件夹 -->
            <div v-if="!documents.isBound" class="library-empty">
              <span class="library-empty-icon"><IconGlyph name="folder-open" :size="18" /></span>
              <p class="library-empty-title">把简历存进电脑文件夹</p>
              <p class="library-empty-text">
                选择文件夹后，每一份 JSON 就是一份简历，点一下即可切换编辑。
              </p>
              <n-button v-if="supportsFolder" size="small" type="primary" @click="onBindFromLibrary">
                选择文件夹
              </n-button>
              <p v-else class="library-empty-text">请使用 Chrome 或 Edge 浏览器。</p>
            </div>

            <!-- 选过文件夹但权限过期 -->
            <div v-else-if="documents.status !== 'ready'" class="library-empty">
              <span class="library-empty-icon"><IconGlyph name="folder" :size="18" /></span>
              <p class="library-empty-title">
                {{ documents.status === 'denied' ? '文件夹权限被拒绝' : '需要授权才能读取' }}
              </p>
              <p class="library-empty-text">
                浏览器会在重新打开页面后收回文件夹权限，授权一次即可继续。
              </p>
              <n-button size="small" type="primary" @click="onAuthorizeFromLibrary">
                授权访问
              </n-button>
            </div>

            <!-- 文件列表 -->
            <template v-else>
              <div class="library-list">
                <button
                  v-for="file in documents.files"
                  :key="file.name"
                  type="button"
                  class="library-item"
                  :class="{ active: isCurrentFile(file.name) }"
                  @click="onOpenFile(file.name)"
                >
                  <span class="library-item-icon">
                    <IconGlyph :name="isCurrentFile(file.name) ? 'file-text' : 'file-json'" :size="14" />
                  </span>
                  <span class="library-item-copy">
                    <span class="library-item-name">{{ file.title }}</span>
                    <span class="library-item-meta">{{ formatRelativeTime(file.mtime) }}</span>
                  </span>
                  <IconGlyph v-if="isCurrentFile(file.name)" name="check" :size="13" class="library-item-check" />
                </button>

                <div v-if="!documents.files.length" class="library-empty">
                  <p class="library-empty-title">文件夹里还没有 JSON</p>
                  <p class="library-empty-text">新建一份空白简历，或把已有 JSON 复制进这个文件夹。</p>
                </div>
              </div>

              <div class="library-foot">
                <button type="button" class="library-foot-btn" @click="onNewDocument">
                  <IconGlyph name="plus" :size="13" />
                  新建空白
                </button>
                <button type="button" class="library-foot-btn" @click="openBackupSettings">
                  <IconGlyph name="sliders-horizontal" :size="13" />
                  备份设置
                </button>
              </div>
            </template>
          </div>
        </n-popover>
      </div>

      <span class="editor-toolbar-spacer" />

      <div class="editor-history">
        <button class="editor-tool-btn" :disabled="!canUndo" title="撤销（Ctrl+Z）" @click="store.undo()">
          <IconGlyph name="undo-2" :size="14" />
        </button>
        <button class="editor-tool-btn" :disabled="!canRedo" title="重做（Ctrl+Shift+Z）" @click="store.redo()">
          <IconGlyph name="redo-2" :size="14" />
        </button>
      </div>

      <span class="editor-toolbar-divider" />

      <!-- 预览缩放（与诊断页共用 previewZoom，两边始终一致） -->
      <div class="editor-zoom">
        <button
          v-for="z in ZOOM_LEVELS"
          :key="z"
          class="editor-zoom-btn"
          :class="{ active: previewZoom === z }"
          @click="previewZoom = z"
        >
          {{ Math.round(z * 100) }}%
        </button>
      </div>

      <span class="editor-toolbar-divider" />

      <!-- 纸面宽度：简历成品的页面宽度（快捷档 + 滑块），预览与导出 PDF 同步生效 -->
      <n-popover v-model:show="widthMenuShow" trigger="click" placement="bottom-end" :width="272">
        <template #trigger>
          <button
            type="button"
            class="editor-width-btn"
            :class="{ open: widthMenuShow }"
            :aria-expanded="widthMenuShow"
            title="纸面宽度：预览与导出 PDF 的页面宽度"
          >
            <IconGlyph name="scan-line" :size="13" />
            <span class="editor-width-text">纸面 {{ pageWidth }}×{{ pageHeight }}</span>
            <IconGlyph name="chevron-down" :size="12" />
          </button>
        </template>
        <div class="width-menu">
          <div class="width-menu-label">纸面宽度：预览与导出 PDF 同步生效</div>
          <div class="width-presets">
            <button
              v-for="p in PAGE_WIDTH_PRESETS"
              :key="p.value"
              type="button"
              class="width-preset"
              :class="{ active: pageWidth === p.value }"
              @click="pageWidth = p.value"
            >
              <span class="width-preset-name">{{ p.label }}</span>
              <span class="width-preset-value">{{ p.size }}</span>
            </button>
          </div>
          <div class="width-slider-row">
            <n-slider
              v-model:value="pageWidth"
              class="width-slider"
              :min="PAGE_WIDTH_MIN"
              :max="PAGE_WIDTH_MAX"
              :step="10"
              :tooltip="false"
            />
            <span class="width-slider-value">{{ pageWidth }}×{{ pageHeight }}</span>
          </div>
        </div>
      </n-popover>
    </header>

    <!-- 两栏：左（组件库 + 画布）｜ 分隔条 ｜ 右（实时预览） -->
    <div class="editor-columns" :style="mainStyle">
      <div class="editor-left">
        <ComponentLibrary />
        <EditCanvas />
      </div>
      <ColumnDivider @resize="onResizeEditor" @reset="onResetEditor" />
      <ResumePreview />
    </div>
  </main>
</template>

<style scoped>
.editor-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* ============================================================
 * 顶部工具栏
 * ============================================================ */
.editor-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 44px;
  padding: 0 14px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
}

/* 简历名字：固定标签 + 输入框，空的时候也不会显得"空白一块" */
.editor-name-box {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.editor-name-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
}
.editor-name {
  width: 170px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  padding: 4px 8px;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease);
}
.editor-name:hover {
  background: var(--surface-soft);
}
.editor-name:focus {
  border-color: var(--primary);
  background: var(--panel-bg);
  outline: none;
  box-shadow: 0 0 0 2px rgba(71, 83, 199, 0.12);
}

/* 简历库入口：文件夹图标 + 文件数，紧跟在名字输入框后面 */
.editor-library-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex: none;
  height: 26px;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    border-color 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-library-btn:hover,
.editor-library-btn.open {
  background: var(--surface-soft);
  color: var(--text-secondary);
}
.editor-library-btn.bound {
  color: var(--primary);
}
.editor-library-count {
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--primary-soft);
  font-size: 10px;
  font-weight: 600;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  color: var(--primary-hover);
}

/* ---- 简历库弹层 ---- */
.library-menu {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.library-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.library-head-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.library-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.library-sub {
  font-size: 11px;
  color: var(--text-tertiary);
}
.library-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.library-icon-btn:hover {
  background: var(--surface-soft);
  color: var(--text);
}
.library-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 300px;
  overflow: auto;
  margin: 0 -4px;
  padding: 2px 4px;
}
.library-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 7px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease);
}
.library-item:hover {
  background: var(--surface-soft);
}
.library-item.active {
  background: var(--primary-faint);
}
.library-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
}
.library-item.active .library-item-icon {
  background: var(--panel-bg);
  color: var(--primary);
}
.library-item-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.library-item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.library-item.active .library-item-name {
  font-weight: 600;
  color: var(--primary-hover);
}
.library-item-meta {
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.library-item-check {
  flex: none;
  color: var(--primary);
}
.library-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  padding: 18px 14px;
  text-align: center;
}
.library-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: var(--surface-soft);
  color: var(--text-tertiary);
}
.library-empty-title {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
}
.library-empty-text {
  margin: 0;
  max-width: 230px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.library-foot {
  display: flex;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.library-foot-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  flex: 1;
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--panel-bg);
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    border-color 0.14s var(--ease),
    color 0.14s var(--ease);
}
.library-foot-btn:hover {
  border-color: var(--primary);
  background: var(--primary-faint);
  color: var(--primary);
}

.editor-toolbar-spacer {
  flex: 1;
}

.editor-history {
  display: flex;
  gap: 4px;
}
.editor-tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    border-color 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-tool-btn:hover:not(:disabled) {
  background: var(--surface-soft);
  border-color: var(--border);
  color: var(--text);
}
.editor-tool-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.editor-toolbar-divider {
  flex: none;
  width: 1px;
  height: 18px;
  background: var(--border);
}

.editor-zoom {
  display: flex;
  gap: 2px;
  flex: none;
  padding: 2px;
  border-radius: 8px;
  background: var(--surface-soft);
}
.editor-zoom-btn {
  height: 24px;
  padding: 0 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-zoom-btn:hover {
  color: var(--text);
}
.editor-zoom-btn.active {
  background: var(--panel-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.08);
}

/* ---- 纸面宽度：触发按钮 ---- */
.editor-width-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  height: 24px;
  padding: 0 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.editor-width-btn:hover,
.editor-width-btn.open {
  background: var(--surface-soft);
  color: var(--text);
}
.editor-width-btn :deep(.icon-glyph) {
  color: var(--text-tertiary);
}
.editor-width-btn:hover :deep(.icon-glyph),
.editor-width-btn.open :deep(.icon-glyph) {
  color: var(--text-secondary);
}

/* ---- 纸面宽度：弹层 ---- */
.width-menu {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.width-menu-label {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-tertiary);
}
.width-presets {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.width-preset {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 7px 0 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-bg);
  cursor: pointer;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease);
}
.width-preset:hover {
  border-color: var(--primary);
}
.width-preset.active {
  border-color: var(--primary);
  background: var(--primary-faint);
}
.width-preset-name {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text);
}
.width-preset-value {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-tertiary);
}
.width-preset.active .width-preset-name,
.width-preset.active .width-preset-value {
  color: var(--primary);
}
.width-slider-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.width-slider {
  flex: 1;
  min-width: 0;
}
.width-slider-value {
  flex: none;
  width: 76px;
  text-align: right;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

/* ============================================================
 * 两栏布局
 * ============================================================ */
.editor-columns {
  flex: 1;
  min-height: 0;
  display: grid;
  /* 列：编辑区 | 分隔条 | 预览 —— 宽度由 JS 控制 */
  grid-template-columns: 640px 8px minmax(0, 1fr);
}
.editor-columns > * {
  min-width: 0;
  min-height: 0;
}

/* 左列：组件库在上、画布在下 */
.editor-left {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--border);
}

/* 窄屏：工具栏压缩名称宽度 */
@media (max-width: 760px) {
  .editor-name {
    width: 100px;
  }
}
</style>
