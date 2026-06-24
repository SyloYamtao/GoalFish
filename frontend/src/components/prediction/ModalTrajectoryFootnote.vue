<template>
  <div class="modal-traj">
    <span class="modal-traj-dot"></span>
    <span class="mono">{{ t('prediction.sampleCount', { count: nSimsLabel }) }}</span>
    <span class="modal-traj-detail">
      {{ t('prediction.firstGoal', { minute: firstGoalLabel }) }}
      <template v-if="trajectory?.decisive_minute">
        {{ t('prediction.decisiveGoal', { minute: trajectory.decisive_minute }) }}
      </template>
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  trajectory: { type: Object, default: () => ({}) },
  nSims: { type: [Number, String], default: 0 },
})

const { t, locale } = useI18n()

const nSimsLabel = computed(() => Number(props.nSims || 0).toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US'))
const firstGoalLabel = computed(() => (
  props.trajectory?.first_goal_minute ? `${props.trajectory.first_goal_minute}'` : t('prediction.noFirstGoal')
))
</script>

<style scoped>
.modal-traj {
  border-top: 1px dashed #EAEAEA;
  margin-top: 10px;
  padding-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #666;
  min-width: 0;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

.modal-traj-dot {
  width: 6px;
  height: 6px;
  background: #FF4500;
  border-radius: 50%;
  flex: 0 0 auto;
}

.modal-traj-detail {
  color: #777;
  font-family: 'JetBrains Mono', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
