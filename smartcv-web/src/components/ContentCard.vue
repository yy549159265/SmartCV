<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, type CSSProperties } from 'vue'
import { useResumeStore } from '@/stores/resume'
import { message } from '@/utils/feedback'
import { polishTexts, type PolishMode } from '@/api/polish'
import { ICON_GROUPS, LIST_TEXT_ICON } from '@/data/icons'
import { useClickPopover } from '@/composables/useClickPopover'
import { CONTENT_TYPE_NAMES } from '@/utils/constants'
import type { Content, ContentData, Section, LayoutWindow, ContentType } from '@/types'
import StylePopover from './StylePopover.vue'
import IconGlyph from './IconGlyph.vue'
import TagInput from './TagInput.vue'
import { onMarkdownKeydown } from '@/utils/textShortcuts'

const props = defineProps<{
  section: Section
  row: LayoutWindow
  content: Content
}>()
const store = useResumeStore()

const { show: iconPopoverShow, triggerRef: iconTriggerRef } = useClickPopover()
const { show: moreShow, triggerRef: moreTriggerRef } = useClickPopover()

const isSelected = computed(() => store.selectedId === props.content.id)

const editShow = ref(false)

const modalTitle = computed(() => `编辑内容 · ${CONTENT_TYPE_NAMES[props.content.type]}`)

const TYPE_ICONS: Record<ContentType, string> = {
  iconText: '🅰️',
  twoColumn: '↔️',
  timeRange: '⏱️',
  tag: '🏷️',
  listText: LIST_TEXT_ICON,
  image: '🖼️',
  spacer: '🫥',
}

function openEdit() {
  store.select(props.content.id)
  editShow.value = true
}

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

function pickIcon(icon: string) {
  iconModel.value = icon
  iconPopoverShow.value = false
}

function onPickImage(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    message.warning('请选择图片文件')
    return
  }
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

const listItems = computed(() =>
  (props.content.content.items ?? []).map((item) =>
    typeof item === 'string' ? { text: item, indent: 0 } : { text: item.text ?? '', indent: item.indent ?? 0 },
  ),
)

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
  if (polishShow.value) {
    polishTargets.value = polishTargets.value
      .filter((i) => i !== index)
      .map((i) => (i > index ? i - 1 : i))
  }
}

const INDENT_STEP = 24
const INDENT_MAX = 2

function indentItem(index: number, delta: 1 | -1) {
  const items = listItems.value.map((it) => ({ ...it }))
  const next = (items[index].indent ?? 0) + delta
  items[index].indent = Math.min(Math.max(next, 0), INDENT_MAX)
  saveListItems(items)
}

const dragIndex = ref<number | null>(null)
const dragOverIndex = ref<number | null>(null)

function onDragStart(index: number, e: DragEvent) {
  dragIndex.value = index
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(index: number, e: DragEvent) {
  if (dragIndex.value === null) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  dragOverIndex.value = index
}

function onDrop(index: number) {
  const from = dragIndex.value
  dragIndex.value = null
  dragOverIndex.value = null
  if (from === null || from === index) return
  const order = listItems.value.map((_, i) => i)
  const [movedOrder] = order.splice(from, 1)
  order.splice(index, 0, movedOrder)
  const items = listItems.value.map((it) => ({ ...it }))
  const [moved] = items.splice(from, 1)
  items.splice(index, 0, moved)
  saveListItems(items)
  if (polishShow.value && polishTargets.value.length) {
    const picked = new Set(polishTargets.value)
    polishTargets.value = order
      .map((oldIndex, newIndex) => (picked.has(oldIndex) ? newIndex : -1))
      .filter((i) => i >= 0)
  }
}

function onDragEnd() {
  dragIndex.value = null
  dragOverIndex.value = null
}

const polishShow = ref(false)
const polishing = ref(false)

const flashIndexes = ref<number[]>([])
const textFlash = ref(false)
const FLASH_MS = 1400
let flashTimer: number | undefined
let textFlashTimer: number | undefined

function flashList(indexes: number[]) {
  if (!indexes.length) return
  flashIndexes.value = []
  nextTick(() => {
    flashIndexes.value = indexes
    window.clearTimeout(flashTimer)
    flashTimer = window.setTimeout(() => (flashIndexes.value = []), FLASH_MS)
  })
}

function flashText() {
  textFlash.value = false
  nextTick(() => {
    textFlash.value = true
    window.clearTimeout(textFlashTimer)
    textFlashTimer = window.setTimeout(() => (textFlash.value = false), FLASH_MS)
  })
}

onBeforeUnmount(() => {
  window.clearTimeout(flashTimer)
  window.clearTimeout(textFlashTimer)
})

const polishDescription = ref('')
const polishInputRef = ref<{ focus: () => void } | null>(null)

type ContentPolishMode = 'strict' | 'free'
const polishMode = ref<ContentPolishMode>('strict')

const POLISH_MODES: { key: ContentPolishMode; label: string; hint: string }[] = [
  { key: 'strict', label: '严谨', hint: '只重构表达，保留原句式，不新增任何数据' },
  { key: 'free', label: '自由', hint: '可大幅重写、扩写、补充术语；不勾「补充量化数据」就不会编造数字' },
]

const POLISH_DIRECTIONS: { key: string; label: string; text: string }[] = [
  { key: 'impact', label: '突出成果', text: '突出成果与业务价值' },
  { key: 'tech', label: '技术深度', text: '突出技术深度与方案设计' },
  { key: 'terms', label: '专业术语', text: '补充行业术语，提升专业密度' },
  { key: 'concise', label: '精简表达', text: '压缩篇幅，去掉冗余修饰' },
  { key: 'quant', label: '补充量化数据', text: '允许补充量化数据（可用具体数值或 XX 占位）' },
]

const polishDirs = ref<string[]>([])

function togglePolishDir(key: string) {
  const i = polishDirs.value.indexOf(key)
  if (i >= 0) polishDirs.value.splice(i, 1)
  else polishDirs.value.push(key)
}

const polishPlaceholder = computed(() =>
  polishDirs.value.length > 0
    ? '可选：补充更具体的润色要求'
    : '可选：写点润色要求，不写则按默认规则处理',
)

const polishTargets = ref<number[]>([])

const polishableIndexes = computed(() =>
  listItems.value.reduce<number[]>((acc, it, i) => {
    if (it.text.trim()) acc.push(i)
    return acc
  }, []),
)

const selectedIndexes = computed(() =>
  polishTargets.value.filter((i) => polishableIndexes.value.includes(i)),
)

const allSelected = computed(
  () =>
    polishableIndexes.value.length > 0 &&
    selectedIndexes.value.length === polishableIndexes.value.length,
)

function toggleTarget(index: number) {
  if (!polishableIndexes.value.includes(index)) return
  const set = new Set(selectedIndexes.value)
  if (set.has(index)) set.delete(index)
  else set.add(index)
  polishTargets.value = [...set].sort((a, b) => a - b)
}

function toggleAllTargets() {
  polishTargets.value = allSelected.value ? [] : [...polishableIndexes.value]
}

const polishable = computed(() =>
  props.content.type === 'iconText'
    ? Boolean(textModel.value?.trim())
    : listItems.value.some((it) => it.text.trim()),
)

function openPolish() {
  if (!polishable.value) {
    message.warning('先写点内容再润色吧')
    return
  }
  if (props.content.type === 'listText') polishTargets.value = [...polishableIndexes.value]
  polishShow.value = true
  nextTick(() => polishInputRef.value?.focus())
}

function cancelPolish() {
  polishShow.value = false
  polishDescription.value = ''
}

async function sendPolish() {
  const parts: string[] = []
  const dirs = POLISH_DIRECTIONS.filter((d) => polishDirs.value.includes(d.key))
  if (dirs.length > 0) parts.push(`润色方向：${dirs.map((d) => d.text).join('、')}`)
  const thought = polishDescription.value.trim()
  if (thought) parts.push(`用户思路：${thought}`)
  const mode = polishMode.value
  const description = parts.join('；')
  const isList = props.content.type === 'listText'
  if (isList && selectedIndexes.value.length === 0) {
    message.warning('先勾选要润色的条目')
    return
  }
  const targets = isList ? [...selectedIndexes.value] : []
  cancelPolish()
  if (!polishable.value) return
  await runPolish(description, mode, targets)
}

async function runPolish(description: string, mode: PolishMode, targets: number[]) {
  const isList = props.content.type === 'listText'
  const items = listItems.value
  const texts = isList
    ? targets.map((i) => items[i]?.text ?? '')
    : [textModel.value ?? '']

  polishing.value = true
  const loading = message.loading(
    isList ? `正在润色 ${texts.length} 条…` : '正在润色…',
    { duration: 0 },
  )
  try {
    const polished = await polishTexts(texts, description, mode)

    if (!isList) {
      const value = polished[0]?.trim()
      if (value && value !== texts[0]) {
        textModel.value = value
        flashText()
        message.success('润色完成')
      } else {
        message.info('这段不用改，内容保持原样')
      }
      return
    }

    const next = items.map((it) => ({ ...it }))
    const changed: number[] = []
    targets.forEach((itemIndex, k) => {
      const value = polished[k]?.trim()
      if (value && value !== next[itemIndex].text) {
        next[itemIndex].text = value
        changed.push(itemIndex)
      }
    })
    saveListItems(next)
    flashList(changed)
    if (changed.length) message.success(`已润色 ${changed.length} 条`)
    else message.info('这几条不用改，内容保持原样')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '润色失败')
  } finally {
    polishing.value = false
    loading?.destroy()
  }
}

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
    <span class="content-drag-handle" title="按住拖动排序 / 移到其他窗口">
      ⋮⋮
    </span>

    <button
      class="content-label"
      :title="`点击展开编辑 · ${CONTENT_TYPE_NAMES[content.type]}`"
      @click.stop="openEdit"
    >
      <span class="content-type-icon" v-html="TYPE_ICONS[content.type]" />
      <span class="content-type-name">{{ CONTENT_TYPE_NAMES[content.type] }}</span>
    </button>

    <div class="content-actions" @click.stop>
      <n-popover v-model:show="moreShow" trigger="click" placement="bottom-end" :width="300">
        <template #trigger>
          <button ref="moreTriggerRef" class="content-more-btn" title="样式 / 复制 / 删除">⋯</button>
        </template>
        <template #default>
          <template v-if="content.type !== 'image'">
            <StylePopover mode="content" :section-id="section.id" :content-id="content.id" />
            <n-divider style="margin: 10px 0" />
          </template>
          <div class="more-actions">
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
            <button type="button" class="more-action-btn" @click="onDuplicate">
              <IconGlyph name="copy" :size="13" />
              <span>复制内容</span>
            </button>
            <button type="button" class="more-action-btn danger" @click="onRemove">
              <IconGlyph name="trash-2" :size="13" />
              <span>删除内容</span>
            </button>
          </div>
        </template>
      </n-popover>
    </div>
  </div>

  <n-modal
    v-model:show="editShow"
    preset="card"
    :title="modalTitle"
    :mask-closable="false"
    style="width: 560px; max-width: 92vw"
  >
    <div class="content-editor">
      <template v-if="content.type === 'iconText'">
        <div class="icontext-toolbar">
          <span class="editor-hint">图标文字内容</span>
          <n-button size="tiny" quaternary class="polish-btn" :disabled="polishing" @click.stop="openPolish">
            <IconGlyph name="sparkles" :size="12" />
            润色
          </n-button>
        </div>
        <div v-if="polishShow" class="polish-input">
          <div class="polish-mode">
            <button
              v-for="m in POLISH_MODES"
              :key="m.key"
              type="button"
              class="polish-mode-btn"
              :class="{ active: polishMode === m.key }"
              :title="m.hint"
              @click="polishMode = m.key"
            >
              {{ m.label }}
            </button>
          </div>
          <div class="polish-dirs">
            <button
              v-for="d in POLISH_DIRECTIONS"
              :key="d.key"
              type="button"
              class="polish-dir-pill"
              :class="{ on: polishDirs.includes(d.key) }"
              @click="togglePolishDir(d.key)"
            >
              {{ d.label }}
            </button>
          </div>
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
            <n-button size="tiny" quaternary @click.stop="cancelPolish">取消</n-button>
            <n-button size="tiny" type="primary" @click.stop="sendPolish">润色</n-button>
          </div>
        </div>
        <div class="icontext-row" :class="{ 'just-polished': textFlash }">
          <n-popover v-model:show="iconPopoverShow" trigger="click" placement="bottom-start" :width="320">
            <template #trigger>
              <button
                ref="iconTriggerRef"
                class="icon-trigger"
                :class="{ empty: !content.content.icon }"
                :title="content.content.icon ? '点击更换图标' : '点击添加图标（留空则不显示图标）'"
              >
                <span v-if="content.content.icon" class="icon-trigger-content" v-html="content.content.icon" />
                <span v-else>＋</span>
              </button>
            </template>
            <template #default>
              <div class="icon-picker">
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
                      <span v-html="ic" />
                    </button>
                  </div>
                </div>
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
            :disabled="polishing"
            :autosize="{ minRows: 1 }"
            placeholder="文字（支持 Markdown；选中后 Ctrl+B 加粗）"
            @keydown="onMarkdownKeydown"
          />
        </div>
        <TagInput v-model="tagsModel" />
      </template>

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

      <template v-else-if="content.type === 'timeRange'">
        <n-input v-model:value="startModel" size="small" placeholder="开始时间，如 2022.07" />
        <span class="editor-divider">-</span>
        <n-input v-model:value="endModel" size="small" placeholder="结束时间，如 至今" />
      </template>

      <template v-else-if="content.type === 'tag'">
        <TagInput v-model="tagsModel" />
      </template>

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

      <template v-else-if="content.type === 'spacer'">
        <div class="spacer-editor">🫥</div>
      </template>

      <template v-else-if="content.type === 'listText'">
        <div class="list-toolbar">
          <n-radio-group v-model:value="listTypeModel" size="small">
            <n-radio-button value="bullet">圆点列表</n-radio-button>
            <n-radio-button value="ordered">数字列表</n-radio-button>
          </n-radio-group>
          <n-button size="tiny" quaternary class="polish-btn" :disabled="polishing" @click.stop="openPolish">
            <IconGlyph name="sparkles" :size="12" />
            润色
          </n-button>
        </div>
        <div v-if="polishShow" class="polish-input">
          <div class="polish-scope">
            <span class="polish-scope-label">润色范围</span>
            <span class="polish-scope-count">
              已选 {{ selectedIndexes.length }} / {{ polishableIndexes.length }}
            </span>
            <button type="button" class="polish-scope-all" @click="toggleAllTargets">
              {{ allSelected ? '取消全选' : '全选' }}
            </button>
          </div>
          <div class="polish-mode">
            <button
              v-for="m in POLISH_MODES"
              :key="m.key"
              type="button"
              class="polish-mode-btn"
              :class="{ active: polishMode === m.key }"
              :title="m.hint"
              @click="polishMode = m.key"
            >
              {{ m.label }}
            </button>
          </div>
          <div class="polish-dirs">
            <button
              v-for="d in POLISH_DIRECTIONS"
              :key="d.key"
              type="button"
              class="polish-dir-pill"
              :class="{ on: polishDirs.includes(d.key) }"
              @click="togglePolishDir(d.key)"
            >
              {{ d.label }}
            </button>
          </div>
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
            <n-button size="tiny" quaternary @click.stop="cancelPolish">取消</n-button>
            <n-button size="tiny" type="primary" @click.stop="sendPolish">润色</n-button>
          </div>
        </div>
        <div class="list-items" :class="{ locked: polishing }">
          <div
            v-for="(item, i) in listItems"
            :key="i"
            class="list-item-edit"
            :class="{
              dragging: dragIndex === i,
              'drag-over': dragOverIndex === i && dragIndex !== i,
              'just-polished': flashIndexes.includes(i),
            }"
            :style="{ paddingLeft: `${(item.indent ?? 0) * INDENT_STEP}px` }"
            @dragover="onDragOver(i, $event)"
            @drop.prevent="onDrop(i)"
          >
            <n-checkbox
              v-if="polishShow"
              class="list-item-check"
              :checked="selectedIndexes.includes(i)"
              :disabled="!item.text.trim()"
              :title="item.text.trim() ? '勾选后参与本次润色' : '空条目无需润色'"
              @update:checked="toggleTarget(i)"
              @click.stop
            />
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
              :disabled="polishing"
              :autosize="{ minRows: 1 }"
              placeholder="列表内容（支持 Markdown；选中后 Ctrl+B 加粗）"
              @update:value="(v: string) => setItem(i, v)"
              @keydown="onMarkdownKeydown"
            />
            <n-button size="tiny" quaternary type="error" @click.stop="removeItem(i)">✕</n-button>
          </div>
        </div>
        <n-button size="tiny" quaternary type="primary" :disabled="polishing" @click.stop="addItem">＋ 添加一项</n-button>
      </template>
    </div>
    <template #footer>
      <div class="modal-footer">
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
  font-size: 14px;
  animation: cardAppear 0.25s ease-out;
  box-shadow: inset 0 0 0 1px transparent;
  transition: box-shadow 0.15s;
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

@container (max-width: 140px) {
  .content-label {
    justify-content: center;
    padding: 0 2px;
  }
  .content-type-name {
    display: none;
  }
}

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

.polish-input {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
}
.polish-btn :deep(.n-button__content) {
  gap: 5px;
}
.polish-mode {
  display: flex;
  gap: 2px;
  padding: 2px;
  border-radius: 8px;
  background: var(--surface-soft);
}
.polish-mode-btn {
  flex: 1;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.polish-mode-btn:hover {
  color: var(--text);
}
.polish-mode-btn.active {
  background: var(--panel-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(28, 33, 48, 0.08);
}
.polish-dirs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.polish-dir-pill {
  height: 22px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel-bg);
  font-size: 11px;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color 0.14s var(--ease),
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.polish-dir-pill:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.polish-dir-pill.on {
  border-color: var(--primary);
  background: var(--primary-faint);
  color: var(--primary);
  font-weight: 600;
}
.polish-input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.polish-scope {
  display: flex;
  align-items: center;
  gap: 8px;
}
.polish-scope-label {
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.polish-scope-count {
  font-size: 11.5px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.polish-scope-all {
  margin-left: auto;
  padding: 0 2px;
  border: none;
  background: transparent;
  font-size: 11.5px;
  color: var(--primary);
  cursor: pointer;
}
.polish-scope-all:hover {
  text-decoration: underline;
}

.icontext-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

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
.icon-trigger :deep(svg) {
  width: 16px;
  height: 16px;
  display: block;
}
.icon-trigger.empty {
  border-style: dashed;
  border-color: var(--border-strong);
  background: var(--surface-soft);
  color: var(--text-tertiary);
  font-size: 14px;
}

.spacer-editor {
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-tertiary);
}

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

.editor-divider {
  align-self: center;
  color: var(--text-tertiary);
  padding: 0 2px;
}

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
.list-items.locked {
  pointer-events: none;
  opacity: 0.6;
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
.list-item-check {
  flex: none;
  margin-top: 4px;
}
@keyframes polishFlash {
  0% {
    background-color: var(--primary-soft);
    box-shadow: inset 0 0 0 1.5px var(--primary);
  }
  55% {
    background-color: var(--primary-faint);
    box-shadow: inset 0 0 0 1.5px var(--primary);
  }
  100% {
    background-color: transparent;
    box-shadow: inset 0 0 0 1.5px transparent;
  }
}
.list-item-edit.just-polished {
  border-radius: 4px;
  animation: polishFlash 1.4s ease-out;
}
.icontext-row.just-polished :deep(.n-input) {
  border-radius: 6px;
  animation: polishFlash 1.4s ease-out;
}
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

.more-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.more-action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.14s var(--ease),
    color 0.14s var(--ease);
}
.more-action-btn .icon-glyph {
  color: var(--text-tertiary);
}
.more-action-btn:hover {
  background: var(--surface-soft);
  color: var(--text);
}
.more-action-btn.danger:hover {
  background: var(--danger-soft);
  color: var(--danger);
}
.more-action-btn.danger:hover .icon-glyph {
  color: var(--danger);
}

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
