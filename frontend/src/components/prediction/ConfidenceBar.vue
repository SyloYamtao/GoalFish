<template>
  <div
    class="confidence-bar"
    role="meter"
    :aria-valuenow="safeValue"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <span
      v-for="idx in 6"
      :key="idx"
      class="confidence-seg"
      :class="{ active: idx <= activeSegments }"
    ></span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },
})

const safeValue = computed(() => {
  const numeric = Number(props.value)
  if (!Number.isFinite(numeric)) return 0
  return Math.max(0, Math.min(100, numeric))
})

const activeSegments = computed(() => Math.round((safeValue.value / 100) * 6))
</script>

<style scoped>
.confidence-bar {
  display: inline-grid;
  grid-template-columns: repeat(6, 8px);
  gap: 2px;
  align-items: center;
  height: 10px;
}

.confidence-seg {
  height: 8px;
  border-radius: 2px;
  background: #EFEFEF;
}

.confidence-seg.active {
  background: #111;
}
</style>
