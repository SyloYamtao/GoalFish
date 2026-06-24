<template>
  <div class="meter">
    <div class="meter-title">
      <small>{{ t('prediction.callDistributionSummary', { total: totalCalls, planned: plannedCalls, cap: hardCap }) }}</small>
      <InfoTooltip
        align="right"
        :title="t('prediction.callDistributionTitle')"
        :text="t('prediction.callDistributionTooltip')"
      />
    </div>
    <div class="meter-bar" aria-hidden="true">
      <div
        v-for="seg in segments"
        :key="seg.key"
        class="meter-seg"
        :style="{ width: seg.width + '%' }"
        :class="seg.class"
        :title="seg.tooltip"
      ></div>
    </div>
    <div class="meter-legend">
      <span v-for="seg in visibleLegend" :key="seg.key">
        <i class="meter-dot" :class="seg.class"></i>
        {{ seg.label }} <b class="mono">{{ seg.count }}</b>
      </span>
      <span v-if="failures.length" class="meter-failures">{{ t('prediction.failuresShort') }} <b class="mono">{{ failures.length }}</b></span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  ledger: { type: Object, default: () => ({}) }
})

const { t } = useI18n()

const totalCalls = computed(() => Number(props.ledger?.total_calls ?? props.ledger?.calls_used ?? 0))
const cached = computed(() => Number(props.ledger?.cached ?? props.ledger?.calls_cached ?? 0))
const plannedCalls = computed(() => Number(props.ledger?.calls_planned ?? props.ledger?.planned_calls ?? totalCalls.value))
const hardCap = computed(() => Number(props.ledger?.hard_cap ?? props.ledger?.hard_cap_calls ?? 0))
const fresh = computed(() => Math.max(0, totalCalls.value - cached.value))
const remaining = computed(() => Math.max(0, hardCap.value - totalCalls.value))
const denominator = computed(() => Math.max(hardCap.value, totalCalls.value, 1))
const failures = computed(() => props.ledger?.failures || [])

const segments = computed(() => [
  {
    key: 'fresh',
    label: 'fresh',
    count: fresh.value,
    width: fresh.value / denominator.value * 100,
    class: 'fresh',
    tooltip: `${fresh.value} fresh calls`
  },
  {
    key: 'cached',
    label: 'cached',
    count: cached.value,
    width: cached.value / denominator.value * 100,
    class: 'cached',
    tooltip: `${cached.value} cached calls`
  },
  {
    key: 'remain',
    label: 'remain',
    count: remaining.value,
    width: remaining.value / denominator.value * 100,
    class: 'budget-remain',
    tooltip: `${remaining.value} calls remaining`
  }
])

const visibleLegend = computed(() => segments.value.filter(seg => seg.key !== 'remain' || hardCap.value > 0))
</script>

<style scoped>
.meter {
  margin-top: 16px;
}

.meter-title small {
  color: #777;
  font-size: 12px;
}

.meter-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meter-bar {
  display: flex;
  height: 10px;
  background: #EFEFEF;
  border-radius: 4px;
  overflow: hidden;
  margin: 8px 0;
}

.meter-seg {
  background: #111;
  height: 100%;
  min-width: 0;
}

.meter-seg.cached {
  background: #999;
}

.meter-seg.budget-remain {
  background: #EFEFEF;
}

.meter-legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #555;
}

.meter-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
  background: #111;
  vertical-align: middle;
}

.meter-dot.cached {
  background: #999;
}

.meter-dot.budget-remain {
  background: #EFEFEF;
  border: 1px solid #E1E1E1;
}

.meter-failures {
  color: #8A1F2D;
}
</style>
