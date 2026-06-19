<template>
  <span class="info-tooltip">
    <button
      ref="triggerRef"
      class="info-trigger"
      type="button"
      :aria-label="ariaLabel"
      :aria-describedby="tooltipId"
      @mouseenter="show"
      @mouseleave="hide"
      @focus="show"
      @blur="hide"
      @keydown.esc="hide"
    >
      i
    </button>
    <Teleport to="body">
      <span
        v-if="visible"
        :id="tooltipId"
        ref="bubbleRef"
        class="info-bubble"
        role="tooltip"
        :style="bubbleStyle"
      >
        <b v-if="title">{{ title }}</b>
        <span>{{ text }}</span>
      </span>
    </Teleport>
  </span>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  text: { type: String, required: true },
  align: {
    type: String,
    default: 'center',
    validator: value => ['left', 'center', 'right'].includes(value)
  }
})

const tooltipId = `info-tip-${Math.random().toString(36).slice(2, 10)}`
const ariaLabel = props.title ? `说明：${props.title}` : '配置说明'
const triggerRef = ref(null)
const bubbleRef = ref(null)
const visible = ref(false)
const position = ref({ left: 0, top: 0, arrowLeft: 16 })

const bubbleStyle = computed(() => ({
  left: `${position.value.left}px`,
  top: `${position.value.top}px`,
  '--arrow-left': `${position.value.arrowLeft}px`
}))

const show = async () => {
  visible.value = true
  await nextTick()
  updatePosition()
}

const hide = () => {
  visible.value = false
}

const updatePosition = () => {
  const trigger = triggerRef.value
  const bubble = bubbleRef.value
  if (!trigger || !bubble) return

  const triggerRect = trigger.getBoundingClientRect()
  const bubbleRect = bubble.getBoundingClientRect()
  const margin = 8
  const gap = 8
  const viewportWidth = window.innerWidth

  let left = triggerRect.left + triggerRect.width / 2 - bubbleRect.width / 2
  if (props.align === 'left') left = triggerRect.left
  if (props.align === 'right') left = triggerRect.right - bubbleRect.width

  left = Math.max(margin, Math.min(left, viewportWidth - bubbleRect.width - margin))
  const triggerCenter = triggerRect.left + triggerRect.width / 2
  const arrowLeft = Math.max(12, Math.min(triggerCenter - left, bubbleRect.width - 12))

  position.value = {
    left,
    top: triggerRect.bottom + gap,
    arrowLeft
  }
}

const closeOnViewportChange = () => hide()
window.addEventListener('scroll', closeOnViewportChange, true)
window.addEventListener('resize', closeOnViewportChange)

onBeforeUnmount(() => {
  window.removeEventListener('scroll', closeOnViewportChange, true)
  window.removeEventListener('resize', closeOnViewportChange)
})
</script>

<style scoped>
.info-tooltip {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  vertical-align: middle;
}

.info-trigger {
  width: 18px;
  height: 18px;
  border: 1px solid #BDBDBD;
  border-radius: 50%;
  background: #FFF;
  color: #555;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  cursor: help;
  padding: 0;
}

.info-trigger:hover,
.info-trigger:focus-visible {
  border-color: #111;
  color: #111;
  outline: none;
}

.info-bubble {
  position: fixed;
  z-index: 2147483000;
  width: min(320px, calc(100vw - 16px));
  background: #111;
  color: #FFF;
  border-radius: 6px;
  padding: 10px 12px;
  box-shadow: 0 12px 28px rgba(0, 0, 0, .18);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.55;
  white-space: normal;
  overflow-wrap: anywhere;
  pointer-events: none;
}

.info-bubble::before {
  content: '';
  position: absolute;
  top: -5px;
  left: var(--arrow-left);
  transform: translateX(-50%) rotate(45deg);
  width: 10px;
  height: 10px;
  background: #111;
}

.info-bubble b {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
}
</style>
