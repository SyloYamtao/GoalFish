<template>
  <div class="rs-card">
    <div class="rs-card-title">
      <span>球员名册</span>
      <InfoTooltip
        align="right"
        title="球员名册"
        text="展示当前数据集中主队和客队各自的名册覆盖、平均能力、门将最高专项分、伤停和状态存疑人数。平均能力用于球队整体和位置深度估计；门将单独展示，是因为扑救、出球、高球处理会进入独立门将维度，而不是替代平均能力。"
      />
    </div>

    <div class="rs-team-list">
      <div class="rs-team" v-for="team in teamRows" :key="team.role">
        <div class="rs-row">
          <span class="rs-team-label">{{ team.label }}</span>
          <b :title="team.name">{{ team.name }}</b>
          <span class="mono">{{ team.playersCount }} 人</span>
        </div>

        <dl class="rs-stats">
          <div class="rs-stat">
            <dt>平均能力</dt>
            <dd class="mono">{{ formatNumber(team.avgOverall, 1) }}</dd>
          </div>
          <div class="rs-stat">
            <dt>门将</dt>
            <dd class="mono">{{ formatNumber(team.gkMax, 0) }}</dd>
          </div>
          <div class="rs-stat">
            <dt>伤停</dt>
            <dd class="mono">{{ team.unavailable }}</dd>
          </div>
          <div class="rs-stat">
            <dt>状态存疑</dt>
            <dd class="mono">{{ team.doubtful }}</dd>
          </div>
        </dl>
      </div>
    </div>

    <div class="rs-dataset mono">dataset: {{ datasetId || '-' }}</div>

    <div class="rs-actions">
      <button class="ghost-btn ghost-btn-sm" type="button" @click="$emit('open-drawer')">查看完整名册 →</button>
      <button class="ghost-btn ghost-btn-sm" type="button" @click="$emit('switch-dataset')">切换数据集</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  summary: { type: Object, default: null },
  datasetId: { type: String, default: '' }
})

defineEmits(['open-drawer', 'switch-dataset'])

const teamRows = computed(() => {
  const home = props.summary?.home || {}
  const away = props.summary?.away || {}
  return [
    mapTeamRow('home', '主队', home),
    mapTeamRow('away', '客队', away)
  ]
})

const mapTeamRow = (role, label, team = {}) => {
  const injured = toCount(team.injured)
  const suspended = toCount(team.suspended)
  return {
    role,
    label,
    name: team.team_name || team.team_iso3 || '-',
    playersCount: toCount(team.players_count),
    avgOverall: toNumberOrNull(team.avg_overall),
    gkMax: toNumberOrNull(team.gk_max),
    unavailable: injured + suspended,
    doubtful: toCount(team.doubtful)
  }
}

const toCount = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

const toNumberOrNull = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

const formatNumber = (value, digits = 1) => {
  if (!Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(digits)
}
</script>

<style scoped>
.rs-card {
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  background: #FCFCFC;
  padding: 12px;
  min-width: 0;
}

.rs-card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #555;
  font-size: 13px;
  font-weight: 800;
  margin-bottom: 10px;
}

.rs-team-list {
  display: grid;
  gap: 10px;
}

.rs-team {
  border-top: 1px solid #EFEFEF;
  padding-top: 10px;
}

.rs-team:first-child {
  border-top: none;
  padding-top: 0;
}

.rs-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 0;
  font-size: 13px;
}

.rs-row b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rs-team-label {
  color: #FF4500;
  font-size: 12px;
  font-weight: 800;
}

.rs-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 8px 0 0;
}

.rs-stat {
  min-width: 0;
}

.rs-stat dt {
  display: block;
  color: #777;
  font-size: 11px;
  margin-bottom: 4px;
}

.rs-stat dd {
  margin: 0;
  color: #111;
  font-size: 16px;
  font-weight: 800;
  line-height: 1.1;
}

.rs-dataset {
  margin-top: 10px;
  color: #777;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rs-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.ghost-btn-sm {
  padding: 6px 10px;
  font-size: 12px;
}

@media (max-width: 560px) {
  .rs-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
