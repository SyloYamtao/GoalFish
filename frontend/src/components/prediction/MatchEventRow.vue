<template>
  <div class="event-row" :class="rowClass">
    <div class="event-main">
      <span class="event-minute mono">{{ event.minute }}'</span>
      <span class="event-type-pill" :style="pillStyle">{{ eventTypeLabel(event.event_type || event.type) }}</span>
      <span class="event-desc">{{ event.description }}</span>
      <span v-if="scoreText" class="event-score mono">{{ scoreText }}</span>
    </div>

    <div class="event-meta" v-if="event.confidence !== undefined || provenanceText">
      <span class="event-confidence" v-if="event.confidence !== undefined">
        置信
        <ConfidenceBar :value="Number(event.confidence)" />
        <small class="mono">({{ Math.round(Number(event.confidence) || 0) }}%)</small>
      </span>
      <small class="mono event-provenance" v-if="provenanceText">
        {{ provenanceText }}
      </small>
    </div>

    <button
      v-if="event.actor_player"
      class="event-player-toggle"
      type="button"
      @click="playerOpen = !playerOpen"
      :aria-expanded="playerOpen"
    >
      球员卡 {{ playerOpen ? '▴' : '▾' }}
    </button>
    <transition name="slide-down">
      <div v-if="playerOpen" class="event-player-card">
        <div class="player-card-head">
          <b>{{ event.actor_player.name }}</b>
          <span class="mono">{{ event.actor_player.position }}</span>
        </div>
        <div class="player-card-ratings" v-if="ratingEntries.length">
          <span v-for="[key, value] in ratingEntries" :key="key">
            {{ ratingLabel(key) }} <b>{{ value }}</b>
          </span>
        </div>
        <div v-if="event.assist_player" class="player-card-assist">
          <small>助攻</small>
          <b>{{ event.assist_player.name }}</b>
          <span class="mono">{{ event.assist_player.position }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import ConfidenceBar from './ConfidenceBar.vue'
import { eventTypeLabel, scoreAfterText, seedShortCode } from '../../utils/step3Adapters'

const props = defineProps({
  event: { type: Object, required: true },
})

const playerOpen = ref(false)

const eventType = computed(() => props.event.event_type || props.event.type || '')
const scoreText = computed(() => scoreAfterText(props.event.score_after) || props.event.score || '')
const rowClass = computed(() => (
  String(eventType.value).includes('GOAL')
    ? 'event-row-goal'
    : `event-row-${String(eventType.value).toLowerCase()}`
))

const provenanceText = computed(() => {
  const scenarioKey = props.event.sample_provenance?.scenario_key || props.event.scenario_key
  const seed = props.event.sample_provenance?.sim_seed || props.event.sim_seed
  if (!scenarioKey && seed === undefined) return ''
  return `${scenarioKey || '-'} · seed ${seedShortCode(seed)}`
})

const ratingEntries = computed(() => Object.entries(props.event.actor_player?.rating_snapshot || {}))

const pillStyle = computed(() => {
  const type = eventType.value
  const cardColor = String(props.event.card_color || props.event.metadata?.card_color || '').toLowerCase()
  if (type === 'RED_CARD' || (type === 'CARD' && cardColor === 'red')) {
    return { background: '#8A1F2D', color: '#FFF' }
  }
  if (type === 'CARD' || type === 'YELLOW_CARD') {
    return { background: '#FFC400', color: '#111' }
  }
  return {}
})

const ratingLabel = (key) => ({
  overall: '总评',
  finishing: '终结',
  pace: '速度',
  dribbling: '盘带',
  passing: '传球',
  defense: '防守',
  gk: '门将',
}[key] || key)
</script>

<style scoped>
.event-row {
  border-bottom: 1px solid #EFEFEF;
  padding: 12px 14px;
  font-size: 13px;
}

.event-row:last-child {
  border-bottom: none;
}

.event-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.event-minute {
  color: #FF4500;
  font-weight: 800;
  width: 36px;
  flex: 0 0 auto;
}

.event-type-pill {
  background: #EFEFEF;
  border-radius: 3px;
  padding: 2px 6px;
  font-size: 11px;
  color: #555;
  text-transform: uppercase;
  flex: 0 0 auto;
}

.event-row-goal .event-type-pill {
  background: #111;
  color: #FFF;
}

.event-desc {
  flex: 1;
  color: #333;
  min-width: 0;
}

.event-score {
  font-weight: 800;
  background: #111;
  color: #FFF;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  flex: 0 0 auto;
}

.event-meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: #777;
  padding-left: 46px;
  flex-wrap: wrap;
}

.event-confidence {
  display: flex;
  align-items: center;
  gap: 6px;
}

.event-provenance {
  color: #999;
}

.event-player-toggle {
  margin-top: 4px;
  margin-left: 46px;
  border: none;
  background: transparent;
  font-size: 11px;
  color: #666;
  cursor: pointer;
  padding: 0;
}

.event-player-toggle:focus-visible {
  outline: 2px solid #111;
  outline-offset: 2px;
}

.event-player-card {
  margin: 8px 0 0 46px;
  padding: 10px 12px;
  background: #FCFCFC;
  border: 1px solid #EFEFEF;
  border-radius: 6px;
}

.player-card-head {
  display: flex;
  gap: 10px;
  align-items: center;
}

.player-card-ratings {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11px;
  color: #666;
}

.player-card-ratings b {
  color: #111;
}

.player-card-assist {
  margin-top: 6px;
  font-size: 11px;
  color: #666;
  display: flex;
  gap: 8px;
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: opacity .16s ease, transform .16s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

@media (max-width: 760px) {
  .event-main {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .event-desc {
    flex-basis: 100%;
    padding-left: 46px;
  }
}
</style>
