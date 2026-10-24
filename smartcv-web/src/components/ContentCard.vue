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
import { computed, nextTick, ref, type CSSProperties } from 'vue'
import { useResumeStore } from '@/stores/resume'
import { message } from '@/utils/feedback'
import { polishTexts, type PolishMode } from '@/api/polish'
import { ICON_GROUPS, LIST_TEXT_ICON } from '@/data/icons'
import { useClickPopover } from '@/composables/useClickPopover'
import { CONTENT_TYPE_NAMES } from '@/utils/constants'
import type { Content, ContentData, Section, LayoutWindow, ContentType } from '@/types'
import StylePopover from './StylePopover.vue'
import TagInput from './TagInput.vue'
import { onMarkdownKeydown } from '@/utils/textShortcuts'

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
 * 点卡片上的类型标签（图标 + 类型名）就在弹窗里编辑内容 —— 空间充足，输入框不会被压扁。
 * 卡片里不再单独放「▸ 展开」按钮：它占地方，而且点类型标签本来就能展开。
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
  listText: LIST_TEXT_ICON,
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

/* ---------- 列表项拖动排序（原生 HTML5 drag，不依赖外部库） ---------- */

/** 正在拖的项下标 / 当前悬停的目标行下标 */
const dragIndex = ref<number | null>(null)
const dragOverIndex = ref<number | null>(null)

function onDragStart(index: number, e: DragEvent) {
  dragIndex.value = index
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    // Firefox 要求必须 setData 才会真正开始拖动
    e.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(index: number, e: DragEvent) {
  if (dragIndex.value === null) return
  e.preventDefault() // 允许 drop
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  dragOverIndex.value = index
}

/** 松手：把拖动的项移到目标行所在的位置 */
function onDrop(index: number) {
  const from = dragIndex.value
  dragIndex.value = null
  dragOverIndex.value = null
  if (from === null || from === index) return
  const items = listItems.value.map((it) => ({ ...it }))
  const [moved] = items.splice(from, 1)
  items.splice(index, 0, moved)
  saveListItems(items)
}

function onDragEnd() {
  dragIndex.value = null
  dragOverIndex.value = null
}

/* ---------- 润色（listText / iconText 类型会显示按钮） ---------- */

/**
 * 点「润色」先展开一个思路输入区（而不是直接发请求）：
 * 用户可以写一句润色思路再「发送」，也可以什么都不写直接「发送」，
 * 点「取消」则收起输入区，不发任何请求。
 */
const polishShow = ref(false)
/** 用户填的润色描述/思路（可为空，空串时后端按默认规则润色） */
const polishDescription = ref('')
const polishInputRef = ref<{ focus: () => void } | null>(null)

/**
 * 润色模式（后端按它选用不同的系统提示词）：
 *  - strict 严谨（默认）：规则锁死，只优化表达，不改变原文内容
 *  - free   自由：像直接问 AI，由模型自主判断怎么写最好，并优先遵循用户思路
 * 选择刻意不随「取消」重置——用户下次打开通常还是想用上次那个模式。
 */
/** 卡片润色只提供这两档；enhance 是「优化简历」输入框的提示词增强，不在这里选 */
type ContentPolishMode = 'strict' | 'free'
const polishMode = ref<ContentPolishMode>('strict')
/** 每个模式的一句话说明，直接展示给用户，避免只看到名字猜不出差别 */
const POLISH_MODE_HINTS: Record<ContentPolishMode, string> = {
  strict: '严格按规则改写，只优化表达，不改变原文内容',
  free: '像直接问 AI 一样自由发挥，可大幅重写、补充数据',
}
/** 思路输入框的提示语：自由模式鼓励写具体要求；不写就让模型自由发挥 */
const polishPlaceholder = computed(() =>
  polishMode.value === 'free'
    ? '写下你的润色要求，不写则由 AI 自由发挥'
    : '输入你想润色的思路，可以不写',
)

/** 当前内容是否有可润色的文字（一个字没写就别润色了） */
const polishable = computed(() =>
  props.content.type === 'iconText'
    ? Boolean(textModel.value?.trim())
    : listItems.value.some((it) => it.text.trim()),
)

/** 点「润色」：展开思路输入区并聚焦输入框（没内容则先提示，不展开） */
function openPolish() {
  if (!polishable.value) {
    message.warning('先写点内容再润色吧')
    return
  }
  polishShow.value = true
  nextTick(() => polishInputRef.value?.focus())
}

/** 取消：收起输入区，清空已填思路，不发请求 */
function cancelPolish() {
  polishShow.value = false
  polishDescription.value = ''
}

/** 发送：带着用户填的思路（可为空）与所选模式发起润色；列表型/图标文字型各走各的写回逻辑 */
async function sendPolish() {
  const description = polishDescription.value.trim()
  // 先取出模式：cancelPolish 会清空描述，但模式要保留
  const mode = polishMode.value
  cancelPolish()
  // 输入区开着期间内容被清空了：静默返回（openPolish 已提示过，不再打扰）
  if (!polishable.value) return
  if (props.content.type === 'iconText') await polishIconText(description, mode)
  else await polishList(description, mode)
}

/** 列表文字型：批量润色，按输入顺序写回，保留每条原有缩进 */
async function polishList(description: string, mode: PolishMode) {
  const items = listItems.value
  const texts = items.map((it) => it.text)
  const loading = message.loading('正在润色…', { duration: 0 })
  try {
    const polished = await polishTexts(texts, description, mode)
    // 模型返回少了/空了就保留原文
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
async function polishIconText(description: string, mode: PolishMode) {
  const orig = textModel.value ?? ''
  const loading = message.loading('正在润色…', { duration: 0 })
  try {
    const polished = await polishTexts([orig], description, mode)
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
    <!-- 拖拽手柄：按住拖动排序 / 移到其他窗口（vue-draggable-plus） -->
    <span class="content-drag-handle" title="按住拖动排序 / 移到其他窗口">
      ⋮⋮
    </span>

    <!-- 类型标签：图标 + 类型名。点它 = 展开编辑弹窗（悬停提示说明这一点）；
         卡片被挤窄时只留图标，点击区域仍然覆盖整条标签 -->
    <button
      class="content-label"
      :title="`点击展开编辑 · ${CONTENT_TYPE_NAMES[content.type]}`"
      @click.stop="openEdit"
    >
      <span class="content-type-icon" v-html="TYPE_ICONS[content.type]" />
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
            <n-button size="small" quaternary type="error" block @click="onRemove">删除</n-button>
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
          <n-button size="tiny" quaternary type="warning" @click.stop="openPolish">
            润色
          </n-button>
        </div>
        <!-- 润色思路输入区：点「润色」展开，写不写思路都能发送；取消则收起、不发请求 -->
        <div v-if="polishShow" class="polish-input">
          <!-- 模式切换 + 一句话说明：让用户一眼看出两档的差别 -->
          <n-radio-group v-model:value="polishMode" size="small">
            <n-radio-button value="strict">严谨</n-radio-button>
            <n-radio-button value="free">自由</n-radio-button>
          </n-radio-group>
          <div class="polish-mode-hint">{{ POLISH_MODE_HINTS[polishMode] }}</div>
          <n-input
            ref="polishInputRef"
            v-model:value="polishDescription"
            size="small"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            :placeholder="polishPlaceholder"
            @keydown.enter.exact.prevent="sendPolish"
          />
          <div class="polish-input-actions">
            <n-button size="tiny" type="primary" @click.stop="sendPolish">发送</n-button>
            <n-button size="tiny" quaternary @click.stop="cancelPolish">取消</n-button>
          </div>
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
            placeholder="文字（支持 Markdown；选中后 Ctrl+B 加粗）"
            @keydown="onMarkdownKeydown"
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
              :placeholder="`第 ${i + 1} 栏文字（Ctrl+B 加粗）`"
              @update:value="(v: string) => setColumn(i, v)"
              @keydown="onMarkdownKeydown"
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
          <n-button size="tiny" quaternary type="warning" @click.stop="openPolish">
            润色
          </n-button>
        </div>
        <!-- 润色思路输入区：点「润色」展开，写不写思路都能发送；取消则收起、不发请求 -->
        <div v-if="polishShow" class="polish-input">
          <!-- 模式切换 + 一句话说明：让用户一眼看出两档的差别 -->
          <n-radio-group v-model:value="polishMode" size="small">
            <n-radio-button value="strict">严谨</n-radio-button>
            <n-radio-button value="free">自由</n-radio-button>
          </n-radio-group>
          <div class="polish-mode-hint">{{ POLISH_MODE_HINTS[polishMode] }}</div>
          <n-input
            ref="polishInputRef"
            v-model:value="polishDescription"
            size="small"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            :placeholder="polishPlaceholder"
            @keydown.enter.exact.prevent="sendPolish"
          />
          <div class="polish-input-actions">
            <n-button size="tiny" type="primary" @click.stop="sendPolish">发送</n-button>
            <n-button size="tiny" quaternary @click.stop="cancelPolish">取消</n-button>
          </div>
        </div>
        <div class="list-items">
          <div
            v-for="(item, i) in listItems"
            :key="i"
            class="list-item-edit"
            :class="{ dragging: dragIndex === i, 'drag-over': dragOverIndex === i && dragIndex !== i }"
            :style="{ paddingLeft: `${(item.indent ?? 0) * INDENT_STEP}px` }"
            @dragover="onDragOver(i, $event)"
            @drop.prevent="onDrop(i)"
          >
            <!-- 拖拽手柄：按住上下拖，松手插到目标行位置 -->
            <span
              class="list-item-drag"
              draggable="true"
              title="按住拖动调整列表项顺序"
              @dragstart="onDragStart(i, $event)"
              @dragend="onDragEnd"
            >
              ⋮⋮
            </span>
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
              placeholder="列表内容（支持 Markdown；选中后 Ctrl+B 加粗）"
              @update:value="(v: string) => setItem(i, v)"
              @keydown="onMarkdownKeydown"
            />
            <n-button size="tiny" quaternary type="error" @click.stop="removeItem(i)">✕</n-button>
          </div>
        </div>
        <n-button size="tiny" quaternary type="primary" @click.stop="addItem">＋ 添加一项</n-button>
      </template>
    </div>
    <template #footer>
      <div class="modal-footer">
        <!-- 加粗只在支持 Markdown 的文本类型里有意义，其它类型不显示提示 -->
        <span
          v-if="content.type === 'iconText' || content.type === 'twoColumn' || content.type === 'listText'"
          class="modal-shortcut-hint"
        >
          选中文字后 <kbd>Ctrl</kbd>+<kbd>B</kbd> 加粗
        </span>
        <n-button size="small" type="primary" @click="editShow = false">完成</n-button>
      </div>
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
  background: var(--panel-bg);
  /* 编辑画布是"操作面板"，文字固定小字号，不跟随内容字号放大（放大效果只在预览区体现） */
  font-size: 14px;
  /* 新插入的内容出现时播放一次淡入动画（按 key 挂载的 DOM 只有新内容会播放） */
  animation: cardAppear 0.25s ease-out;
  /* 选中/悬停用内阴影画边框，不占布局空间（保证和预览高度一致） */
  box-shadow: inset 0 0 0 1px transparent;
  transition: box-shadow 0.15s;
  /* 卡片自身作为容器：宽度被挤窄（横排里放多块）时，按自己的真实宽度切换成"只显示图标"。
     用卡片而不是画布做容器 —— 同一行里每块宽度可能都不一样。 */
  container-type: inline-size;
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
  box-shadow: inset 0 0 0 1px var(--border-strong);
}
.content-card.selected {
  box-shadow: inset 0 0 0 1.5px var(--primary);
  background: var(--primary-faint);
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
  background: var(--primary-soft);
}
.content-type-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
/* 内联 SVG 类型图标（如「列表文字」）：与 emoji 同样按字号缩放 */
.content-type-icon :deep(svg) {
  display: block;
  width: 1em;
  height: 1em;
}
.content-type-name {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ============================================================
 * 压缩模式：卡片自身宽度不够时只显示类型图标
 *
 * 阈值的由来：图标 13px + 间距 6 + 「列表文字」4×13 ≈ 71px，
 * 加上左右内边距、⋮⋮ 手柄和 ⋯ 按钮约 61px → 约 132px 才放得下名字。
 * 卡片再窄就只留图标（仍可点击展开编辑，悬停提示会说明类型）。
 * 展开按钮已删除，所以图标就是唯一入口，点击区域撑满剩余宽度。
 * ============================================================ */
@container (max-width: 140px) {
  .content-label {
    justify-content: center;
    padding: 0 2px;
  }
  .content-type-name {
    display: none;
  }
}

/* 拖拽手柄：默认半透明，悬停卡片时显示 */
.content-drag-handle {
  flex: none;
  align-self: stretch;
  display: flex;
  align-items: center;
  cursor: grab;
  color: var(--text-tertiary);
  font-size: 13px;
  letter-spacing: 1px;
  padding: 0 4px;
  border-radius: 4px;
  user-select: none;
}
.content-drag-handle:hover {
  background: var(--primary-soft);
  color: var(--text-secondary);
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

/* 弹窗底部：左侧快捷键提示，右侧「完成」 */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.modal-shortcut-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.modal-shortcut-hint kbd {
  display: inline-block;
  min-width: 16px;
  margin: 0 2px;
  padding: 1px 5px;
  font-family: inherit;
  font-size: 10.5px;
  line-height: 1.5;
  text-align: center;
  color: var(--text-secondary);
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 4px;
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
  color: var(--text-secondary);
}

/* 润色思路输入区：浅色底 + 虚线边框，和工具栏区分开（虚线暗示"可选填"） */
.polish-input {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px dashed rgba(166, 118, 63, 0.34);
  border-radius: 6px;
  background: var(--warning-soft);
}
/* 模式说明小字：告诉用户当前这档到底做什么（只看到「严谨/深度」猜不出差别） */
.polish-mode-hint {
  font-size: 12px;
  line-height: 1.5;
  color: var(--warning);
}
.polish-input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
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
  border: 1px solid var(--border);
  border-radius: 4px;
}
.image-placeholder {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 48px;
  border-radius: 8px;
  border: 1px dashed var(--border-strong);
  background: var(--surface-soft);
  color: var(--text-tertiary);
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
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-bg);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: border-color 0.15s var(--ease);
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
  border-color: var(--border-strong);
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 14px;
}

/* 占位组件编辑区：只有一个小标记，不显示任何文字/放大效果 */
.spacer-editor {
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-tertiary);
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
  color: var(--text-tertiary);
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
  background: var(--primary-soft);
}
.icon-cell.active {
  background: var(--primary-soft);
  border-color: var(--primary);
}

/* 分栏 / 时间段里的分隔符 */
.editor-divider {
  align-self: center;
  color: var(--text-tertiary);
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
  color: var(--text-tertiary);
}
.column-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
.column-sep-label {
  flex: none;
  font-size: 12px;
  color: var(--text-secondary);
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
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  border-radius: 4px;
  transition: opacity 0.12s;
}
.list-item-edit :deep(.n-input) {
  flex: 1;
}
/* 拖动中的行变淡；目标位置在行上方画一条主题色指示线 */
.list-item-edit.dragging {
  opacity: 0.4;
}
.list-item-edit.drag-over::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: -4px;
  height: 2px;
  border-radius: 2px;
  background: var(--primary);
}
.list-item-drag {
  flex: none;
  color: var(--text-tertiary);
  line-height: 26px;
  font-size: 12px;
  letter-spacing: 1px;
  cursor: grab;
  user-select: none;
}
.list-item-drag:active {
  cursor: grabbing;
}
.list-marker {
  flex: none;
  color: var(--text-secondary);
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
  color: var(--text-secondary);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s var(--ease);
}
.content-more-btn:hover {
  background: var(--primary-soft);
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
  color: var(--text-secondary);
}
.more-option-row :deep(.n-slider) {
  flex: 1;
}
.more-option-value {
  flex: none;
  width: 40px;
  text-align: right;
  font-size: 12px;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
</style>
