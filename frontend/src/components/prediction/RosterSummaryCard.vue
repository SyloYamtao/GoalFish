<template>
  <div class="rs-card">
    <div class="rs-card-title">
      <span>{{ t('prediction.rosterSummaryTitle') }}</span>
      <InfoTooltip
        align="right"
        :title="t('prediction.rosterSummaryTitle')"
        :text="t('prediction.rosterSummaryTooltip')"
      />
    </div>

    <div class="rs-team-list">
      <div class="rs-team" v-for="team in teamRows" :key="team.role">
        <div class="rs-row">
          <span class="rs-team-label">{{ team.label }}</span>
          <b :title="team.name">{{ team.name }}</b>
          <span class="mono">{{ t('prediction.peopleUnit', { count: team.playersCount }) }}</span>
        </div>

        <dl class="rs-stats">
          <div class="rs-stat">
            <dt>{{ t('prediction.averageAbility') }}</dt>
            <dd class="mono">{{ formatNumber(team.avgOverall, 1) }}</dd>
          </div>
          <div class="rs-stat">
            <dt>{{ t('prediction.goalkeeper') }}</dt>
            <dd class="mono">{{ formatNumber(team.gkMax, 0) }}</dd>
          </div>
          <div class="rs-stat">
            <dt>{{ t('prediction.unavailable') }}</dt>
            <dd class="mono">{{ team.unavailable }}</dd>
          </div>
          <div class="rs-stat">
            <dt>{{ t('prediction.doubtful') }}</dt>
            <dd class="mono">{{ team.doubtful }}</dd>
          </div>
        </dl>
      </div>
    </div>

    <div class="rs-dataset mono">dataset: {{ datasetId || '-' }}</div>

    <div class="rs-actions">
      <button class="ghost-btn ghost-btn-sm" type="button" @click="$emit('open-drawer')">{{ t('prediction.viewFullRoster') }}</button>
      <button class="ghost-btn ghost-btn-sm" type="button" @click="$emit('switch-dataset')">{{ t('prediction.switchDataset') }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  summary: { type: Object, default: null },
  datasetId: { type: String, default: '' }
})

defineEmits(['open-drawer', 'switch-dataset'])

const { t } = useI18n()

const teamRows = computed(() => {
  const home = props.summary?.home || {}
  const away = props.summary?.away || {}
  return [
    mapTeamRow('home', t('prediction.homeTeam'), home),
    mapTeamRow('away', t('prediction.awayTeam'), away)
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
