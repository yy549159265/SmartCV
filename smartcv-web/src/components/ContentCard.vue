<script setup lang="ts">
/**
 * 内容的"编辑卡片"（中间画布用）
 *
 * 渲染同样完全按 content.type 驱动（与预设名无关），每个类型对应一套编辑控件：
 *  - iconText  → 图标输入框 + 文字输入框
 *  - twoColumn → 任意多栏 + 分隔符（各栏按内容宽度排列，紧挨分隔符）
 *  - timeRange → 开始 - 结束
 *  - tag       → 标签输入框（空格/回车/逗号 一次识别多个）
 *  - listText  → 圆点/数字切换 + 多条列表项 + 【润色按钮（仅此类型有）】
 *
 * 所有读写都通过 store（单一数据源），本组件不保存任何本地副本。
 */
import { computed, ref, type CSSProperties } from 'vue'
import { useResumeStore } from '@/stores/resume'
import { message } from '@/utils/feedback'
import { polishTexts } from '@/api/polish'
import { ICON_GROUPS } from '@/data/icons'
import { useClickPopover } from '@/composables/useClickPopover'
import { CONTENT_TYPE_NAMES } from '@/utils/constants'
import type { Content, ContentData, Section, LayoutWindow, ContentType } from '@/types'
import StylePopover from './StylePopover.vue'
import TagInput from './TagInput.vue'

const props = defineProps<{
  section: Section
  /** 该内容所在的布局窗口（决定横向/竖向） */
  row: LayoutWindow
  content: Content
}>()
const store = useResumeStore()

/** 图标选择器弹层（受控，点外部自动关闭） */
const { show: iconPopoverShow, triggerRef: iconTriggerRef } = useClickPopover()
/** ⋯ 菜单弹层（受控，点外部自动关闭） */
const { show: moreShow, triggerRef: moreTriggerRef } = useClickPopover()

const isSelected = computed(() => store.selectedId === props.content.id)

/* ---------- 展开编辑弹窗 ---------- */

/**
 * 编辑方式：画布里的内容卡片永远只占一行（横向窗口里放很多块也不会挤），
 * 点「展开」在弹窗里编辑内容 —— 空间充足，输入框不会被压扁。
 */
const editShow = ref(false)

/** 弹窗标题：编辑内容 · 类型名 */
const modalTitle = computed(() => `编辑内容 · ${CONTENT_TYPE_NAMES[props.content.type]}`)

/** 卡片上显示的类型小图标（和组件库一致，一眼认出是什么类型） */
const TYPE_ICONS: Record<ContentType, string> = {
  iconText: '🅰️',
  twoColumn: '↔️',
  timeRange: '⏱️',
  tag: '🏷️',
  listText: '☰',
  image: '🖼️',
  spacer: '🫥',
}

/** 打开编辑弹窗 */
function openEdit() {
  store.select(props.content.id)
  editShow.value = true
}

/* ---------- 内容字段的双向绑定：读写都走 store ---------- */

function contentModel<K extends keyof ContentData>(key: K) {
  return computed({
    get: () => props.content.content[key],
    set: (v: ContentData[K]) =>
      store.updateContent(props.section.id, props.content.id, { content: { [key]: v } }),
  })
}

const iconModel = contentModel('icon')
const textModel = contentModel('text')
const columnsModel = contentModel('columns')
const separatorModel = contentModel('separator')
const startModel = contentModel('start')
const endModel = contentModel('end')
const tagsModel = contentModel('tags')
const listTypeModel = contentModel('listType')
const imageModel = contentModel('image')
const imageSizeModel = contentModel('imageSize')
const imageShapeModel = contentModel('imageShape')
const imageAlignModel = contentModel('imageAlign')

/** 编辑卡里的图片预览样式（圆形裁正方形；圆角/原图保持原比例） */
const imagePreviewStyle = computed<CSSProperties>(() => {
  const shape = props.content.content.imageShape === 'circle'
    ? 'circle'
    : props.content.content.imageShape === 'original'
      ? 'original'
      : 'rounded'
  return {
    width: '56px',
    ...(shape === 'circle' ? { height: '56px' } : {}),
    borderRadius: shape === 'circle' ? '50%' : shape === 'rounded' ? '8px' : '0px',
    objectFit: shape === 'circle' ? 'cover' : 'contain',
  }
})

/** 选择图标：写入内容并立即关闭选择器（选完就走，不用再点外面一下） */
function pickIcon(icon: string) {
  iconModel.value = icon
  iconPopoverShow.value = false
}

/* ---------- 图片型：上传 / 尺寸 / 清除 ---------- */

function onPickImage(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选同一张图
  if (!file) return
  if (!file.type.startsWith('image/')) {
    message.warning('请选择图片文件')
    return
  }
  // 压缩提示：太大的图先压到 400px 内再存（简历场景够用）
  const reader = new FileReader()
  reader.onload = () => {
    const img = new Image()
    img.onload = () => {
      const maxSize = 400
      let { width, height } = img
      if (width > maxSize || height > maxSize) {
        const scale = Math.min(maxSize / width, maxSize / height)
        width = Math.round(width * scale)
        height = Math.round(height * scale)
      }
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      canvas.getContext('2d')?.drawImage(img, 0, 0, width, height)
      imageModel.value = canvas.toDataURL('image/jpeg', 0.85)
    }
    img.src = String(reader.result)
  }
  reader.readAsDataURL(file)
}

function onClearImage() {
  imageModel.value = ''
}

/* ---------- 分栏型：增加 / 删除一栏（栏数任意，预览里每栏平均分配宽度） ---------- */

function addColumn() {
  columnsModel.value = [...(columnsModel.value ?? []), '']
}

function setColumn(index: number, value: string) {
  const cols = [...(columnsModel.value ?? [])]
  cols[index] = value
  columnsModel.value = cols
}

function removeColumn(index: number) {
  const cols = [...(columnsModel.value ?? [])]
  cols.splice(index, 1)
  columnsModel.value = cols
}

/* ---------- 列表文字型的列表项操作（数组元素不能直接用 v-model） ---------- */

/** 当前列表项（统一成 { text, indent } 对象形式，兼容旧数据里的纯字符串） */
const listItems = computed(() =>
  (props.content.content.items ?? []).map((item) =>
    typeof item === 'string' ? { text: item, indent: 0 } : { text: item.text ?? '', indent: item.indent ?? 0 },
  ),
)

/** 把列表项写回 store */
function saveListItems(items: { text: string; indent: number }[]) {
  store.updateContent(props.section.id, props.content.id, { content: { items } })
}

function setItem(index: number, value: string) {
  const items = listItems.value.map((it) => ({ ...it }))
  items[index].text = value
  saveListItems(items)
}

function addItem() {
  saveListItems([...listItems.value, { text: '', indent: 0 }])
}

function removeItem(index: number) {
  const items = [...listItems.value]
  items.splice(index, 1)
  saveListItems(items)
}

/** 缩进层级：每级 24px，最多两级 */
const INDENT_STEP = 24
const INDENT_MAX = 2

function indentItem(index: number, delta: 1 | -1) {
  const items = listItems.value.map((it) => ({ ...it }))
  const next = (items[index].indent ?? 0) + delta
  items[index].indent = Math.min(Math.max(next, 0), INDENT_MAX)
  saveListItems(items)
}

/* ---------- 润色（listText / iconText 类型会显示按钮） ---------- */

async function polish() {
  const items = listItems.value
  const texts = items.map((it) => it.text)
  if (!texts.some((t) => t.trim())) {
    message.warning('先写点内容再润色吧')
    return
  }
  const loading = message.loading('正在润色…', { duration: 0 })
  try {
    const polished = await polishTexts(texts)
    // 按输入顺序写回，保留每条原有缩进；模型返回少了/空了就保留原文
    saveListItems(
      texts.map((orig, i) => ({
        text: polished[i]?.trim() || orig,
        indent: items[i]?.indent ?? 0,
      })),
    )
    message.success('润色完成')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '润色失败')
  } finally {
    loading?.destroy()
  }
}

/** 图标文字型：润色单段文字（文字在 text 字段），复用同一 /api/polish 接口 */
async function polishIconText() {
  const orig = textModel.value ?? ''
  if (!orig.trim()) {
    message.warning('先写点内容再润色吧')
    return
  }
  const loading = message.loading('正在润色…', { duration: 0 })
  try {
    const polished = await polishTexts([orig])
    // 单条输入对应单条输出；模型返回空了就保留原文
    textModel.value = polished[0]?.trim() || orig
    message.success('润色完成')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '润色失败')
  } finally {
    loading?.destroy()
  }
}

/* ---------- 复制 / 删除 / 拖拽排序 ---------- */

function onDuplicate() {
  store.duplicateContent(props.section.id, props.content.id)
}

function onRemove() {
  store.removeContent(props.section.id, props.content.id)
  message.success('内容已删除')
}
</script>

<template>
  <div
    class="content-card"
    :class="{ selected: isSelected }"
    :data-content-id="content.id"
    @click.stop="store.select(content.id)"
  >
    <!-- 展开按钮：卡片永远只占一行（横向窗口里放再多块也不会挤），点它弹出编辑弹窗 -->
    <button class="expand-btn" title="展开内容，在弹窗里编辑内容" @click.stop="openEdit">
      ▸ 展开
    </button>

    <!-- 拖拽手柄：按住拖动排序 / 移到其他窗口（vue-draggable-plus） -->
    <span class="content-drag-handle" title="按住拖动排序 / 移到其他窗口">
      ⋮⋮
    </span>

    <!-- 类型标签：只显示「图标 + 类型名」，点它同样打开编辑弹窗 -->
    <button
      class="content-label"
      :title="`点击编辑${CONTENT_TYPE_NAMES[content.type]}`"
      @click.stop="openEdit"
    >
      <span class="content-type-icon">{{ TYPE_ICONS[content.type] }}</span>
      <span class="content-type-name">{{ CONTENT_TYPE_NAMES[content.type] }}</span>
    </button>

    <!-- ⋯ 更多操作菜单：样式 / 复制 / 删除（收进一个按钮，横向放多块时也不会被挤没） -->
    <div class="content-actions" @click.stop>
      <n-popover v-model:show="moreShow" trigger="click" placement="bottom-end" :width="300">
        <template #trigger>
          <button ref="moreTriggerRef" class="content-more-btn" title="样式 / 复制 / 删除">⋯</button>
        </template>
        <template #default>
          <!-- 图片组件没有通用样式（字号/颜色/行距等），⋯ 菜单里只显示图片选项 -->
          <template v-if="content.type !== 'image'">
            <StylePopover mode="content" :section-id="section.id" :content-id="content.id" />
            <n-divider style="margin: 10px 0" />
          </template>
          <div class="more-actions">
            <!-- 图片型专属：形状 + 尺寸（放在菜单里，横向拥挤时也能设置） -->
            <div v-if="content.type === 'image'" class="image-more-options">
              <div class="more-option-row">
                <span class="more-option-label">形状</span>
                <n-radio-group v-model:value="imageShapeModel" size="small">
                  <n-radio-button value="rounded">圆角</n-radio-button>
                  <n-radio-button value="circle">圆形</n-radio-button>
                  <n-radio-button value="original">原图</n-radio-button>
                </n-radio-group>
              </div>
              <div class="more-option-row">
                <span class="more-option-label">位置</span>
                <n-radio-group v-model:value="imageAlignModel" size="small">
                  <n-radio-button value="left">左</n-radio-button>
                  <n-radio-button value="center">中</n-radio-button>
                  <n-radio-button value="right">右</n-radio-button>
                </n-radio-group>
              </div>
              <div class="more-option-row">
                <span class="more-option-label">尺寸</span>
                <n-slider
                  :value="content.content.imageSize ?? 96"
                  :min="40"
                  :max="160"
                  :step="4"
                  :tooltip="false"
                  @update:value="(v: number) => (imageSizeModel = v)"
                />
                <span class="more-option-value">{{ content.content.imageSize ?? 96 }}px</span>
              </div>
            </div>
            <n-button size="small" quaternary block @click="onDuplicate">⧉ 复制</n-button>
            <n-button size="small" quaternary type="error" block @click="onRemove">🗑️ 删除</n-button>
          </div>
        </template>
      </n-popover>
    </div>
  </div>

  <!-- 展开编辑弹窗：内容编辑全部在弹窗里进行（空间充足，输入框不会被压扁） -->
  <n-modal
    v-model:show="editShow"
    preset="card"
    :title="modalTitle"
    :mask-closable="false"
    style="width: 560px; max-width: 92vw"
  >
    <div class="content-editor">
      <!-- 图标文字型：图标（点击弹出图标选择器）+ 文字 + 可选标签（跟在文字后面） -->
      <template v-if="content.type === 'iconText'">
        <div class="icontext-toolbar">
          <span class="editor-hint">图标文字内容</span>
          <n-button size="tiny" quaternary type="warning" @click.stop="polishIconText">
            ✨ 润色
          </n-button>
        </div>
        <div class="icontext-row">
          <n-popover v-model:show="iconPopoverShow" trigger="click" placement="bottom-start" :width="320">
            <template #trigger>
              <button
                ref="iconTriggerRef"
                class="icon-trigger"
                :class="{ empty: !content.content.icon }"
                :title="content.content.icon ? '点击更换图标' : '点击添加图标（留空则不显示图标）'"
              >
                <!-- 图标可能是 emoji，也可能是品牌 SVG（v-html 两种都能渲染） -->
                <span v-if="content.content.icon" class="icon-trigger-content" v-html="content.content.icon" />
                <span v-else>＋</span>
              </button>
            </template>
            <template #default>
              <div class="icon-picker">
                <!-- 按用途分组的常用图标 -->
                <div v-for="g in ICON_GROUPS" :key="g.name" class="icon-group">
                  <div class="icon-section-name">{{ g.name }}</div>
                  <div class="icon-grid">
                    <button
                      v-for="ic in g.icons"
                      :key="ic"
                      class="icon-cell"
                      :class="{ active: content.content.icon === ic }"
                      @click="pickIcon(ic)"
                    >
                      <!-- emoji / 品牌 SVG 都能渲染 -->
                      <span v-html="ic" />
                    </button>
                  </div>
                </div>
                <!-- 也可以手输任意 emoji -->
                <n-input
                  v-model:value="iconModel"
                  size="small"
                  placeholder="或输入任意 emoji / 留空则不显示图标"
                />
              </div>
            </template>
          </n-popover>
          <n-input
            v-model:value="textModel"
            size="small"
            type="textarea"
            :autosize="{ minRows: 1 }"
            placeholder="文字（支持 Markdown，如 **加粗**）"
          />
        </div>
        <TagInput v-model="tagsModel" />
      </template>

      <!-- 分栏型：任意多栏 + 分隔符（预览里每栏平均分配宽度） -->
      <template v-else-if="content.type === 'twoColumn'">
        <div class="column-editor">
          <div v-for="(col, i) in columnsModel ?? []" :key="i" class="column-row">
            <span class="column-index">{{ i + 1 }}</span>
            <n-input
              :value="col"
              size="small"
              :placeholder="`第 ${i + 1} 栏文字（支持 Markdown）`"
              @update:value="(v: string) => setColumn(i, v)"
            />
            <n-button
              size="tiny"
              quaternary
              type="error"
              title="删除这一栏"
              :disabled="(columnsModel ?? []).length <= 1"
              @click.stop="removeColumn(i)"
            >
              ✕
            </n-button>
          </div>
          <div class="column-footer">
            <n-button size="tiny" quaternary type="primary" @click.stop="addColumn">
              ＋ 添加一栏
            </n-button>
            <span class="column-sep-label">分隔符</span>
            <n-input
              v-model:value="separatorModel"
              size="tiny"
              class="column-sep-input"
              placeholder="|"
              title="栏与栏之间显示的分隔符，如 | 、· 或 /"
            />
          </div>
        </div>
      </template>

      <!-- 时间段型 -->
      <template v-else-if="content.type === 'timeRange'">
        <n-input v-model:value="startModel" size="small" placeholder="开始时间，如 2022.07" />
        <span class="editor-divider">-</span>
        <n-input v-model:value="endModel" size="small" placeholder="结束时间，如 至今" />
      </template>

      <!-- 标签型：一个输入框，空格/回车/逗号 一次识别多个标签 -->
      <template v-else-if="content.type === 'tag'">
        <TagInput v-model="tagsModel" />
      </template>

      <!-- 图片型：上传图片（头像等）；尺寸/形状在 ⋯ 菜单里设置 -->
      <template v-else-if="content.type === 'image'">
        <div class="image-editor">
          <img
            v-if="content.content.image"
            :src="content.content.image"
            class="image-preview"
            :style="imagePreviewStyle"
            alt="图片"
          />
          <div v-else class="image-placeholder">🖼️</div>
          <div class="image-controls">
            <n-button size="small" quaternary type="primary" @click.stop>
              {{ content.content.image ? '更换图片' : '上传图片' }}
              <input
                type="file"
                accept="image/*"
                class="image-file-input"
                @change="onPickImage"
              />
            </n-button>
            <n-button
              v-if="content.content.image"
              size="small"
              quaternary
              type="error"
              @click.stop="onClearImage"
            >
              清除
            </n-button>
          </div>
        </div>
      </template>

      <!-- 占位组件：纯空白（高度 = 正文字号 × 行距，效果只在预览区体现） -->
      <template v-else-if="content.type === 'spacer'">
        <div class="spacer-editor">🫥</div>
      </template>

      <!-- 列表文字型 -->
      <template v-else-if="content.type === 'listText'">
        <div class="list-toolbar">
          <n-radio-group v-model:value="listTypeModel" size="small">
            <n-radio-button value="bullet">圆点列表</n-radio-button>
            <n-radio-button value="ordered">数字列表</n-radio-button>
          </n-radio-group>
          <!-- 润色按钮：只有列表文字型提供 -->
          <n-button size="tiny" quaternary type="warning" @click.stop="polish">
            ✨ 润色
          </n-button>
        </div>
        <div class="list-items">
          <div v-for="(item, i) in listItems" :key="i" class="list-item-edit" :style="{ paddingLeft: `${(item.indent ?? 0) * INDENT_STEP}px` }">
            <span class="list-marker">
              {{ content.content.listType === 'ordered' ? `${i + 1}.` : '•' }}
            </span>
            <!-- 缩进：向左 / 向右各一级（最多两级），实现子条目效果 -->
            <n-button
              size="tiny"
              quaternary
              title="向左缩进一级"
              :disabled="(item.indent ?? 0) <= 0"
              @click.stop="indentItem(i, -1)"
            >
              ⇤
            </n-button>
            <n-button
              size="tiny"
              quaternary
              title="向右缩进一级（子条目）"
              :disabled="(item.indent ?? 0) >= INDENT_MAX"
              @click.stop="indentItem(i, 1)"
            >
              ⇥
            </n-button>
            <n-input
              :value="item.text"
              size="small"
              type="textarea"
              :autosize="{ minRows: 1 }"
              placeholder="列表内容（支持 Markdown）"
              @update:value="(v: string) => setItem(i, v)"
            />
            <n-button size="tiny" quaternary type="error" @click.stop="removeItem(i)">✕</n-button>
          </div>
        </div>
        <n-button size="tiny" quaternary type="primary" @click.stop="addItem">＋ 添加一项</n-button>
      </template>
    </div>
    <template #footer>
      <n-button size="small" type="primary" @click="editShow = false">完成</n-button>
    </template>
  </n-modal>
</template>

<style scoped>
.content-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 6px;
  background: #fff;
  /* 编辑画布是"操作面板"，文字固定小字号，不跟随内容字号放大（放大效果只在预览区体现） */
  font-size: 14px;
  /* 新插入的内容出现时播放一次淡入动画（按 key 挂载的 DOM 只有新内容会播放） */
  animation: cardAppear 0.25s ease-out;
  /* 选中/悬停用内阴影画边框，不占布局空间（保证和预览高度一致） */
  box-shadow: inset 0 0 0 1px transparent;
  transition: box-shadow 0.15s;
}
@keyframes cardAppear {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
.content-card:hover {
  box-shadow: inset 0 0 0 1px #d8dde6;
}
.content-card.selected {
  box-shadow: inset 0 0 0 1.5px var(--primary);
  background: #f5f8ff;
}

/* 展开按钮：打开编辑弹窗 */
.expand-btn {
  flex: none;
  height: 24px;
  padding: 0 8px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--primary);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s;
}
.expand-btn:hover {
  background: #e8edf5;
}

/* 类型标签：卡片的主体（图标 + 类型名，点它打开编辑弹窗） */
.content-label {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  padding: 0 6px;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s;
}
.content-label:hover {
  background: #eef3ff;
}
.content-type-icon {
  flex: none;
  font-size: 13px;
}
.content-type-name {
  flex: none;
  font-size: 13px;
  color: #4b5563;
  white-space: nowrap;
}

/* 拖拽手柄：默认半透明，悬停卡片时显示 */
.content-drag-handle {
  flex: none;
  align-self: stretch;
  display: flex;
  align-items: center;
  cursor: grab;
  color: #b6bdc9;
  font-size: 13px;
  letter-spacing: 1px;
  padding: 0 4px;
  border-radius: 4px;
  user-select: none;
}
.content-drag-handle:hover {
  background: #e8edf5;
  color: #5b6675;
}
.content-drag-handle:active {
  cursor: grabbing;
}

.content-editor {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 图标文字型：标志 + 润色按钮 */
.icontext-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.editor-hint {
  font-size: 12px;
  color: #6b7280;
}

/* 图标文字型：图标按钮 + 文字输入框 */
.icontext-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

/* 图片型编辑器 */
.image-editor {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.image-preview {
  flex: none;
  width: 56px;
  max-height: 72px;
  object-fit: contain;
  border: 1px solid #e2e6ee;
}
.image-placeholder {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 48px;
  border-radius: 8px;
  border: 1.5px dashed #d3dae6;
  background: #f7f9fc;
  font-size: 22px;
}
.image-controls {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.image-file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.image-controls :deep(.n-button) {
  position: relative;
  align-self: flex-start;
}
.icon-trigger {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 28px;
  border: 1px solid #d8dde6;
  border-radius: 6px;
  background: #fff;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: border-color 0.15s;
}
.icon-trigger:hover {
  border-color: var(--primary);
}
/* 品牌 SVG 图标：按按钮尺寸缩放（:deep 才能命中 v-html 插入的 svg） */
.icon-trigger :deep(svg) {
  width: 16px;
  height: 16px;
  display: block;
}
/* 没选图标时的空状态：虚线框 + 浅色 ＋，暗示"可以不填" */
.icon-trigger.empty {
  border-style: dashed;
  background: #f7f9fc;
  color: #b6bdc9;
  font-size: 14px;
}

/* 占位组件编辑区：只有一个小标记，不显示任何文字/放大效果 */
.spacer-editor {
  font-size: 14px;
  line-height: 1.5;
  color: #b6bdc9;
}

/* 图标选择器弹层 */
.icon-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
  padding: 2px;
}
.icon-section-name {
  font-size: 11px;
  color: #9ca3af;
  margin-bottom: 4px;
}
.icon-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.icon-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.12s,
    border-color 0.12s;
}
/* 品牌 SVG 图标：按格子尺寸缩放（:deep 才能命中 v-html 插入的 svg） */
.icon-cell :deep(svg) {
  width: 18px;
  height: 18px;
  display: block;
}
.icon-cell:hover {
  background: #eef3ff;
}
.icon-cell.active {
  background: #eef3ff;
  border-color: var(--primary);
}

/* 分栏 / 时间段里的分隔符 */
.editor-divider {
  align-self: center;
  color: #9ca3af;
  padding: 0 2px;
}

/* 分栏型：多栏编辑 */
.column-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.column-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.column-row :deep(.n-input) {
  flex: 1;
}
.column-index {
  flex: none;
  width: 16px;
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
}
.column-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
.column-sep-label {
  flex: none;
  font-size: 12px;
  color: #6b7280;
}
.column-sep-input {
  width: 72px;
}

/* 列表文字型 */
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.list-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.list-item-edit {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.list-item-edit :deep(.n-input) {
  flex: 1;
}
.list-marker {
  flex: none;
  color: #6b7280;
  line-height: 26px;
  width: 14px;
  text-align: center;
}

/* ⋯ 更多操作：默认隐藏，悬停/选中显示；只有一个按钮，窄卡片里也不会被挤没 */
.content-actions {
  flex: none;
  display: flex;
  align-items: flex-start;
  opacity: 0;
  transition: opacity 0.15s;
}
.content-card:hover .content-actions,
.content-card.selected .content-actions {
  opacity: 1;
}
.content-more-btn {
  width: 22px;
  height: 26px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #6b7280;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s;
}
.content-more-btn:hover {
  background: #e8edf5;
}

/* 菜单里的操作按钮组 */
.more-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 图片型：⋯ 菜单里的形状/尺寸设置 */
.image-more-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 4px;
}
.more-option-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.more-option-label {
  flex: none;
  width: 30px;
  font-size: 12px;
  color: #6b7280;
}
.more-option-row :deep(.n-slider) {
  flex: 1;
}
.more-option-value {
  flex: none;
  width: 40px;
  text-align: right;
  font-size: 12px;
  color: #374151;
  font-variant-numeric: tabular-nums;
}
</style>
