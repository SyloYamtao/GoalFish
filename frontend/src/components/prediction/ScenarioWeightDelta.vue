<template>
  <span class="weight-delta" :title="tooltip">
    <template v-if="Number(initial) !== Number(final)">
      {{ initial }}
      <i class="weight-arrow"></i>
      <b>{{ final }}</b>
      <i class="weight-direction" :class="`weight-direction-${direction}`">
        {{ direction === 'up' ? '▲' : direction === 'down' ? '▼' : '' }}
      </i>
    </template>
    <template v-else>
      {{ final }}
    </template>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  initial: { type: [Number, String], default: 0 },
  final: { type: [Number, String], default: 0 },
  weightChange: { type: Object, default: () => ({}) }
})

const delta = computed(() => Number(props.final || 0) - Number(props.initial || 0))
const direction = computed(() => delta.value > 0 ? 'up' : delta.value < 0 ? 'down' : 'flat')

const tooltip = computed(() => {
  const change = props.weightChange || {}
  const contributors = Array.isArray(change.contributors) ? change.contributors : []
  const voteText = contributors
    .map(item => `${item.role || item.source || 'role'} ${item.delta ?? item.applied_delta ?? ''}`.trim())
    .filter(Boolean)
    .join(' / ')
  const applied = change.applied_delta ?? change.applied_weight_delta ?? delta.value
  return voteText ? `${voteText} -> applied ${applied}` : `initial ${props.initial} -> final ${props.final}`
})
</script>

<style scoped>
.weight-delta {
  background: #111;
  color: #FFF;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
}

.weight-arrow {
  display: inline-block;
  width: 8px;
  height: 1px;
  background: #999;
  margin: 0 2px;
}

.weight-direction {
  font-size: 9px;
  color: #FF4500;
}
</style>
