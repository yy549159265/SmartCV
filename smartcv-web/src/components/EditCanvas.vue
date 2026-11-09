<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { onKeyStroke } from '@vueuse/core'
import { VueDraggable } from 'vue-draggable-plus'
import SectionCard from './SectionCard.vue'
import BrandMark from './BrandMark.vue'
import IconGlyph from './IconGlyph.vue'
import { useResumeStore } from '@/stores/resume'
import { createSectionFromPreset } from '@/data/presets'
import { message } from '@/utils/feedback'

const store = useResumeStore()

const scrollEl = ref<HTMLElement | null>(null)

const EDGE_ZONE = 80
const MAX_SCROLL_SPEED = 14

let dragActive = false
let pointerX = 0
let pointerY = 0
let rafId = 0

function onPointerMove(e: PointerEvent) {
  pointerX = e.clientX
  pointerY = e.clientY
}

function tick() {
  rafId = 0
  if (!dragActive) return
  const el = scrollEl.value
  if (el) {
    const rect = el.getBoundingClientRect()
    if (pointerX >= rect.left && pointerX <= rect.right) {
      const fromTop = pointerY - rect.top
      const fromBottom = rect.bottom - pointerY
      let speed = 0
      if (fromTop >= 0 && fromTop < EDGE_ZONE && el.scrollTop > 0) {
        speed = -MAX_SCROLL_SPEED * (1 - fromTop / EDGE_ZONE)
      } else if (
        fromBottom >= 0 &&
        fromBottom < EDGE_ZONE &&
        el.scrollTop < el.scrollHeight - el.clientHeight
      ) {
        speed = MAX_SCROLL_SPEED * (1 - fromBottom / EDGE_ZONE)
      }
      if (speed !== 0) el.scrollTop += speed
    }
  }
  rafId = requestAnimationFrame(tick)
}

function onDragStart(e: Event) {
  const oe = (e as { originalEvent?: { clientX?: number; clientY?: number } }).originalEvent
  if (oe && typeof oe.clientX === 'number' && typeof oe.clientY === 'number') {
    pointerX = oe.clientX
    pointerY = oe.clientY
  }
  dragActive = true
  if (!rafId) rafId = requestAnimationFrame(tick)
}

function onDragEnd() {
  dragActive = false
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = 0
  }
}

onMounted(() => {
  document.addEventListener('start', onDragStart)
  document.addEventListener('end', onDragEnd)
  window.addEventListener('pointermove', onPointerMove, { passive: true })
  window.addEventListener('blur', onDragEnd)
})

onBeforeUnmount(() => {
  document.removeEventListener('start', onDragStart)
  document.removeEventListener('end', onDragEnd)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('blur', onDragEnd)
  onDragEnd()
})

function indexOfId<T extends { id?: unknown }>(arr: T[], id: unknown): number {
  if (typeof id !== 'string') return -1
  return arr.findIndex((x) => x && x.id === id)
}

function onSectionAdd(evt: { data?: unknown; newIndex?: number }) {
  const preset = evt.data as { id?: unknown; name?: string; type?: unknown; layout?: unknown } | undefined
  if (!preset || typeof preset.name !== 'string' || preset.type !== undefined || preset.layout !== undefined) {
    const i = indexOfId(store.resume, preset?.id)
    if (i >= 0) store.resume.splice(i, 1)
    message.warning('这里只能放章节（从组件库「章节」分组拖入）')
    return
  }
  const real = createSectionFromPreset(preset as never)
  const arr = store.resume
  const i = indexOfId(arr, preset.id)
  if (i >= 0) {
    arr.splice(i, 1, real)
  } else {
    arr.splice(Math.min(evt.newIndex ?? arr.length, arr.length), 1, real)
  }
  store.select(real.id)
}

onKeyStroke('Delete', () => {
  const active = document.activeElement as HTMLElement | null
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) {
    return
  }
  const section = store.selectedSection
  if (section) {
    store.removeSection(section.id)
    message.success('章节已删除')
    return
  }
  const row = store.selectedRow
  if (row) {
    store.removeRow(row.section.id, row.row.id)
    message.success('布局窗口已删除')
    return
  }
  const sel = store.selectedContent
  if (sel) {
    store.removeContent(sel.section.id, sel.content.id)
    message.success('内容已删除')
  }
})
</script>

<template>
  <section class="canvas">
    <div class="canvas-toolbar">
      <span class="canvas-title-icon"><IconGlyph name="pen-line" :size="15" /></span>
      <span class="canvas-title">编辑画布</span>
      <span class="canvas-hint">从上方组件库点击添加，或拖到指定位置；拖动 ⋮⋮ 手柄排序</span>
    </div>

    <div ref="scrollEl" class="canvas-scroll">
      <div class="canvas-sheet" @click.self="store.select(null)">
        <div class="section-list">
          <VueDraggable
            v-model="store.resume"
            :group="{ name: 'smartcv-group', put: ['smartcv-group'] }"
            handle=".section-drag-handle"
            :animation="200"
            class="section-list-inner"
            @add="onSectionAdd"
          >
            <SectionCard v-for="g in store.resume" :key="g.id" :section="g" />
          </VueDraggable>

          <div v-if="store.resume.length === 0" class="canvas-empty">
            <BrandMark :size="36" class="canvas-empty-mark" />
            <p>
              画布是空的<br />
              从上方组件库点击或拖入章节开始
            </p>
          </div>

        </div>
      </div>

      <div class="canvas-bottom-space" />
    </div>
  </section>
</template>

<style scoped>
.canvas {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  min-width: 0;
  background: var(--surface-sunken);
  container-type: inline-size;
}

.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 14px;
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border);
}
.canvas-title-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--primary-soft);
  color: var(--primary);
}
.canvas-title {
  flex: none;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text);
}
.canvas-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.canvas-scroll {
  flex: 1;
  overflow: auto;
  padding: 24px 16px 56px;
}

.canvas-sheet {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1000px;
  margin: 0 auto;
  padding: 20px 16px 28px;
  background: var(--panel-bg);
  border-radius: var(--radius-lg);
  box-shadow:
    0 0 0 1px var(--border),
    var(--shadow-paper);
}

.section-list {
  position: relative;
  flex: 1;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}
.section-list-inner {
  flex: 1;
  min-height: 240px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.canvas-empty {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
  color: var(--text-tertiary);
  pointer-events: none;
}
.canvas-empty-mark {
  opacity: 0.35;
}
.canvas-empty p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.8;
}

.canvas-bottom-space {
  height: 24px;
}
</style>
