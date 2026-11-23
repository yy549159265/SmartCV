<script setup lang="ts">
/**
 * 简历原文面板：按引用坐标定位到具体文字单元，并保持黄色高亮。
 *
 * 渲染复用编辑器预览的 PreviewSection / PreviewContent，坐标由
 * `data-coord="s-r-c-i"` 标在文字单元上，与后端 [s:r:c:i] 对齐。
 */

import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { Coord } from '@/api/interview'
import { useResumeStore } from '@/stores/resume'
import IconGlyph from '@/components/IconGlyph.vue'
import PreviewSection from '@/components/PreviewSection.vue'

const props = defineProps<{
  open: boolean
  coords: Coord[]
  seq: number
}>()

const emit = defineEmits<{ close: [] }>()

const resumeStore = useResumeStore()
const scrollEl = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)

function clearFlash(): void {
  scrollEl.value
    ?.querySelectorAll('.coord-flash')
    .forEach((el) => el.classList.remove('coord-flash'))
}

/** 同一字段的多条引用一起点亮，滚动位置对准第一条。 */
async function focusCoords(): Promise<void> {
  if (!props.open || !props.coords.length) return
  await nextTick()
  const root = scrollEl.value
  if (!root) return

  clearFlash()
  const targets = props.coords
    .map((coord) => root.querySelector<HTMLElement>(`[data-coord="${coord.join('-')}"]`))
    .filter((el): el is HTMLElement => el !== null)
  if (!targets.length) return

  for (const target of targets) target.classList.add('coord-flash')
  const first = targets[0]
  const rootRect = root.getBoundingClientRect()
  const targetRect = first.getBoundingClientRect()
  root.scrollTo({
    top:
      root.scrollTop +
      targetRect.top -
      rootRect.top -
      root.clientHeight / 2 +
      targetRect.height / 2,
    behavior: 'smooth',
  })
}

watch(
  () => [props.open, props.coords, props.seq] as const,
  async ([open]) => {
    document.body.style.overflow = open ? 'hidden' : ''
    if (!open) {
      clearFlash()
      return
    }
    await nextTick()
    closeBtn.value?.focus({ preventScroll: true })
    await focusCoords()
  },
  { immediate: true },
)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.open) emit('close')
}

window.addEventListener('keydown', onKeydown)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="source">
      <div v-if="open" class="source-overlay" @click.self="emit('close')">
        <aside class="source-panel" role="dialog" aria-modal="true" aria-label="简历原文">
          <header class="source-head">
            <div class="source-heading">
              <h2>简历原文</h2>
              <p>黄色标记的就是引用在简历里的位置。</p>
            </div>
            <button
              ref="closeBtn"
              class="source-close"
              type="button"
              aria-label="关闭简历原文"
              @click="emit('close')"
            >
              <IconGlyph name="x" :size="18" />
            </button>
          </header>

          <div ref="scrollEl" class="source-scroll">
            <div class="source-paper">
              <PreviewSection
                v-for="(section, index) in resumeStore.resume"
                :key="section.id"
                :section="section"
                :section-index="index"
              />
            </div>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.source-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  justify-content: flex-end;
  background: rgba(24, 30, 46, 0.34);
}

.source-panel {
  display: flex;
  flex-direction: column;
  width: min(760px, 94vw);
  height: 100%;
  background: var(--app-bg);
  border-left: 1px solid var(--border);
  box-shadow: -18px 0 48px rgba(23, 29, 43, 0.16);
}

.source-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 24px 18px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
}
.source-heading h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.015em;
}
.source-heading p {
  margin: 5px 0 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}
.source-close {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--panel-bg);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color var(--dur-2) var(--ease),
    color var(--dur-2) var(--ease),
    background-color var(--dur-2) var(--ease);
}
.source-close:hover {
  border-color: var(--border-strong);
  background: var(--surface-soft);
  color: var(--text);
}

.source-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px 22px 48px;
}

.source-paper {
  max-width: 680px;
  margin: 0 auto;
  padding: 34px 32px 42px;
  background: var(--doc-paper, #fff);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-paper);
}

:global([data-coord].coord-flash) {
  background: rgba(250, 204, 21, 0.42);
  box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.28);
  border-radius: 3px;
  transition: background-color 0.2s var(--ease);
}

.source-enter-active,
.source-leave-active {
  transition: opacity 0.2s var(--ease);
}
.source-enter-active .source-panel,
.source-leave-active .source-panel {
  transition: transform 0.24s var(--ease-out);
}
.source-enter-from,
.source-leave-to {
  opacity: 0;
}
.source-enter-from .source-panel,
.source-leave-to .source-panel {
  transform: translateX(32px);
}

@media (max-width: 640px) {
  .source-overlay {
    align-items: stretch;
  }
  .source-panel {
    width: 100%;
  }
  .source-head {
    padding: 16px 16px 14px;
  }
  .source-scroll {
    padding: 16px 10px 32px;
  }
  .source-paper {
    padding: 24px 18px 32px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .source-enter-active,
  .source-leave-active,
  .source-enter-active .source-panel,
  .source-leave-active .source-panel {
    transition: none;
  }
}
</style>
