<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import IconGlyph from '@/components/IconGlyph.vue'
import { listReferenceExamples, type ReferenceExampleMeta } from '@/api/referenceExamples'

const props = defineProps<{ selected: string[] }>()
const emit = defineEmits<{ 'update:selected': [string[]]; 'open-library': [] }>()

const items = ref<ReferenceExampleMeta[]>([])
const state = ref<'loading' | 'ready' | 'error'>('loading')
const error = ref('')

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    items.value = await listReferenceExamples()
    state.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '示例库读取失败'
    state.value = 'error'
  }
}

onMounted(load)

const metaById = computed(() => new Map(items.value.map((item) => [item.id, item])))

const selectedItems = computed(() =>
  props.selected.map(
    (id) =>
      metaById.value.get(id) ?? {
        id,
        direction: '示例',
        description: '',
        createdAt: '',
        sectionCount: 0,
      },
  ),
)

const collapsed = ref(false)

const selectedPreview = computed(() =>
  selectedItems.value.map((item) => item.direction).join(' · '),
)

const showPicker = ref(false)
const keyword = ref('')
const draft = ref<string[]>([])

const draftOrder = computed(() => new Map(draft.value.map((id, i) => [id, i + 1])))
const isFull = computed(() => draft.value.length >= 3)

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter(
    (item) =>
      item.direction.toLowerCase().includes(q) || item.description.toLowerCase().includes(q),
  )
})

function openPicker() {
  draft.value = [...props.selected]
  keyword.value = ''
  showPicker.value = true
  if (state.value === 'error') void load()
}

function toggleDraft(item: ReferenceExampleMeta) {
  const index = draft.value.indexOf(item.id)
  if (index >= 0) draft.value.splice(index, 1)
  else if (draft.value.length < 3) draft.value.push(item.id)
}

function confirm() {
  emit('update:selected', [...draft.value])
  showPicker.value = false
  collapsed.value = false
}

function remove(id: string) {
  emit(
    'update:selected',
    props.selected.filter((item) => item !== id),
  )
}

function goLibrary() {
  showPicker.value = false
  emit('open-library')
}
</script>

<template>
  <div class="ref-picker">
    <div class="ref-head">
      <button
        type="button"
        class="ref-toggle"
        :aria-expanded="!collapsed"
        @click="collapsed = !collapsed"
      >
        <span class="ref-caret" :class="{ open: !collapsed }" aria-hidden="true"></span>
        <span class="ref-toggle-text">优秀示例（可选，最多 3 份）</span>
        <span v-if="selected.length" class="ref-selected-count">已选 {{ selected.length }} 份</span>
        <span class="ref-toggle-spacer" />
        <span v-if="collapsed && selectedPreview" class="ref-selected-preview">
          {{ selectedPreview }}
        </span>
      </button>
      <button
        type="button"
        class="ref-pick-cta"
        :aria-label="selected.length ? '调整优秀示例' : '选择优秀示例'"
        @click="openPicker"
      >
        <IconGlyph name="plus" :size="13" />
        {{ selected.length ? '调整' : '选择' }}
      </button>
    </div>

    <div v-if="!collapsed && selectedItems.length" class="ref-selected-list">
      <div v-for="(item, i) in selectedItems" :key="item.id" class="ref-selected-item">
        <span class="ref-index on">{{ i + 1 }}</span>
        <span class="ref-selected-copy">
          <span class="ref-selected-direction">{{ item.direction }}</span>
          <span v-if="item.description" class="ref-selected-desc">{{ item.description }}</span>
        </span>
        <button
          type="button"
          class="ref-selected-remove"
          aria-label="取消选择"
          title="取消选择"
          @click="remove(item.id)"
        >
          <IconGlyph name="x" :size="13" />
        </button>
      </div>
    </div>

    <n-modal
      v-model:show="showPicker"
      display-directive="if"
      :mask-closable="false"
      preset="card"
      style="width: 640px; max-width: 94vw"
    >
      <template #header>
        <div class="ref-modal-head">
          <span class="ref-modal-title">选择优秀示例</span>
          <span class="ref-modal-count">已选 {{ draft.length }} / 3</span>
        </div>
      </template>

      <div class="ref-picker-modal">
        <n-input v-model:value="keyword" clearable placeholder="搜索职业方向或描述">
          <template #prefix>
            <IconGlyph name="search" :size="14" />
          </template>
        </n-input>

        <div v-if="state === 'loading'" class="ref-status">
          <n-spin size="small" />
          <span>正在读取示例库…</span>
        </div>

        <div v-else-if="state === 'error'" class="ref-status">
          <span class="ref-status-text">{{ error }}</span>
          <n-button size="tiny" @click="load">重试</n-button>
        </div>

        <div v-else-if="items.length === 0" class="ref-status">
          <span class="ref-status-text">示例库还没有内容，上传后就能在这里选择。</span>
          <n-button size="tiny" type="primary" ghost @click="goLibrary">
            <IconGlyph name="file-plus-2" :size="13" />
            去上传示例
          </n-button>
        </div>

        <template v-else>
          <div v-if="filtered.length" class="ref-pick-list">
            <button
              v-for="item in filtered"
              :key="item.id"
              type="button"
              class="ref-pick-item"
              :class="{
                selected: draftOrder.has(item.id),
                'is-disabled': !draftOrder.has(item.id) && isFull,
              }"
              :disabled="!draftOrder.has(item.id) && isFull"
              :aria-pressed="draftOrder.has(item.id)"
              @click="toggleDraft(item)"
            >
              <span class="ref-index" :class="{ on: draftOrder.has(item.id) }">
                {{ draftOrder.get(item.id) ?? '' }}
              </span>
              <span class="ref-item-copy">
                <span class="ref-item-top">
                  <span class="ref-item-direction">{{ item.direction }}</span>
                  <span class="ref-item-meta">{{ item.sectionCount }} 个章节</span>
                </span>
                <span class="ref-item-desc">{{ item.description }}</span>
              </span>
            </button>
          </div>

          <div v-else class="ref-status">
            <span class="ref-status-text">没有匹配「{{ keyword }}」的示例。</span>
          </div>

          <p v-if="isFull" class="ref-limit-tip">已选满 3 份；取消一份后才能选择其它示例。</p>
        </template>
      </div>

      <template #footer>
        <div class="ref-modal-footer">
          <div class="ref-modal-actions">
            <n-button size="small" @click="showPicker = false">取消</n-button>
            <n-button size="small" type="primary" @click="confirm">确定选择</n-button>
          </div>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.ref-picker {
  border-bottom: 1px solid var(--border);
  background: var(--panel-bg);
}
.ref-head {
  display: flex;
  align-items: center;
  gap: 2px;
  padding-right: 16px;
}
.ref-toggle {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 9px 0 9px 16px;
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s var(--ease),
    color 0.16s var(--ease);
}
.ref-toggle:hover {
  background: var(--surface-soft);
  color: var(--text);
}

.ref-caret {
  flex: none;
  position: relative;
  width: 11px;
  height: 11px;
  color: var(--text-tertiary);
  transition: color 0.16s var(--ease);
}
.ref-caret::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 50%;
  width: 5px;
  height: 5px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  border-radius: 1px;
  transform: translateY(-50%) rotate(-45deg);
  transition: transform 0.2s var(--ease);
}
.ref-caret.open::before {
  transform: translateY(-50%) rotate(45deg);
}
.ref-toggle:hover .ref-caret {
  color: var(--primary);
}
.ref-toggle-text {
  flex: none;
  white-space: nowrap;
}
.ref-selected-count {
  flex: none;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary-hover);
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
}
.ref-toggle-spacer {
  flex: 1;
  min-width: 8px;
}
.ref-selected-preview {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 11px;
  font-weight: 400;
  color: var(--text-tertiary);
}
.ref-pick-cta {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--primary);
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.16s var(--ease);
}
.ref-pick-cta:hover {
  background: var(--primary-faint);
}

.ref-selected-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0 16px 11px;
}
.ref-selected-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-soft);
}
.ref-selected-copy {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 2px 8px;
  min-width: 0;
  flex: 1;
}
.ref-selected-direction {
  flex: none;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.ref-selected-desc {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 11px;
  color: var(--text-tertiary);
}
.ref-selected-remove {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition:
    color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.ref-selected-remove:hover {
  color: var(--danger);
  background: var(--danger-soft);
}

.ref-modal-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ref-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.ref-modal-count {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-sunken);
  font-size: 10.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ref-picker-modal {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ref-pick-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 46vh;
  overflow-y: auto;
  padding: 2px;
}
.ref-pick-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--panel-bg);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s var(--ease),
    background 0.16s var(--ease);
}
.ref-pick-item:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
}
.ref-pick-item.selected {
  border-color: var(--primary);
  background: var(--primary-faint);
}
.ref-pick-item.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ref-pick-item.is-disabled:hover {
  border-color: var(--border);
  background: var(--panel-bg);
}
.ref-index {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  color: transparent;
  transition:
    background 0.16s var(--ease),
    border-color 0.16s var(--ease),
    color 0.16s var(--ease);
}
.ref-index.on {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}
.ref-item-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ref-item-top {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
}
.ref-item-direction {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.ref-item-meta {
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.ref-item-desc {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
.ref-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 22px 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-secondary);
  justify-content: center;
  text-align: center;
}
.ref-status-text {
  min-width: 0;
  overflow-wrap: anywhere;
}
.ref-limit-tip {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-tertiary);
}
.ref-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}
.ref-modal-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
