<template>
  <section class="lineup-pitch-module" :aria-label="t('prediction.lineupPitchAria')">
    <div class="lineup-pitch-header">
      <div>
        <span class="module-kicker">{{ t('prediction.expectedLineupsKicker') }}</span>
        <h3>{{ homeTeam }} {{ t('common.vs') }} {{ awayTeam }}</h3>
      </div>
      <div class="formation-summary">
        <span>{{ homeFormation }}</span>
        <strong>{{ t('prediction.lineupPitchTitle') }}</strong>
        <span>{{ awayFormation }}</span>
      </div>
    </div>

    <div v-if="hasLineup" class="pitch-scroll">
      <div class="pitch-surface">
        <div class="pitch-lines" aria-hidden="true">
          <span class="line halfway"></span>
          <span class="circle center-circle"></span>
          <span class="spot center-spot"></span>
          <span class="box penalty left"></span>
          <span class="box penalty right"></span>
          <span class="box goal left"></span>
          <span class="box goal right"></span>
          <span class="goal-mouth left"></span>
          <span class="goal-mouth right"></span>
        </div>

        <div class="team-label home-label">
          <strong>{{ homeTeam }}</strong>
          <span>{{ homeFormation }} · {{ confidenceLabel(home?.confidence) }}</span>
        </div>
        <div class="team-label away-label">
          <strong>{{ awayTeam }}</strong>
          <span>{{ awayFormation }} · {{ confidenceLabel(away?.confidence) }}</span>
        </div>

        <button
          v-for="player in positionedHomePlayers"
          :key="`home-${player.key}`"
          class="player-marker player-home"
          type="button"
          :class="[markerClass(player), { selected: selectedKey === `home-${player.key}` }]"
          :style="markerStyle(player)"
          :aria-label="playerAriaLabel(player)"
          @mouseenter="hoverPlayer(player)"
          @mouseleave="clearHoverPlayer"
          @focus="hoverPlayer(player)"
          @blur="clearHoverPlayer"
          @click="selectPlayer('home', player)"
        >
          <span class="player-score">{{ scoreLabel(player) }}</span>
          <span class="player-caption">{{ numberName(player) }}</span>
          <span class="player-flags" v-if="playerBadges(player).length">
            <i v-for="badge in playerBadges(player)" :key="badge" :title="badgeTitle(badge)">{{ badgeIcon(badge) }}</i>
          </span>
        </button>

        <button
          v-for="player in positionedAwayPlayers"
          :key="`away-${player.key}`"
          class="player-marker player-away"
          type="button"
          :class="[markerClass(player), { selected: selectedKey === `away-${player.key}` }]"
          :style="markerStyle(player)"
          :aria-label="playerAriaLabel(player)"
          @mouseenter="hoverPlayer(player)"
          @mouseleave="clearHoverPlayer"
          @focus="hoverPlayer(player)"
          @blur="clearHoverPlayer"
          @click="selectPlayer('away', player)"
        >
          <span class="player-score">{{ scoreLabel(player) }}</span>
          <span class="player-caption">{{ numberName(player) }}</span>
          <span class="player-flags" v-if="playerBadges(player).length">
            <i v-for="badge in playerBadges(player)" :key="badge" :title="badgeTitle(badge)">{{ badgeIcon(badge) }}</i>
          </span>
        </button>
      </div>
    </div>

    <div v-else class="lineup-empty">{{ t('prediction.lineupEmpty') }}</div>

    <div class="selected-player-panel" v-if="hasLineup">
      <template v-if="activePlayer">
        <strong>{{ activePlayer.name || t('prediction.unspecified') }}</strong>
        <span>{{ activePlayer.position || '-' }} · {{ activePlayer.role || t('prediction.unspecified') }} · {{ availabilityLabel(activePlayer.availability) }}</span>
        <small>{{ attributesText(activePlayer) }}</small>
        <small>{{ t('prediction.confidence') }}: {{ activePlayer.data_confidence || t('prediction.confidenceMediumValue') }}</small>
      </template>
      <template v-else>
        <strong>{{ t('prediction.lineupHoverTitle') }}</strong>
        <span>{{ t('prediction.lineupHoverText') }}</span>
      </template>
    </div>

    <div class="lineup-notes" v-if="lineupNotes.length">
      <span v-for="note in lineupNotes" :key="note">{{ note }}</span>
    </div>
    <div class="lineup-notes" v-else-if="inferredLayoutNotes.length">
      <span v-for="note in inferredLayoutNotes" :key="note">{{ note }}</span>
    </div>

    <div class="bench-strip" v-if="homeBench.length || awayBench.length">
      <div class="bench-team">
        <span>{{ homeTeam }} {{ t('prediction.bench') }}</span>
        <b v-for="player in homeBench" :key="`hb-${player.name}-${player.number}`">{{ numberName(player) }}</b>
      </div>
      <div class="bench-team away-bench">
        <span>{{ awayTeam }} {{ t('prediction.bench') }}</span>
        <b v-for="player in awayBench" :key="`ab-${player.name}-${player.number}`">{{ numberName(player) }}</b>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  home: { type: Object, default: () => ({}) },
  away: { type: Object, default: () => ({}) },
})

const selectedKey = ref('')
const selectedPlayer = ref(null)
const hoveredPlayer = ref(null)
const { t } = useI18n()

const homeTeam = computed(() => props.home?.team || t('prediction.homeTeam'))
const awayTeam = computed(() => props.away?.team || t('prediction.awayTeam'))
const homeFormation = computed(() => props.home?.formation || t('prediction.unspecified'))
const awayFormation = computed(() => props.away?.formation || t('prediction.unspecified'))
const homeBench = computed(() => Array.isArray(props.home?.bench) ? props.home.bench.slice(0, 9) : [])
const awayBench = computed(() => Array.isArray(props.away?.bench) ? props.away.bench.slice(0, 9) : [])
const hasLineup = computed(() => homePlayers.value.length > 0 || awayPlayers.value.length > 0)

const homePlayers = computed(() => Array.isArray(props.home?.players) ? props.home.players : [])
const awayPlayers = computed(() => Array.isArray(props.away?.players) ? props.away.players : [])
const lineupNotes = computed(() => [props.home?.notes, props.away?.notes].filter(Boolean))
const activePlayer = computed(() => hoveredPlayer.value || selectedPlayer.value)

const FORMATION_LAYOUTS = {
  '4-3-3': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'LCM', 'CM', 'RCM', 'LW', 'ST', 'RW'],
  '4-2-3-1': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'LDM', 'RDM', 'LAM', 'CAM', 'RAM', 'ST'],
  '4-4-2': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'LM', 'LCM', 'RCM', 'RM', 'LST', 'RST'],
  '3-4-3': ['GK', 'LCB', 'CB', 'RCB', 'LM', 'LCM', 'RCM', 'RM', 'LW', 'ST', 'RW'],
  '3-4-2-1': ['GK', 'LCB', 'CB', 'RCB', 'LM', 'LCM', 'RCM', 'RM', 'LAM', 'RAM', 'ST'],
  '3-5-2': ['GK', 'LCB', 'CB', 'RCB', 'LWB', 'LCM', 'CM', 'RCM', 'RWB', 'LST', 'RST'],
  '5-3-2': ['GK', 'LWB', 'LCB', 'CB', 'RCB', 'RWB', 'LCM', 'CM', 'RCM', 'LST', 'RST'],
  '4-3-1-2': ['GK', 'LB', 'LCB', 'RCB', 'RB', 'LCM', 'DM', 'RCM', 'AM', 'LST', 'RST'],
}

const SLOT_COORDS = {
  GK: [8, 50],
  LB: [22, 18], LWB: [30, 14], LCB: [20, 36], CB: [18, 50], RCB: [20, 64], RB: [22, 82], RWB: [30, 86],
  LDM: [34, 37], DM: [34, 50], RDM: [34, 63],
  LM: [42, 17], LCM: [42, 38], CM: [44, 50], RCM: [42, 62], RM: [42, 83],
  LAM: [52, 29], AM: [52, 50], CAM: [52, 50], RAM: [52, 71],
  LW: [62, 18], LST: [61, 40], ST: [64, 50], RST: [61, 60], RW: [62, 82],
}

const normalizeFormation = value => String(value || '').match(/\d-\d-\d(?:-\d)?/)?.[0] || ''
const halfPitchX = value => {
  const sourceMin = 8
  const sourceMax = 63
  const targetMin = 7
  const targetMax = 45
  const ratio = Math.max(0, Math.min(1, (Number(value) - sourceMin) / (sourceMax - sourceMin)))
  return targetMin + ratio * (targetMax - targetMin)
}

const inferredLayoutNotes = computed(() => {
  const notes = []
  if (homePlayers.value.length && (!normalizeFormation(homeFormation.value) || props.home?.formation_source === 'inferred')) {
    notes.push(t('prediction.inferredFormationNote', { team: homeTeam.value }))
  }
  if (awayPlayers.value.length && (!normalizeFormation(awayFormation.value) || props.away?.formation_source === 'inferred')) {
    notes.push(t('prediction.inferredFormationNote', { team: awayTeam.value }))
  }
  if (homePlayers.value.length > 0 && homePlayers.value.length < 11) {
    notes.push(t('prediction.incompleteLineupNote', { team: homeTeam.value }))
  }
  if (awayPlayers.value.length > 0 && awayPlayers.value.length < 11) {
    notes.push(t('prediction.incompleteLineupNote', { team: awayTeam.value }))
  }
  return notes
})

const fallbackSlot = (player, index) => {
  const pos = String(player?.position || '').toUpperCase()
  if (pos === 'GK') return [8, 50]
  if (['CB', 'LB', 'RB', 'FB', 'DF'].includes(pos)) return [22, 28 + (index % 5) * 11]
  if (['ST', 'CF', 'FW', 'WG', 'LW', 'RW'].includes(pos)) return [61, 30 + (index % 4) * 14]
  return [42, 28 + (index % 5) * 11]
}

const positionPlayers = (players, formation, side) => {
  const slots = FORMATION_LAYOUTS[normalizeFormation(formation)] || []
  return players.map((player, index) => {
    const slot = String(player.pitch_slot || slots[index] || '').toUpperCase()
    const base = SLOT_COORDS[slot] || fallbackSlot(player, index)
    const baseX = halfPitchX(base[0])
    const x = side === 'home' ? baseX : 100 - baseX
    const y = base[1]
    return { ...player, key: `${index}-${player.name || player.position || slot}`, x, y, slot }
  })
}

const positionedHomePlayers = computed(() => positionPlayers(homePlayers.value, homeFormation.value, 'home'))
const positionedAwayPlayers = computed(() => positionPlayers(awayPlayers.value, awayFormation.value, 'away'))

const markerStyle = player => ({ left: `${player.x}%`, top: `${player.y}%` })
const markerClass = player => ({
  'caption-above': Number(player?.y ?? 50) > 74,
})

const scoreLabel = player => {
  const value = Number(player.rating ?? player.overall)
  return Number.isFinite(value) ? value.toFixed(1) : '--'
}

const numberName = player => {
  const number = player?.number || '--'
  const rawName = String(player?.name || t('prediction.unspecified')).trim()
  const compactName = rawName.includes(' ') ? rawName.split(/\s+/).slice(-1)[0] : rawName
  return `${number}. ${compactName || t('prediction.unspecified')}`
}

const availabilityLabel = value => ({
  available: t('prediction.availability_available'),
  doubtful: t('prediction.availability_doubtful'),
  injured: t('prediction.availability_injured'),
  suspended: t('prediction.availability_suspended'),
}[String(value || '')] || value || t('prediction.unspecified'))

const playerBadges = player => {
  const flags = Array.isArray(player?.risk_flags) ? [...player.risk_flags] : []
  if (player?.is_captain) flags.unshift('captain')
  return [...new Set(flags)].slice(0, 3)
}

const badgeIcon = badge => ({ captain: 'C', doubtful: '!', injured: '+', suspended: 'S', low_confidence: '?' }[badge] || '!')
const badgeTitle = badge => ({
  captain: t('prediction.badge_captain'),
  doubtful: t('prediction.badge_doubtful'),
  injured: t('prediction.badge_injured'),
  suspended: t('prediction.badge_suspended'),
  low_confidence: t('prediction.badge_low_confidence'),
}[badge] || badge)

const attributesText = player => {
  const attrs = player?.key_attributes || {}
  const parts = Object.entries(attrs).slice(0, 3).map(([key, value]) => `${key} ${value}`)
  return parts.length ? parts.join(' · ') : t('prediction.attributesUnknown')
}

const confidenceLabel = value => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return t('prediction.confidenceUnknown')
  if (numeric >= 0.75) return t('prediction.confidenceHigh')
  if (numeric >= 0.55) return t('prediction.confidenceMedium')
  return t('prediction.confidenceLow')
}

const selectPlayer = (side, player) => {
  selectedKey.value = `${side}-${player.key}`
  selectedPlayer.value = player
  hoveredPlayer.value = player
}

const hoverPlayer = player => {
  hoveredPlayer.value = player
}

const clearHoverPlayer = () => {
  hoveredPlayer.value = null
}

const playerAriaLabel = player => {
  const parts = [
    player?.name || t('prediction.unspecified'),
    player?.position || t('prediction.positionUnknown'),
    player?.role || t('prediction.roleUnknown'),
    availabilityLabel(player?.availability),
  ]
  return parts.join(' · ')
}
</script>

<style scoped>
.lineup-pitch-module {
  margin: 18px 0 22px;
  color: #102018;
}

.lineup-pitch-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.module-kicker {
  display: block;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #607469;
}

.lineup-pitch-header h3 {
  margin: 2px 0 0;
  font-size: 20px;
  line-height: 1.2;
}

.formation-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #47584f;
}

.formation-summary strong {
  color: #12231a;
}

.pitch-scroll {
  overflow-x: auto;
  padding-bottom: 8px;
}

.pitch-surface {
  position: relative;
  width: 100%;
  min-width: 100%;
  aspect-ratio: 1.92 / 1;
  border: 2px solid rgba(255,255,255,0.82);
  border-radius: 8px;
  overflow: hidden;
  container-type: inline-size;
  background:
    repeating-linear-gradient(90deg, rgba(255,255,255,0.05) 0 9.09%, rgba(0,0,0,0.05) 9.09% 18.18%),
    linear-gradient(135deg, #176339, #0f4d31 48%, #195e3b);
  box-shadow: inset 0 0 0 1px rgba(10,40,24,0.25), 0 14px 30px rgba(11, 36, 23, 0.16);
}

.pitch-lines > span {
  position: absolute;
  border-color: rgba(255,255,255,0.72);
  pointer-events: none;
}

.halfway {
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255,255,255,0.72);
}

.center-circle {
  width: 16%;
  aspect-ratio: 1;
  border: 1px solid rgba(255,255,255,0.72);
  border-radius: 50%;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
}

.center-spot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(255,255,255,0.78);
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
}

.box {
  border: 1px solid rgba(255,255,255,0.72);
}

.penalty {
  width: 13%;
  height: 48%;
  top: 26%;
}

.penalty.left { left: 0; border-left: 0; }
.penalty.right { right: 0; border-right: 0; }

.goal {
  width: 5%;
  height: 24%;
  top: 38%;
}

.goal.left { left: 0; border-left: 0; }
.goal.right { right: 0; border-right: 0; }

.goal-mouth {
  width: 8px;
  height: 14%;
  top: 43%;
  border: 1px solid rgba(255,255,255,0.72);
}

.goal-mouth.left { left: -2px; }
.goal-mouth.right { right: -2px; }

.team-label {
  position: absolute;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: rgba(255,255,255,0.94);
  text-shadow: 0 1px 2px rgba(0,0,0,0.28);
  max-width: 260px;
}

.team-label strong {
  font-size: 14px;
}

.team-label span {
  font-size: 11px;
}

.home-label { left: 16px; }
.away-label { right: 16px; text-align: right; }

.player-marker {
  --marker-color: #f28b2e;
  position: absolute;
  width: 38px;
  height: 38px;
  transform: translate(-50%, -50%);
  border: 0;
  background: transparent;
  padding: 0;
  cursor: pointer;
  z-index: 2;
}

.player-score {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  border-radius: 50%;
  background: var(--marker-color);
  border: 2px solid rgba(255,255,255,0.92);
  box-shadow: 0 4px 12px rgba(0,0,0,0.28);
  color: #fff;
  font-weight: 900;
  font-size: 11px;
}

.player-away { --marker-color: #287bd8; }

.player-marker.selected .player-score {
  outline: 3px solid rgba(255,255,255,0.9);
  box-shadow: 0 0 0 5px rgba(0,0,0,0.2), 0 6px 16px rgba(0,0,0,0.34);
}

.player-caption {
  position: absolute;
  left: 50%;
  top: calc(100% + 4px);
  transform: translateX(-50%);
  display: block;
  width: 72px;
  min-height: 18px;
  padding: 2px 4px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 4px;
  background: rgba(9, 18, 13, 0.48);
  color: #fff;
  font-size: 9px;
  line-height: 1.1;
  font-weight: 800;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
  text-shadow: 0 1px 2px rgba(0,0,0,0.45);
}

.player-marker.caption-above .player-caption {
  top: auto;
  bottom: calc(100% + 4px);
}

.player-flags {
  position: absolute;
  left: 50%;
  top: -8px;
  transform: translateX(11px);
  display: flex;
  gap: 2px;
  pointer-events: none;
}

.player-flags i {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #111;
  color: #fff;
  font-style: normal;
  font-size: 8px;
  font-weight: 900;
}

.lineup-notes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.lineup-notes span {
  padding: 5px 8px;
  border-radius: 6px;
  background: #fff8e8;
  color: #7a5314;
  font-size: 12px;
  font-weight: 700;
}

.selected-player-panel {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 4px 12px;
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid #dfe6df;
  border-left: 4px solid #f28b2e;
  border-radius: 6px;
  background: linear-gradient(180deg, #fbfcfb 0%, #f4f7f4 100%);
}

.selected-player-panel span,
.selected-player-panel small {
  color: #516057;
}

.selected-player-panel strong {
  width: 100%;
  font-size: 14px;
  color: #13231a;
}

.selected-player-panel span {
  font-size: 12px;
}

.selected-player-panel small {
  font-size: 11px;
}

.bench-strip {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 12px;
}

.bench-team {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 9px;
  background: #f4f7f3;
  border: 1px solid #dfe6df;
  border-radius: 6px;
}

.bench-team span {
  width: 100%;
  font-weight: 800;
  font-size: 12px;
  color: #526158;
}

.bench-team b {
  max-width: 120px;
  padding: 4px 6px;
  border-radius: 5px;
  background: #fff;
  color: #1b2c22;
  font-size: 11px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.lineup-empty {
  padding: 18px;
  border: 1px dashed #cbd5cf;
  border-radius: 6px;
  color: #69766f;
  background: #f7f8f6;
}

@media (max-width: 760px) {
  .lineup-pitch-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .pitch-surface {
    min-width: 760px;
  }

  .player-score {
    width: 34px;
    height: 34px;
    font-size: 10px;
  }

  .player-caption {
    width: 68px;
    font-size: 9px;
  }

  .bench-strip {
    grid-template-columns: 1fr;
  }
}
</style>
