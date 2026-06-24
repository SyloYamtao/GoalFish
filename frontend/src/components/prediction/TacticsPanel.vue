<template>
  <section class="tactics-panel" :aria-label="t('prediction.tacticsAria')">
    <div class="tactics-head">
      <span>{{ t('prediction.tacticalPlanKicker') }}</span>
      <strong>{{ t('prediction.tacticsTitle') }}</strong>
    </div>

    <div class="tactics-grid">
      <article v-for="team in teams" :key="team.key" class="tactics-team">
        <div class="team-title">
          <strong>{{ team.name }}</strong>
          <span>{{ team.shape }} · {{ confidenceLabel(team.confidence) }}</span>
        </div>
        <div class="coach-line">{{ t('prediction.headCoach', { coach: team.coach }) }}</div>
        <dl>
          <div>
            <dt>{{ t('prediction.attack') }}</dt>
            <dd>{{ team.attacking }}</dd>
          </div>
          <div>
            <dt>{{ t('prediction.defense') }}</dt>
            <dd>{{ team.defensive }}</dd>
          </div>
          <div>
            <dt>{{ t('prediction.transition') }}</dt>
            <dd>{{ team.transition }}</dd>
          </div>
          <div>
            <dt>{{ t('prediction.setPiece') }}</dt>
            <dd>{{ team.setPiece }}</dd>
          </div>
          <div class="weakness-row">
            <dt>{{ t('prediction.riskPoint') }}</dt>
            <dd>{{ team.weakness }}</dd>
          </div>
        </dl>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  homeTeam: { type: String, default: '' },
  awayTeam: { type: String, default: '' },
  tactics: { type: Object, default: () => ({}) },
})

const { t } = useI18n()

const safeText = value => String(value || '').trim() || t('prediction.unspecified')
const confidenceLabel = value => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return t('prediction.confidenceUnknown')
  if (numeric >= 0.75) return t('prediction.confidenceHigh')
  if (numeric >= 0.55) return t('prediction.confidenceMedium')
  return t('prediction.confidenceLow')
}

const teamRow = (key, fallbackName) => {
  const row = props.tactics?.[key] || {}
  return {
    key,
    name: fallbackName,
    coach: safeText(row.coach),
    shape: safeText(row.base_shape),
    attacking: safeText(row.attacking_plan),
    defensive: safeText(row.defensive_plan),
    transition: safeText(row.transition_plan),
    setPiece: safeText(row.set_piece_plan),
    weakness: safeText(row.weakness),
    confidence: row.confidence,
  }
}

const teams = computed(() => [
  teamRow('home', props.homeTeam || t('prediction.homeTeam')),
  teamRow('away', props.awayTeam || t('prediction.awayTeam')),
])
</script>

<style scoped>
.tactics-panel {
  margin: 18px 0;
}

.tactics-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}

.tactics-head span {
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  color: #6b746f;
}

.tactics-head strong {
  font-size: 17px;
  color: #151d18;
}

.tactics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.tactics-team {
  border: 1px solid #dde5df;
  border-radius: 8px;
  background: #fbfcfa;
  padding: 14px;
}

.team-title {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}

.team-title strong {
  font-size: 16px;
  color: #132017;
}

.team-title span,
.coach-line {
  color: #647169;
  font-size: 12px;
}

.coach-line {
  margin-bottom: 12px;
}

dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

dl div {
  display: grid;
  grid-template-columns: 54px 1fr;
  gap: 10px;
  align-items: start;
}

dt {
  font-weight: 900;
  color: #24362b;
  font-size: 12px;
}

dd {
  margin: 0;
  color: #425047;
  font-size: 13px;
  line-height: 1.5;
}

.weakness-row {
  padding-top: 8px;
  border-top: 1px solid #e7ece8;
}

@media (max-width: 760px) {
  .tactics-grid {
    grid-template-columns: 1fr;
  }

  .team-title {
    flex-direction: column;
  }
}
</style>
