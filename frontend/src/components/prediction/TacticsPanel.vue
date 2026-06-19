<template>
  <section class="tactics-panel" aria-label="主教练战术思路">
    <div class="tactics-head">
      <span>TACTICAL PLAN</span>
      <strong>主教练战术思路</strong>
    </div>

    <div class="tactics-grid">
      <article v-for="team in teams" :key="team.key" class="tactics-team">
        <div class="team-title">
          <strong>{{ team.name }}</strong>
          <span>{{ team.shape }} · {{ confidenceLabel(team.confidence) }}</span>
        </div>
        <div class="coach-line">主教练：{{ team.coach }}</div>
        <dl>
          <div>
            <dt>进攻</dt>
            <dd>{{ team.attacking }}</dd>
          </div>
          <div>
            <dt>防守</dt>
            <dd>{{ team.defensive }}</dd>
          </div>
          <div>
            <dt>转换</dt>
            <dd>{{ team.transition }}</dd>
          </div>
          <div>
            <dt>定位球</dt>
            <dd>{{ team.setPiece }}</dd>
          </div>
          <div class="weakness-row">
            <dt>风险点</dt>
            <dd>{{ team.weakness }}</dd>
          </div>
        </dl>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  homeTeam: { type: String, default: '主队' },
  awayTeam: { type: String, default: '客队' },
  tactics: { type: Object, default: () => ({}) },
})

const safeText = value => String(value || '').trim() || '资料未明确'
const confidenceLabel = value => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '可信度 -'
  if (numeric >= 0.75) return '可信度 高'
  if (numeric >= 0.55) return '可信度 中'
  return '可信度 低'
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
  teamRow('home', props.homeTeam),
  teamRow('away', props.awayTeam),
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
