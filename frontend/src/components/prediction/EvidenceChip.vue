<template>
  <span class="ev-wrap" :class="{ 'ev-wrap-compact': compact }">
    <button
      ref="triggerRef"
      class="ev-chip"
      :class="{ 'ev-chip-compact': compact }"
      type="button"
      :aria-expanded="expanded"
      :aria-label="t('prediction.viewEvidence', { source: sourceLabel })"
      :title="compact ? sourceLabel : ''"
      @click="toggleExpanded"
    >
      <span v-if="compact" class="ev-chip-compact-label">{{ compactSourceLabel }}</span>
      <span v-else class="ev-chip-source mono">[{{ sourceLabel }}]</span>
    </button>
    <Teleport to="body">
      <transition name="slide-down">
        <span
          v-if="expanded"
          ref="detailRef"
          class="ev-detail"
          :style="detailStyle"
        >
          <span class="ev-detail-title">{{ sourceLabel }}</span>
          <span v-if="normalizedRefs.length === 0" class="ev-empty">{{ t('prediction.emptyEvidence') }}</span>
          <span v-for="ref in normalizedRefs" :key="ref.id" class="ev-row">
            <span class="mono">{{ ref.type }}</span>
            <b>{{ ref.name }}</b>
            <span v-if="ref.contribution_pct !== null" class="mono">{{ ref.contribution_pct.toFixed(1) }}%</span>
          </span>
        </span>
      </transition>
    </Teleport>
  </span>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  compactEvidenceSourceLabel,
  evidenceSourceLabel,
} from '../../utils/evidenceSourceLabels.js'

const props = defineProps({
  source: { type: String, default: '-' },
  refs: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false }
})
const { t } = useI18n()

const expanded = ref(false)
const triggerRef = ref(null)
const detailRef = ref(null)
const position = ref({ left: 0, top: 0 })

const sourceLabel = computed(() => evidenceSourceLabel(props.source, t))
const compactSourceLabel = computed(() => compactEvidenceSourceLabel(props.source, t))
const detailStyle = computed(() => ({
  left: `${position.value.left}px`,
  top: `${position.value.top}px`
}))

const normalizedRefs = computed(() => (props.refs || []).map((item, index) => ({
  id: item.id || item.player_id || item.name || `${props.source}-${index}`,
  type: item.type || item.position || item.source || 'ref',
  name: item.name || item.player_name || item.full_name || item.label || '-',
  contribution_pct: Number.isFinite(Number(item.contribution_pct)) ? Number(item.contribution_pct) : null
})))

const updatePosition = () => {
  const trigger = triggerRef.value
  const detail = detailRef.value
  if (!trigger || !detail) return

  const triggerRect = trigger.getBoundingClientRect()
  const detailRect = detail.getBoundingClientRect()
  const margin = 8
  const gap = 6

  const left = Math.max(
    margin,
    Math.min(triggerRect.right - detailRect.width, window.innerWidth - detailRect.width - margin)
  )

  let top = triggerRect.bottom + gap
  const bottomOverflow = top + detailRect.height > window.innerHeight - margin
  if (bottomOverflow && triggerRect.top - detailRect.height - gap > margin) {
    top = triggerRect.top - detailRect.height - gap
  }

  position.value = { left, top }
}

const hide = () => {
  expanded.value = false
}

const toggleExpanded = async () => {
  expanded.value = !expanded.value
  if (!expanded.value) return
  await nextTick()
  updatePosition()
}

window.addEventListener('scroll', hide, true)
window.addEventListener('resize', hide)

onBeforeUnmount(() => {
  window.removeEventListener('scroll', hide, true)
  window.removeEventListener('resize', hide)
})
</script>

<style scoped>
.ev-wrap {
  position: relative;
  display: inline-flex;
  margin-left: 4px;
  vertical-align: middle;
}

.ev-wrap-compact {
  margin-left: 0;
}

.ev-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #EFEFEF;
  background: #F5F5F5;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  color: #666;
  cursor: pointer;
  font-family: inherit;
}

.ev-chip:hover {
  background: #EAEAEA;
}

.ev-chip:focus-visible {
  outline: 2px solid #111;
  outline-offset: 2px;
}

.ev-chip-compact {
  width: 34px;
  min-width: 34px;
  height: 20px;
  padding: 0;
  border-color: #D9D9D9;
  background: #FFF;
  color: #555;
}

.ev-chip-compact-label {
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.ev-detail {
  position: fixed;
  z-index: 2147483000;
  min-width: 220px;
  width: max-content;
  max-width: min(320px, calc(100vw - 16px));
  background: #FFF;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  padding: 8px;
  color: #555;
  display: grid;
  gap: 6px;
  font-size: 11px;
  box-shadow: 0 14px 32px rgba(0, 0, 0, .16);
}

.ev-detail-title {
  color: #111;
  font-weight: 800;
}

.ev-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  gap: 6px;
  align-items: center;
}

.ev-row b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ev-empty {
  color: #777;
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: opacity .14s ease, transform .14s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
