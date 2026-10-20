<script setup lang="ts">
/**
 * 品牌标记：一枚苔绿纸片 + 三行文字。
 * 只用于应用外壳（顶部栏、主页），不进入简历预览/导出。
 */
withDefaults(defineProps<{ size?: number }>(), { size: 22 })
</script>

<template>
  <svg
    class="brand-mark"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <rect x="2" y="2" width="20" height="20" rx="6" fill="var(--primary)" />
    <path
      d="M7.75 8.25h8.5M7.75 12h8.5M7.75 15.75h5"
      stroke="#ffffff"
      stroke-width="1.5"
      stroke-linecap="round"
      opacity="0.9"
    />
  </svg>
</template>

<style scoped>
.brand-mark {
  display: block;
  flex: none;
}
</style>
