<template>
  <Teleport to="body">
    <transition name="drawer">
      <div
        v-if="open"
        class="drawer-mask"
        @click.self="close"
        @keydown="handleKeydown"
      >
        <aside
          ref="drawerRef"
          class="drawer"
          role="dialog"
          aria-modal="true"
          aria-labelledby="roster-drawer-title"
          tabindex="-1"
        >
          <header class="drawer-header">
            <h3 id="roster-drawer-title">{{ t('prediction.rosterTitle') }}</h3>
            <span class="mono drawer-id">dataset: {{ rosterPayload?.dataset_id || datasetId || '-' }}</span>
            <button class="drawer-close" type="button" :aria-label="t('prediction.closeRoster')" @click="close">×</button>
          </header>
          <div class="drawer-body">
            <div v-if="loading" class="drawer-empty">{{ t('prediction.rosterLoading') }}</div>
            <div v-else-if="error" class="drawer-error" role="alert">{{ error }}</div>
            <template v-else-if="teams.length">
              <section v-for="team in teams" :key="team.role" class="roster-team">
                <div class="roster-team-head">
                  <div>
                    <span>{{ team.role === 'home' ? t('prediction.homeTeam') : t('prediction.awayTeam') }}</span>
                    <b>{{ team.name || team.iso3 || '-' }}</b>
                    <small class="mono">{{ t('prediction.peopleUnit', { count: team.players?.length || 0 }) }}</small>
                  </div>
                  <div class="roster-issues">
                    <span>{{ t('prediction.injuredShort') }} {{ countStatus(team, 'injured') }}</span>
                    <span>{{ t('prediction.suspendedShort') }} {{ countStatus(team, 'suspended') }}</span>
                    <span>{{ t('prediction.doubtfulShort') }} {{ countStatus(team, 'doubtful') + countStatus(team, 'doubt') }}</span>
                  </div>
                </div>

                <table class="roster-table">
                  <thead>
                    <tr>
                      <th scope="col">{{ t('prediction.position') }}</th>
                      <th scope="col">{{ t('prediction.playerName') }}</th>
                      <th scope="col">{{ t('prediction.ability') }}</th>
                      <th scope="col">{{ t('prediction.status') }}</th>
                      <th scope="col">{{ t('prediction.expected') }}</th>
                      <th v-if="mode === 'run'" scope="col">{{ t('prediction.goals') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="player in sortedPlayers(team.players || [])" :key="player.id || player.name">
                      <td class="mono">{{ player.position || '-' }}</td>
                      <td>
                        <b>{{ player.name_zh || player.name || player.name_en || '-' }}</b>
                        <small v-if="player.shirt_number" class="mono">#{{ player.shirt_number }}</small>
                      </td>
                      <td class="mono">{{ player.derived?.overall ?? '-' }}</td>
                      <td :class="`roster-status-${availability(player)}`">{{ statusLabel(player) }}</td>
                      <td class="mono">{{ player.expected_role || '-' }}</td>
                      <td v-if="mode === 'run'" class="mono actor-stat-cell">
                        <span class="actor-stat-bar">
                          <i
                            class="actor-stat-bar-fill"
                            :class="{ 'actor-stat-top': topActorIds.includes(player.id) }"
                            :style="{ width: `${goalShare(player) * 100}%` }"
                          ></i>
                        </span>
                        {{ goalShare(player).toFixed(2) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </section>
            </template>
            <div v-else class="drawer-empty">{{ t('prediction.emptyRoster') }}</div>
          </div>
        </aside>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getPredictionConfigRoster, getPredictionRunRoster } from '../../api/prediction'
import { normalizedAvailability, topGoalShareIds } from '../../utils/step3Adapters'

const props = defineProps({
  open: { type: Boolean, default: false },
  mode: { type: String, default: 'config' },
  runId: { type: String, default: '' },
  configId: { type: String, default: '' },
  datasetId: { type: String, default: '' },
  roster: { type: Object, default: null },
  goalActorStats: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update:open', 'close'])
const { t } = useI18n()

const drawerRef = ref(null)
const loading = ref(false)
const error = ref('')
const fetchedRoster = ref(null)
const previousFocus = ref(null)

const rosterPayload = computed(() => props.roster || fetchedRoster.value)
const teams = computed(() => rosterPayload.value?.teams || [])
const topActorIds = computed(() => topGoalShareIds(rosterPayload.value || {}, 2))

const close = () => {
  emit('update:open', false)
  emit('close')
}

const loadRoster = async () => {
  if (props.roster || !props.open) return
  if (props.mode === 'run' && !props.runId) return
  if (props.mode !== 'run' && !props.configId) return

  loading.value = true
  error.value = ''
  try {
    const response = props.mode === 'run'
      ? await getPredictionRunRoster(props.runId)
      : await getPredictionConfigRoster(props.configId)
    fetchedRoster.value = response.data
  } catch (err) {
    error.value = err.message || t('prediction.rosterLoadFailed')
  } finally {
    loading.value = false
  }
}

const handleKeydown = (event) => {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab') return

  const focusables = drawerRef.value?.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  )
  if (!focusables?.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

const sortedPlayers = (players) => [...players].sort((a, b) => {
  const abilityDiff = playerOverall(b) - playerOverall(a)
  if (abilityDiff !== 0) return abilityDiff

  const roleDiff = roleRank(a) - roleRank(b)
  if (roleDiff !== 0) return roleDiff

  const positionDiff = String(a.position || '').localeCompare(String(b.position || ''))
  if (positionDiff !== 0) return positionDiff

  return playerName(a).localeCompare(playerName(b))
})

const playerOverall = (player) => {
  const value = Number(player?.derived?.overall)
  return Number.isFinite(value) ? value : -1
}

const roleRank = (player) => {
  if (player?.expected_role === 'starter') return 0
  if (player?.expected_role === 'bench') return 1
  return 2
}

const playerName = (player) => String(player?.name_zh || player?.name || player?.name_en || '')

const availability = (player) => normalizedAvailability(player)
const statusLabel = (player) => ({
  available: '✓',
  ok: '✓',
  doubtful: t('prediction.status_doubtful'),
  doubt: t('prediction.status_doubt'),
  injured: t('prediction.status_injured'),
  suspended: t('prediction.status_suspended'),
}[availability(player)] || availability(player))

const countStatus = (team, status) => (
  (team.players || []).filter(player => availability(player) === status).length
)

const goalShare = (player) => {
  const direct = Number(player.actor_stats?.goal_share)
  if (Number.isFinite(direct)) return Math.max(0, Math.min(1, direct))
  const override = Number(props.goalActorStats?.[player.id]?.goal_share)
  if (Number.isFinite(override)) return Math.max(0, Math.min(1, override))
  return 0
}

watch(() => props.open, async (open) => {
  if (open) {
    previousFocus.value = document.activeElement
    await loadRoster()
    await nextTick()
    drawerRef.value?.focus()
  } else {
    previousFocus.value?.focus?.()
  }
})

watch(() => [props.runId, props.configId, props.mode], () => {
  fetchedRoster.value = null
  if (props.open) loadRoster()
})
</script>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.25);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: min(520px, 100vw);
  height: 100%;
  background: #FFF;
  border-left: 1px solid #EAEAEA;
  display: flex;
  flex-direction: column;
  outline: none;
}

.drawer-header {
  padding: 16px 20px;
  border-bottom: 1px solid #EAEAEA;
  display: flex;
  align-items: center;
  gap: 12px;
  position: sticky;
  top: 0;
  background: #FFF;
  z-index: 1;
}

.drawer-header h3 {
  margin: 0;
  flex: 1;
  font-size: 18px;
}

.drawer-id {
  color: #777;
  font-size: 12px;
}

.drawer-close {
  border: none;
  background: transparent;
  font-size: 24px;
  cursor: pointer;
  color: #555;
}

.drawer-body {
  padding: 16px 20px 24px;
  overflow-y: auto;
}

.roster-team {
  margin-bottom: 18px;
}

.roster-team-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-end;
  margin-bottom: 8px;
}

.roster-team-head span {
  color: #FF4500;
  font-size: 12px;
  font-weight: 800;
  margin-right: 8px;
}

.roster-team-head b {
  margin-right: 8px;
}

.roster-team-head small,
.roster-issues {
  color: #777;
  font-size: 11px;
}

.roster-issues {
  display: flex;
  gap: 10px;
  color: #8A4B00;
}

.roster-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.roster-table thead {
  background: #111;
  color: #FFF;
  font-weight: 800;
}

.roster-table th,
.roster-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #EFEFEF;
}

.roster-table tbody tr:hover {
  background: #FCFCFC;
}

.roster-table td small {
  display: block;
  color: #777;
  font-size: 10px;
  margin-top: 2px;
}

.roster-status-available,
.roster-status-ok {
  color: #22863A;
}

.roster-status-doubt,
.roster-status-doubtful {
  color: #8A4B00;
}

.roster-status-injured,
.roster-status-suspended {
  color: #8A1F2D;
}

.actor-stat-cell {
  white-space: nowrap;
}

.actor-stat-bar {
  display: inline-block;
  width: 60px;
  height: 6px;
  background: #EFEFEF;
  border-radius: 2px;
  position: relative;
  margin-right: 6px;
  vertical-align: middle;
  overflow: hidden;
}

.actor-stat-bar-fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: #111;
  border-radius: 2px;
}

.actor-stat-top {
  background: #FF4500;
}

.drawer-empty,
.drawer-error {
  border: 1px dashed #DDD;
  border-radius: 8px;
  padding: 18px;
  color: #777;
  text-align: center;
}

.drawer-error {
  border-color: #F5C2C7;
  color: #8A1F2D;
  background: #FFF5F5;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s;
}

.drawer-enter-active .drawer,
.drawer-leave-active .drawer {
  transition: transform 0.2s;
}

.drawer-enter-from .drawer,
.drawer-leave-to .drawer {
  transform: translateX(100%);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}
</style>
