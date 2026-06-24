<template>
  <section class="key-matchups" :aria-label="t('prediction.keyMatchupsAria')">
    <div class="matchups-head">
      <span>{{ t('prediction.keyMatchupsKicker') }}</span>
      <strong>{{ t('prediction.keyMatchupsTitle') }}</strong>
    </div>

    <div v-if="rows.length" class="matchup-list">
      <article v-for="item in rows" :key="item.key" class="matchup-row" :class="`adv-${item.advantage}`">
        <div class="zone-pill">{{ item.zone }}</div>
        <div class="matchup-main">
          <strong>{{ item.homePlayer }}</strong>
          <span>{{ t('common.vs') }}</span>
          <strong>{{ item.awayPlayer }}</strong>
        </div>
        <div class="advantage-pill">{{ advantageText(item.advantage) }}</div>
        <p>{{ item.why }}</p>
      </article>
    </div>

    <div v-else class="matchup-empty">{{ t('prediction.matchupsEmpty') }}</div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  matchups: { type: Array, default: () => [] },
})

const { t } = useI18n()

const safeText = (value, fallback = t('prediction.unspecified')) => String(value || '').trim() || fallback

const rows = computed(() => props.matchups
  .filter(Boolean)
  .slice(0, 6)
  .map((item, index) => ({
    key: `${index}-${item.zone || item.home_player || item.away_player}`,
    zone: safeText(item.zone, t('prediction.zoneUnknown')),
    homePlayer: safeText(item.home_player, t('prediction.homePlayerUnknown')),
    awayPlayer: safeText(item.away_player, t('prediction.awayPlayerUnknown')),
    why: safeText(item.why_it_matters),
    advantage: ['home', 'away', 'even'].includes(item.advantage) ? item.advantage : 'even',
  })))

const advantageText = value => ({
  home: t('prediction.advantage_home'),
  away: t('prediction.advantage_away'),
  even: t('prediction.advantage_even'),
}[value] || t('prediction.advantage_even'))
</script>

<style scoped>
.key-matchups {
  margin: 18px 0;
}

.matchups-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}

.matchups-head span {
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  color: #6b746f;
}

.matchups-head strong {
  font-size: 17px;
  color: #151d18;
}

.matchup-list {
  display: grid;
  gap: 10px;
}

.matchup-row {
  display: grid;
  grid-template-columns: 74px 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid #dde5df;
  border-left: 4px solid #96a39a;
  border-radius: 8px;
  background: #fbfcfa;
}

.matchup-row.adv-home {
  border-left-color: #f28b2e;
}

.matchup-row.adv-away {
  border-left-color: #287bd8;
}

.zone-pill,
.advantage-pill {
  padding: 5px 8px;
  border-radius: 5px;
  background: #eef3ef;
  color: #33443a;
  font-size: 12px;
  font-weight: 900;
  text-align: center;
}

.matchup-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.matchup-main strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #17231c;
}

.matchup-main span {
  color: #7b877f;
  font-size: 12px;
  font-weight: 900;
}

.advantage-pill {
  background: #f7f2e8;
}

.matchup-row p {
  grid-column: 2 / 4;
  margin: 0;
  color: #536158;
  line-height: 1.45;
  font-size: 13px;
}

.matchup-empty {
  padding: 14px;
  border: 1px dashed #cbd5cf;
  border-radius: 6px;
  color: #69766f;
  background: #f7f8f6;
}

@media (max-width: 760px) {
  .matchup-row {
    grid-template-columns: 1fr;
  }

  .matchup-row p {
    grid-column: auto;
  }

  .zone-pill,
  .advantage-pill {
    width: fit-content;
  }
}
</style>
