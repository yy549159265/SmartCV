<script setup lang="ts">
/**
 * 标签输入：一次输入多个标签，用 空格 / 回车 / 逗号 / 分号 / 、 分隔，
 * 输完自动切成一个个标签芯片，每个都能单独删掉。
 * 给「标签」「图标文字」两种内容的编辑弹窗共用（v-model 绑定内容数组）。
 */
import { ref } from 'vue'

const props = defineProps<{ modelValue?: string[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string[]): void }>()

const input = ref('')

/** 把输入框里当前内容拆成标签并追加（去空、去重） */
function commit() {
  const parts = input.value
    .split(/[\s,，;；、]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (parts.length) {
    emit('update:modelValue', [...new Set([...(props.modelValue ?? []), ...parts])])
  }
  input.value = ''
}

/** 空格 / 回车 / 逗号 / 分号 都当作分隔符，按下即生成标签（不留在输入框里） */
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ' ' || e.key === ',' || e.key === ';') {
    e.preventDefault()
    commit()
  }
}

/** 按值删除（标签已去重，不会有重名，用值比用下标更稳） */
function remove(tag: string) {
  emit('update:modelValue', (props.modelValue ?? []).filter((t) => t !== tag))
}
</script>

<template>
  <div class="tag-input">
    <div v-if="(modelValue ?? []).length" class="tag-chips">
      <span v-for="t in modelValue" :key="t" class="tag-chip">
        {{ t }}
        <button class="tag-remove" title="删除这个标签" @click.stop="remove(t)">✕</button>
      </span>
    </div>
    <input
      v-model="input"
      class="tag-field"
      type="text"
      placeholder="输入标签，用 空格 / 回车 / 逗号 分隔"
      @keydown="onKeydown"
      @blur="commit"
    />
  </div>
</template>

<style scoped>
.tag-input {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tag-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 6px 0 10px;
  border-radius: 999px;
  background: #eef1f6;
  font-size: 12px;
  line-height: 1.7;
  color: #374151;
}
.tag-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #9ca3af;
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.tag-remove:hover {
  background: #e2e8f0;
  color: #ef4444;
}
.tag-field {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 10px;
  border: 1px solid #d8dde6;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  line-height: 1.5;
  color: #374151;
  outline: none;
  transition: border-color 0.15s;
}
.tag-field:focus {
  border-color: var(--primary);
}
</style>
