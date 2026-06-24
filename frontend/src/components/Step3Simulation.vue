<template>
  <div class="match-simulation-panel">
    <div class="simulation-scroll">
      <header class="simulation-header">
        <div class="header-copy">
          <span class="eyebrow mono">{{ t('step3.eyebrow') }}</span>
          <h2>{{ t('step3.title') }}</h2>
          <p>{{ projectData?.simulation_requirement || projectData?.project_name || t('step3.defaultSubtitle') }}</p>
          <div class="matchup-strip" :title="matchIdentity.matchName">
            <span>{{ t('step3.homeTeam') }} <b>{{ matchIdentity.home }}</b></span>
            <span class="mono">{{ t('common.vs') }}</span>
            <span>{{ t('step3.awayTeam') }} <b>{{ matchIdentity.away }}</b></span>
          </div>
        </div>

        <div class="action-controls">
          <button
            v-if="phase !== 2"
            class="action-btn primary"
            type="button"
            :disabled="isRunning || !currentPredictionConfigId || !projectData?.project_id"
            @click="startPrediction"
          >
            <span v-if="isRunning" class="spinner"></span>
            {{ isRunning ? t('step3.runningSimulation') : t('step3.startSimulation') }}
          </button>
          <button
            v-if="currentPredictionRunId"
            class="action-btn secondary"
            type="button"
            :disabled="isRunning || isGeneratingReport"
            @click="regenerateStep3"
          >
            {{ t('step3.regenerateSimulation') }}
          </button>
          <button
            v-if="phase === 2"
            class="action-btn primary"
            type="button"
            :disabled="isGeneratingReport"
            @click="handleNextStep"
          >
            <span v-if="isGeneratingReport" class="spinner"></span>
            {{ isGeneratingReport ? t('step3.generatingPredictionReport') : t('step3.generatePredictionReport') }}
            <span v-if="!isGeneratingReport">→</span>
          </button>
          <button class="action-btn secondary" type="button" @click="$emit('go-back')">{{ t('step3.backToConfig') }}</button>
        </div>
      </header>

      <section class="summary-strip" :aria-label="t('step3.statusAria')">
        <div class="summary-item summary-run">
          <span>{{ t('step3.runConfig') }}</span>
          <b class="mono">{{ currentPredictionRunId || t('step3.notCreated') }}</b>
          <small class="mono">CFG {{ currentPredictionConfigId || t('step3.notBound') }}</small>
        </div>
        <div class="summary-item">
          <span>{{ t('step3.phase') }}</span>
          <b>{{ phaseLabel }}</b>
        </div>
        <div class="summary-item">
          <span>{{ t('step3.model') }}</span>
          <b>{{ selectedScoreline?.model_name || '-' }}</b>
        </div>
        <div class="summary-item">
          <span>{{ t('step3.consensus') }}</span>
          <button
            class="meta-btn mono"
            type="button"
            :title="coachConsensusTooltip"
            :disabled="!coachReview"
            @click="openConsensusDialog"
          >
            {{ coachConsensusLabel }}
          </button>
        </div>
        <div class="summary-item">
          <span>{{ t('step3.budget') }}</span>
          <button
            class="meta-btn mono"
            type="button"
            :class="budgetClass"
            :title="budgetTooltip"
            @click="openBudgetDialog"
          >
            {{ budgetUsed }}/{{ budgetCap }}
          </button>
        </div>
        <div class="summary-item">
          <span>{{ t('step3.roster') }}</span>
          <button class="meta-btn mono" type="button" @click="openRosterDrawer">{{ t('step3.playersUnit', { count: rosterSummary.total }) }}</button>
        </div>
        <div class="summary-item">
          <span>{{ t('step3.seed') }}</span>
          <b class="mono">{{ simulationSeedShort }}</b>
        </div>
      </section>

      <div v-if="errorMessage" class="run-error" role="alert">
        <span>{{ t('step3.simulationFailed') }}</span>
        <p>{{ errorMessage }}</p>
      </div>

      <section v-if="phase === 1" class="run-progress-card" :aria-label="t('step3.progressAria')">
        <div class="run-progress-head">
          <div>
            <span class="mono">{{ t('step3.progressKicker') }}</span>
            <b>{{ progressTitle }}</b>
          </div>
          <strong class="mono">{{ progressPercent }}%</strong>
        </div>
        <div class="run-progress-track">
          <div class="run-progress-fill" :style="{ width: `${progressPercent}%` }"></div>
        </div>
        <p>{{ progressMessage }}</p>
      </section>

      <main class="simulation-workspace">
        <section class="scenario-panel">
          <div class="panel-title panel-title-spread">
            <div>
              <span class="mono">{{ t('step3.matrixKicker') }}</span>
              <b>{{ t('step3.matrixTitle') }}</b>
            </div>
            <em class="mono">{{ orderedScenarioCases.length }}/9</em>
          </div>
          <div v-if="scenarioCases.length === 0" class="empty-state">
            {{ t('step3.matrixEmpty') }}
          </div>
          <div v-else class="scenario-matrix">
            <button
              v-for="scenario in orderedScenarioCases"
              :key="scenario.id"
              class="scenario-cell"
              type="button"
              :class="{ active: selectedScenarioCaseId === scenario.id }"
              :aria-pressed="selectedScenarioCaseId === scenario.id"
              @click="selectScenario(scenario.id)"
            >
              <div class="scenario-head">
                <span class="scenario-title">{{ scenario.scenario_name || scenario.scenario_module }}</span>
                <span class="mono weight-pill">{{ scenarioWeight(scenario) }}</span>
              </div>
              <small class="mono">{{ scenarioKey(scenario) }}</small>

              <div class="scenario-card-score">
                <b class="mono">{{ scenario.most_likely_score || scenarioScore(scenario.id) }}</b>
                <span class="mono">{{ mostLikelyScoreProb(scenario) || t('step3.probabilityUnknown') }}</span>
              </div>

              <div class="state-line">
                <span :title="matchIdentity.homeLabel">{{ t('step3.homeTeam') }} {{ matchIdentity.home }} · {{ stateLabel(scenario.home_state) }}</span>
                <span :title="matchIdentity.awayLabel">{{ t('step3.awayTeam') }} {{ matchIdentity.away }} · {{ stateLabel(scenario.away_state) }}</span>
              </div>
              <p class="sample-line mono">{{ scenarioSampleLabel(scenario) }}</p>
            </button>
          </div>
        </section>

        <section class="scenario-detail-panel">
          <div class="selected-scenario-card">
            <div class="selected-scenario-main">
              <span class="mono">{{ selectedScenarioKey }}</span>
              <h3>{{ selectedScenario?.scenario_name || selectedScenario?.scenario_module || t('step3.matchProcess') }}</h3>
              <div class="state-line selected-state-line">
                <span>{{ t('step3.homeTeam') }} {{ matchIdentity.home }} · {{ stateLabel(selectedScenario?.home_state) }}</span>
                <span>{{ t('step3.awayTeam') }} {{ matchIdentity.away }} · {{ stateLabel(selectedScenario?.away_state) }}</span>
                <span>{{ t('step3.weight') }} {{ selectedScenarioWeight }}</span>
              </div>
            </div>

            <div class="selected-score-grid">
              <div>
                <span>{{ t('step3.mostLikelyScore') }}</span>
                <b class="mono">{{ selectedMostLikelyScore }}</b>
              </div>
              <div>
                <span>xG</span>
                <b class="mono">{{ formatXg(selectedScoreline?.home_xg) }}-{{ formatXg(selectedScoreline?.away_xg) }}</b>
              </div>
              <div>
                <span>{{ t('step3.wdl') }}</span>
                <b>{{ selectedWdlLine }}</b>
              </div>
            </div>

            <div class="selected-scenario-evidence">
              <div>
                <span>{{ t('step3.drivers') }}</span>
                <p>{{ selectedScenarioDrivers.join(' / ') || t('step3.monteCarloModalPath') }}</p>
              </div>
              <div>
                <span>{{ t('step3.risks') }}</span>
                <p>{{ selectedScenarioRisks.join(' / ') || selectedScenario?.scenario_space || '-' }}</p>
              </div>
            </div>

            <ModalTrajectoryFootnote
              :trajectory="selectedScenario?.modal_trajectory_summary"
              :n-sims="selectedScenario?.n_sims || statusPayload?.n_sims || 0"
            />
          </div>

          <div class="detail-tabs" role="tablist" :aria-label="t('step3.detailAria')">
            <button
              class="detail-tab"
              type="button"
              role="tab"
              :class="{ active: activeDetailTab === 'flow' }"
              :aria-selected="activeDetailTab === 'flow'"
              @click="activeDetailTab = 'flow'"
            >
              {{ t('step3.flowTab') }}
              <span class="mono">{{ selectedEvents.length }}</span>
            </button>
            <button
              class="detail-tab"
              type="button"
              role="tab"
              :class="{ active: activeDetailTab === 'review' }"
              :aria-selected="activeDetailTab === 'review'"
              @click="activeDetailTab = 'review'"
            >
              {{ t('step3.reviewTab') }}
              <span class="mono">{{ selectedNotes.length }}</span>
            </button>
          </div>

          <section v-show="activeDetailTab === 'flow'" class="detail-surface" role="tabpanel">
            <div class="panel-title">
              <span class="mono">{{ t('step3.matchFlowKicker') }}</span>
              <b>{{ t('step3.eventChain') }}</b>
            </div>

            <div v-if="selectedEvents.length === 0" class="empty-state">
              {{ t('step3.emptyEventChain') }}
            </div>
            <div v-else class="event-list">
              <MatchEventRow v-for="event in selectedEvents" :key="event.id" :event="event" />
            </div>
          </section>

          <section v-show="activeDetailTab === 'review'" class="detail-surface" role="tabpanel">
            <div class="panel-title">
              <span class="mono">{{ t('step3.modelReviewKicker') }}</span>
              <b>{{ t('step3.modelReview') }}</b>
            </div>

            <div class="review-grid">
              <div class="probability-card">
                <span>{{ t('step3.scoreProbabilityTop') }}</span>
                <div v-if="scoreDistribution.length === 0" class="mini-empty">-</div>
                <div v-else class="score-distribution">
                  <div v-for="row in scoreDistribution" :key="row.score" class="score-prob-row">
                    <b class="mono">{{ row.score }}</b>
                    <span>{{ formatPercent(row.probability) }}</span>
                  </div>
                </div>
              </div>

              <div class="coach-review-card">
                <div class="card-heading">
                  <span>{{ t('step3.coachReview') }}</span>
                  <button class="ghost-btn-xs" type="button" :disabled="!coachReview" @click="openConsensusDialog">{{ t('step3.details') }}</button>
                </div>
                <template v-if="coachReview">
                  <div class="coach-review-summary-line">
                    <span>{{ t('step3.consensus') }} <b class="mono">{{ coachReviewMeta.label }}</b></span>
                    <span>{{ t('step3.source') }} <b>{{ coachReviewMeta.source }}</b></span>
                    <span>{{ t('step3.formula') }} <b class="mono">{{ coachReviewMeta.formula }}</b></span>
                  </div>
                  <div class="vote-line">
                    <b>{{ t('step3.support') }} {{ coachReviewMeta.supportVotes }}</b>
                    <b>{{ t('step3.oppose') }} {{ coachReviewMeta.opposeVotes }}</b>
                    <b>{{ t('step3.observe') }} {{ coachReviewMeta.abstainVotes }}</b>
                  </div>
                  <div class="coach-review-role-list">
                    <article v-for="row in coachReviewPreviewRows" :key="`${row.role}-${row.verdict}`">
                      <div>
                        <b>{{ row.roleLabel }}</b>
                        <span>{{ row.verdictLabel }} · {{ t('step3.weight') }} {{ row.weight }} · {{ t('step3.confidence') }} {{ row.confidence === null ? '-' : `${row.confidence}%` }}</span>
                      </div>
                      <small>{{ row.sourceNote }}</small>
                      <p>{{ row.rationale || t('step3.noRationale') }}</p>
                    </article>
                  </div>
                  <p class="coach-review-footnote">
                    {{ t('step3.reviewFootnote', { delta: coachReviewMeta.confidenceDelta }) }}
                  </p>
                </template>
                <p v-else>{{ t('step3.emptyReview') }}</p>
              </div>

              <div class="review-card">
                <div class="card-heading">
                  <h4>{{ t('step3.reviewSpend') }}</h4>
                  <button class="ghost-btn-xs" type="button" @click="openBudgetDialog">{{ t('step3.details') }}</button>
                </div>
                <LLMBudgetMeter :ledger="budgetLedger" compact />
                <div class="review-card-stats">
                  <span><small>{{ t('step3.totalLatency') }}</small> <b class="mono">{{ formatMs(budgetLedger.total_latency_ms) }}</b></span>
                  <span><small>{{ t('step3.tokens') }}</small> <b class="mono">{{ budgetDetails.totalTokens }}</b></span>
                  <span><small>{{ t('step3.p95Latency') }}</small> <b class="mono">{{ formatMs(budgetLedger.p95_latency_ms) }}</b></span>
                </div>
              </div>

              <div class="review-card">
                <h4>{{ t('step3.rosterAvailability') }}</h4>
                <div class="roster-card-summary">
                  <div class="roster-card-row">
                    <span>{{ t('step3.homeTeam') }}</span>
                    <span class="mono">{{ rosterSummary.home.available }}/{{ rosterSummary.home.total }}</span>
                    <ConfidenceBar :value="availabilityPercent(rosterSummary.home)" />
                  </div>
                  <div class="roster-card-row">
                    <span>{{ t('step3.awayTeam') }}</span>
                    <span class="mono">{{ rosterSummary.away.available }}/{{ rosterSummary.away.total }}</span>
                    <ConfidenceBar :value="availabilityPercent(rosterSummary.away)" />
                  </div>
                </div>
                <div class="roster-card-issues">
                  <span v-if="rosterSummary.injured > 0">{{ t('prediction.injuredShort') }} <b class="mono">{{ rosterSummary.injured }}</b></span>
                  <span v-if="rosterSummary.suspended > 0">{{ t('prediction.suspendedShort') }} <b class="mono">{{ rosterSummary.suspended }}</b></span>
                  <span v-if="rosterSummary.doubtful > 0">{{ t('prediction.doubtfulShort') }} <b class="mono">{{ rosterSummary.doubtful }}</b></span>
                </div>
                <button class="ghost-btn-xs" type="button" @click="openRosterDrawer">{{ t('step3.fullRoster') }}</button>
              </div>
            </div>

            <section class="fallback-panel">
              <div class="fallback-panel-head">
                <div>
                  <span class="mono">{{ t('step3.narrativeFallbacksKicker') }}</span>
                  <h4>{{ t('step3.narrativeFallbacks') }}</h4>
                </div>
                <div class="fallback-actions">
                  <span class="fallback-counter">
                    {{ t('step3.currentAll', { current: fallbackPanel.currentCount, total: fallbackPanel.total }) }}
                  </span>
                  <button
                    class="ghost-btn-xs"
                    type="button"
                    :disabled="budgetFailureRows.length === 0"
                    @click="showAllFallbacks = !showAllFallbacks"
                  >
                    {{ showAllFallbacks ? t('step3.currentOnly') : t('step3.showAll') }}
                  </button>
                  <button class="ghost-btn-xs" type="button" @click="openBudgetDialog">{{ t('step3.budgetDetails') }}</button>
                </div>
              </div>

              <div v-if="fallbackPanel.reasonRows.length" class="fallback-reason-strip">
                <span v-for="row in fallbackPanel.reasonRows" :key="row.reason">
                  {{ row.reason }} <b class="mono">{{ row.count }}</b>
                </span>
              </div>
              <div v-if="fallbackPanel.visible.length === 0" class="mini-empty">
                {{ t('step3.emptyFallbacks') }}
              </div>
              <div v-else class="fallback-event-list">
                <article
                  v-for="row in fallbackPanel.visible"
                  :key="row.id"
                  class="fallback-event-card"
                  :class="{ clickable: row.event }"
                  @click="row.event && focusFallbackEvent(row)"
                >
                  <div class="fallback-event-top">
                    <b>{{ row.index }}. {{ row.eventLabel }}</b>
                    <span class="mono">{{ row.failure.reason || '-' }}</span>
                  </div>
                  <p>{{ row.event?.description || row.failure.scenario_key || '-' }}</p>
                  <div class="fallback-event-meta">
                    <small class="mono">{{ row.failure.scenario_key || row.event?.scenario_key || '-' }}</small>
                    <small>{{ row.fallbackLabel }}</small>
                    <button
                      v-if="row.event"
                      class="ghost-btn-xs"
                      type="button"
                      @click.stop="focusFallbackEvent(row)"
                    >
                      {{ t('step3.viewEvent') }}
                    </button>
                  </div>
                </article>
              </div>
            </section>

            <div class="note-list">
              <article v-for="note in selectedNotes" :key="note.id" class="note-card">
                <div class="note-header">
                  <span>{{ roleLabel(note.agent_role) }}</span>
                  <b class="mono">{{ note.confidence }}%</b>
                </div>
                <p>{{ note.claim }}</p>
                <small>{{ note.reasoning }}</small>
              </article>
            </div>
          </section>
        </section>
      </main>
    </div>

    <PlayerRosterDrawer
      v-model:open="rosterDrawerOpen"
      mode="run"
      :run-id="currentPredictionRunId || ''"
      :dataset-id="runRoster?.dataset_id || ''"
      :roster="runRoster"
      :goal-actor-stats="rosterGoalStats"
    />

    <transition name="modal">
      <div v-if="consensusDialogOpen" class="detail-modal-mask" @click.self="consensusDialogOpen = false">
        <section class="detail-modal" role="dialog" aria-modal="true" aria-labelledby="consensus-detail-title" @keydown.esc="consensusDialogOpen = false">
          <header class="detail-modal-header">
            <div>
              <span class="mono">{{ t('step3.consensusSourceKicker') }}</span>
              <h3 id="consensus-detail-title">{{ t('step3.consensusSourceTitle') }}</h3>
            </div>
            <button class="modal-close-btn" type="button" :aria-label="t('step3.closeConsensusDetails')" @click="consensusDialogOpen = false">×</button>
          </header>

          <div class="detail-modal-body">
            <div class="detail-kpi-grid">
              <div>
                <small>{{ t('step3.currentScenario') }}</small>
                <b class="mono">{{ selectedScenarioKey }}</b>
              </div>
              <div>
                <small>{{ t('step3.consensus') }}</small>
                <b class="mono">{{ coachReviewMeta.label }}</b>
              </div>
              <div>
                <small>{{ t('step3.source') }}</small>
                <b>{{ coachReviewMeta.source }}</b>
              </div>
              <div>
                <small>{{ t('step3.formula') }}</small>
                <b class="mono">{{ coachReviewMeta.formula }}</b>
              </div>
            </div>

            <p class="detail-explain">
              {{ t('step3.consensusExplain') }}
            </p>

            <div class="detail-section">
              <h4>{{ t('step3.roleReviewDetails') }}</h4>
              <div v-if="coachReviewMeta.reviewRows.length === 0" class="mini-empty">{{ t('step3.emptyRoleReviewDetails') }}</div>
              <div v-else class="detail-table">
                <div class="detail-row detail-row-head">
                  <span>{{ t('step3.role') }}</span>
                  <span>{{ t('step3.verdict') }}</span>
                  <span>{{ t('step3.weight') }}</span>
                  <span>{{ t('step3.confidence') }}</span>
                </div>
                <div v-for="row in coachReviewMeta.reviewRows" :key="`${row.role}-${row.verdict}`" class="detail-row">
                  <span>{{ row.roleLabel }}</span>
                  <span>{{ row.verdictLabel }}</span>
                  <span class="mono">{{ row.weight }}</span>
                  <span class="mono">{{ row.confidence === null ? '-' : `${row.confidence}%` }}</span>
                  <p>{{ row.rationale || t('step3.noRationale') }}</p>
                </div>
              </div>
            </div>

            <div class="detail-section">
              <h4>{{ t('step3.rawSummary') }}</h4>
              <p class="raw-summary">{{ coachReviewMeta.summary || t('step3.emptySummary') }}</p>
            </div>
          </div>
        </section>
      </div>
    </transition>

    <transition name="modal">
      <div v-if="budgetDialogOpen" class="detail-modal-mask" @click.self="budgetDialogOpen = false">
        <section class="detail-modal detail-modal-wide" role="dialog" aria-modal="true" aria-labelledby="budget-detail-title" @keydown.esc="budgetDialogOpen = false">
          <header class="detail-modal-header">
            <div>
              <span class="mono">{{ t('step3.budgetSourceKicker') }}</span>
              <h3 id="budget-detail-title">{{ t('step3.budgetCallDetails') }}</h3>
            </div>
            <button class="modal-close-btn" type="button" :aria-label="t('step3.closeBudgetDetails')" @click="budgetDialogOpen = false">×</button>
          </header>

          <div class="detail-modal-body">
            <div class="detail-kpi-grid">
              <div>
                <small>{{ t('step3.usedCap') }}</small>
                <b class="mono" :class="budgetClass">{{ budgetDetails.usedLabel }}</b>
              </div>
              <div>
                <small>{{ t('step3.spent') }}</small>
                <b class="mono">{{ budgetDetails.spent }}</b>
              </div>
              <div>
                <small>{{ t('step3.cacheHits') }}</small>
                <b class="mono">{{ budgetDetails.cached }}</b>
              </div>
              <div>
                <small>{{ t('step3.remaining') }}</small>
                <b class="mono">{{ budgetDetails.remaining }}</b>
              </div>
            </div>

            <p class="detail-explain">
              {{ t('step3.budgetExplain') }}
            </p>

            <div class="detail-section">
              <h4>{{ t('step3.byRole') }}</h4>
              <div v-if="budgetDetails.roleRows.length === 0" class="mini-empty">{{ t('step3.emptyCalls') }}</div>
              <div v-else class="detail-table">
                <div class="detail-row detail-row-head budget-role-row">
                  <span>{{ t('step3.role') }}</span>
                  <span>{{ t('step3.calls') }}</span>
                  <span>{{ t('step3.cache') }}</span>
                  <span>{{ t('step3.tokens') }}</span>
                </div>
                <div v-for="row in budgetDetails.roleRows" :key="row.role" class="detail-row budget-role-row">
                  <span>{{ row.roleLabel }}</span>
                  <span class="mono">{{ row.calls }}</span>
                  <span class="mono">{{ row.cached }}</span>
                  <span class="mono">{{ row.tokens }}</span>
                </div>
              </div>
            </div>

            <div class="detail-section">
              <h4>{{ t('step3.failuresFallback') }}</h4>
              <div class="failure-summary">
                <span v-for="row in budgetDetails.failureReasonRows" :key="row.reason">
                  {{ row.reason }} <b class="mono">{{ row.count }}</b>
                </span>
              </div>
              <div v-if="budgetFailureRows.length === 0" class="mini-empty">{{ t('step3.emptyFailures') }}</div>
              <div v-else class="failure-list">
                <article v-for="row in budgetFailureRows" :key="row.id">
                  <div class="failure-row-head">
                    <b>{{ row.index }}. {{ roleLabel(row.failure.role) }}</b>
                    <span class="mono">{{ row.failure.reason || '-' }}</span>
                  </div>
                  <p>{{ row.eventLabel }}</p>
                  <small v-if="row.event?.description">{{ row.event.description }}</small>
                  <small v-else-if="row.failure.scenario_key" class="mono">{{ row.failure.scenario_key }}</small>
                  <em>{{ row.fallbackLabel }}</em>
                  <em v-if="row.failure.error">{{ row.failure.error }}</em>
                </article>
              </div>
            </div>
          </div>
        </section>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  createPredictionReport,
  getAnalystNotes,
  getMatchEvents,
  getPredictionBudgetUsage,
  getPredictionConfig,
  getPredictionResult,
  getPredictionRunRoster,
  getPredictionStatus,
  getScorelines,
  getScenarioCases,
  getScenarioSpaces,
  getTeamStrengths,
  runPrediction,
} from '../api/prediction'
import { getProjectWorkflow } from '../api/projectWorkflow'
import ConfidenceBar from './prediction/ConfidenceBar.vue'
import LLMBudgetMeter from './prediction/LLMBudgetMeter.vue'
import MatchEventRow from './prediction/MatchEventRow.vue'
import ModalTrajectoryFootnote from './prediction/ModalTrajectoryFootnote.vue'
import PlayerRosterDrawer from './prediction/PlayerRosterDrawer.vue'
import {
  availabilitySummary,
  budgetUsageDetails,
  budgetUsageMeta,
  coachReviewSummary,
  fallbackPanelSummary,
  failureEventRows,
  formatDecimal,
  formatMs,
  formatPercent,
  matchTeamIdentity,
  roleLabel as roleLabelAdapter,
  seedShortCode,
  stateLabel as stateLabelAdapter,
} from '../utils/step3Adapters'
import { regenerateStepWithConfirm } from '../utils/workflowRegenerate.js'

const router = useRouter()
const { t, locale } = useI18n()

const props = defineProps({
  predictionRunId: String,
  predictionConfigId: String,
  projectData: Object,
  graphData: Object,
  systemLogs: { type: Array, default: () => [] },
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const currentPredictionRunId = ref(props.predictionRunId || null)
const currentPredictionConfigId = ref(props.predictionConfigId || null)
const phase = ref(props.predictionRunId ? 1 : 0)
const errorMessage = ref('')
const scenarioSpaces = ref([])
const scenarioCases = ref([])
const teamStrengths = ref([])
const scorelines = ref([])
const matchEvents = ref([])
const analystNotes = ref([])
const predictionResult = ref(null)
const predictionConfigSnapshot = ref(null)
const selectedScenarioCaseId = ref(null)
const statusPayload = ref(null)
const budgetLedger = ref({})
const runRoster = ref(null)
const rosterDrawerOpen = ref(false)
const consensusDialogOpen = ref(false)
const budgetDialogOpen = ref(false)
const isGeneratingReport = ref(false)
const activeDetailTab = ref('flow')
const showAllFallbacks = ref(false)
const pollTimer = ref(null)
const isLoadingArtifacts = ref(false)
const workflowLoaded = ref(false)

const isRunning = computed(() => phase.value === 1)
const progressPercent = computed(() => Math.max(0, Math.min(100, Number(statusPayload.value?.progress_percent || 0))))
const progressTitle = computed(() => phaseLabel.value)
const progressMessage = computed(() => {
  const messages = statusPayload.value?.metadata?.progress_messages || []
  const latest = Array.isArray(messages) ? messages[messages.length - 1] : null
  if (latest?.message) return latest.message
  if (statusPayload.value?.status === 'queued') return t('step3.phaseQueued')
  if (statusPayload.value?.status === 'running') return t('step3.phaseRunning')
  return t('step3.phaseReady')
})
const phaseLabel = computed(() => {
  if (phase.value === 2) return t('common.completed')
  if (phase.value === 1) return phaseDisplayName(statusPayload.value?.current_phase || statusPayload.value?.status)
  return currentPredictionConfigId.value ? t('common.ready') : t('step3.notBound')
})

const orderedScenarioCases = computed(() => {
  const order = [
    'home_overperform_away_overperform',
    'home_overperform_away_normal',
    'home_overperform_away_underperform',
    'home_normal_away_overperform',
    'home_normal_away_normal',
    'home_normal_away_underperform',
    'home_underperform_away_overperform',
    'home_underperform_away_normal',
    'home_underperform_away_underperform',
  ]
  return [...scenarioCases.value].sort((a, b) => {
    const aIndex = order.indexOf(scenarioKey(a))
    const bIndex = order.indexOf(scenarioKey(b))
    return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex)
  })
})

const selectedScenario = computed(() => (
  scenarioCases.value.find(item => item.id === selectedScenarioCaseId.value) || null
))

const selectedScoreline = computed(() => (
  scorelines.value.find(item => item.scenario_case_id === selectedScenarioCaseId.value) || null
))

const selectedScenarioKey = computed(() => (
  selectedScenario.value ? scenarioKey(selectedScenario.value) : '-'
))

const selectedScenarioWeight = computed(() => (
  selectedScenario.value ? scenarioWeight(selectedScenario.value) : '-'
))

const selectedMostLikelyScore = computed(() => (
  selectedScenario.value?.most_likely_score
  || selectedScoreline.value?.most_likely_score
  || scenarioScore(selectedScenarioCaseId.value)
  || '-'
))

const selectedScenarioDrivers = computed(() => scenarioDrivers(selectedScenario.value))
const selectedScenarioRisks = computed(() => scenarioRisks(selectedScenario.value))

const selectedEvents = computed(() => (
  matchEvents.value
    .filter(event => event.scenario_case_id === selectedScenarioCaseId.value)
    .sort((a, b) => Number(a.minute || 0) - Number(b.minute || 0))
))

const selectedNotes = computed(() => (
  analystNotes.value.filter(note => note.scenario_case_id === selectedScenarioCaseId.value)
))

const coachReview = computed(() => {
  const note = selectedNotes.value.find(item => item.agent_role === 'coach_review')
  return note?.metadata?.coach_review_summary || null
})

const coachReviewMeta = computed(() => coachReviewSummary(coachReview.value, budgetLedger.value || {}, t))
const coachReviewPreviewRows = computed(() => coachReviewMeta.value.reviewRows.slice(0, 3))

const coachConsensusLabel = computed(() => {
  if (!coachReview.value) return '-'
  return coachReviewMeta.value.label
})

const coachConsensusTooltip = computed(() => {
  if (!coachReview.value) return t('step3.emptyCoachReviewTooltip')
  return t('step3.coachReviewTooltip', { formula: coachReviewMeta.value.formula, label: coachReviewMeta.value.label })
})

const selectedWdlLine = computed(() => {
  const wdl = selectedScenario.value?.win_draw_loss_probability || {}
  const home = selectedScoreline.value?.home_win_probability ?? wdl.home ?? wdl.home_win ?? wdl.home_win_probability
  const draw = selectedScoreline.value?.draw_probability ?? wdl.draw ?? wdl.draw_probability
  const away = selectedScoreline.value?.away_win_probability ?? wdl.away ?? wdl.away_win ?? wdl.away_win_probability
  if (home === undefined && draw === undefined && away === undefined) return '-'
  return t('step3.wdlLine', {
    home: formatPercent(home),
    draw: formatPercent(draw),
    away: formatPercent(away),
  })
})

const scoreDistribution = computed(() => (
  normalizeScoreDistribution(selectedScoreline.value?.scoreline_distribution || selectedScenario.value?.scoreline_distribution).slice(0, 5)
))

const budgetMeta = computed(() => budgetUsageMeta(budgetLedger.value || {}))
const budgetUsed = computed(() => budgetMeta.value.used)
const budgetCap = computed(() => budgetMeta.value.cap)
const budgetClass = computed(() => budgetMeta.value.className)
const budgetDetails = computed(() => budgetUsageDetails(budgetLedger.value || {}, t))
const budgetFailureRows = computed(() => failureEventRows(budgetDetails.value.failures, matchEvents.value, t))
const fallbackPanel = computed(() => fallbackPanelSummary(budgetFailureRows.value, selectedScenarioKey.value, showAllFallbacks.value))
const budgetTooltip = computed(() => t('step3.budgetTooltip', { used: budgetDetails.value.usedLabel, remaining: budgetDetails.value.remaining }))
const rosterSummary = computed(() => availabilitySummary(runRoster.value || {}))
const matchIdentity = computed(() => matchTeamIdentity({
  statusPayload: statusPayload.value || {},
  predictionConfig: predictionConfigSnapshot.value || {},
  predictionResult: predictionResult.value || {},
  teamStrengths: teamStrengths.value,
  roster: runRoster.value || {},
  t,
}))
const simulationSeedShort = computed(() => seedShortCode(statusPayload.value?.simulation_seed || predictionResult.value?.metadata?.simulation_seed))
const rosterGoalStats = computed(() => {
  const stats = {}
  for (const team of runRoster.value?.teams || []) {
    for (const player of team.players || []) {
      if (player.id) stats[player.id] = player.actor_stats || {}
    }
  }
  return stats
})

const addLog = (message) => emit('add-log', message)

const resetRunState = () => {
  stopStatusPolling()
  currentPredictionRunId.value = null
  phase.value = currentPredictionConfigId.value ? 0 : 0
  statusPayload.value = null
  scenarioSpaces.value = []
  scenarioCases.value = []
  teamStrengths.value = []
  scorelines.value = []
  matchEvents.value = []
  analystNotes.value = []
  predictionResult.value = null
  selectedScenarioCaseId.value = null
  budgetLedger.value = {}
  runRoster.value = null
  activeDetailTab.value = 'flow'
}

const reconcileActiveWorkflow = async () => {
  if (!props.projectData?.project_id) return false
  try {
    const response = await getProjectWorkflow(props.projectData.project_id)
    const active = response.data?.active_artifacts || {}
    workflowLoaded.value = true

    if (active.prediction_config_id) {
      currentPredictionConfigId.value = active.prediction_config_id
    }

    if (!active.prediction_run_id) {
      if (currentPredictionRunId.value) {
        addLog(t('step3.logNoActiveRun'))
      }
      resetRunState()
      emit('update-status', currentPredictionConfigId.value ? 'processing' : 'error')
      errorMessage.value = currentPredictionConfigId.value
        ? ''
        : t('step3.missingStep2Config')
      return false
    }

    if (currentPredictionRunId.value && currentPredictionRunId.value !== active.prediction_run_id) {
      addLog(t('step3.logOldRunSwitched'))
    }
    currentPredictionRunId.value = active.prediction_run_id
    return true
  } catch (err) {
    addLog(t('step3.logActiveWorkflowFailed', { error: err.message }))
    return Boolean(currentPredictionRunId.value)
  }
}

const recoverPredictionConfigFromRun = async () => {
  if (!currentPredictionRunId.value || currentPredictionConfigId.value) return Boolean(currentPredictionConfigId.value)
  try {
    const statusRes = await getPredictionStatus(currentPredictionRunId.value)
    statusPayload.value = statusRes.data || statusPayload.value
    currentPredictionConfigId.value = statusRes.data?.prediction_config_id || currentPredictionConfigId.value
    return Boolean(currentPredictionConfigId.value)
  } catch (err) {
    addLog(t('step3.logRestoreConfigFailed', { error: err.message }))
    return false
  }
}

const regenerateStep3 = async () => {
  if (!props.projectData?.project_id || !currentPredictionRunId.value) return
  errorMessage.value = ''
  try {
    const regenerated = await regenerateStepWithConfirm({
      projectId: props.projectData.project_id,
      step: 3,
      reason: 'step3_rerun',
      t,
      onBefore: () => {
        resetRunState()
        emit('update-status', 'processing')
        addLog(t('step3.logStep3Regenerated'))
      },
    })
    if (!regenerated) return
  } catch (err) {
    errorMessage.value = err.message || t('step3.regenerateFailed')
    emit('update-status', 'error')
    addLog(t('step3.logSimulationFailed', { error: errorMessage.value }))
  }
}

const startPrediction = async () => {
  if (!props.projectData?.project_id || !currentPredictionConfigId.value || isRunning.value) return

  errorMessage.value = ''
  phase.value = 1
  statusPayload.value = {
    status: 'queued',
    current_phase: 'queued',
    progress_percent: 1,
    metadata: {
      progress_messages: [{ message: t('step3.queueEntering'), progress_percent: 1 }],
    },
  }
  emit('update-status', 'processing')
  addLog(t('step3.logStartWithConfig', { id: currentPredictionConfigId.value }))

  try {
    const response = await runPrediction(props.projectData.project_id, {
      prediction_config_id: currentPredictionConfigId.value,
      async: true,
    })

    currentPredictionRunId.value = response.data.prediction_run_id
    currentPredictionConfigId.value = response.data.prediction_config_id || currentPredictionConfigId.value
    statusPayload.value = response.data || statusPayload.value
    addLog(t('step3.logQueued', { id: currentPredictionRunId.value }))
    startStatusPolling()

    router.replace({
      name: 'SimulationRun',
      params: {
        projectId: props.projectData.project_id,
        predictionRunId: currentPredictionRunId.value,
      },
      query: { prediction_config_id: currentPredictionConfigId.value },
    })
  } catch (err) {
    errorMessage.value = err.message || 'unknown error'
    phase.value = 0
    emit('update-status', 'error')
    addLog(t('step3.logSimulationFailed', { error: errorMessage.value }))
  }
}

const startStatusPolling = () => {
  stopStatusPolling()
  if (!currentPredictionRunId.value) return
  pollPredictionStatus()
  pollTimer.value = window.setInterval(pollPredictionStatus, 2500)
}

const stopStatusPolling = () => {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

const pollPredictionStatus = async () => {
  if (!currentPredictionRunId.value || isLoadingArtifacts.value) return
  try {
    const statusRes = await getPredictionStatus(currentPredictionRunId.value)
    statusPayload.value = statusRes.data || null
    currentPredictionConfigId.value = statusRes.data?.prediction_config_id || currentPredictionConfigId.value
    if (statusRes.data?.status === 'completed') {
      stopStatusPolling()
      await loadPredictionArtifacts()
    } else if (statusRes.data?.status === 'failed') {
      stopStatusPolling()
      errorMessage.value = statusRes.data?.error || t('step3.simulationFailed')
      phase.value = 0
      emit('update-status', 'error')
      addLog(t('step3.logSimulationFailed', { error: errorMessage.value }))
    }
  } catch (err) {
    addLog(t('step3.logProgressFailed', { error: err.message }))
  }
}

const loadPredictionArtifacts = async () => {
  if (!currentPredictionRunId.value) return

  phase.value = 1
  isLoadingArtifacts.value = true
  emit('update-status', 'processing')

  try {
    const [
      statusRes,
      spacesRes,
      casesRes,
      strengthsRes,
      scorelinesRes,
      eventsRes,
      notesRes,
      resultRes,
      rosterRes,
      budgetRes,
    ] = await Promise.all([
      getPredictionStatus(currentPredictionRunId.value),
      getScenarioSpaces(currentPredictionRunId.value),
      getScenarioCases(currentPredictionRunId.value),
      getTeamStrengths(currentPredictionRunId.value),
      getScorelines(currentPredictionRunId.value),
      getMatchEvents(currentPredictionRunId.value),
      getAnalystNotes(currentPredictionRunId.value),
      getPredictionResult(currentPredictionRunId.value),
      getPredictionRunRoster(currentPredictionRunId.value).catch(err => ({ data: null, optionalError: err })),
      getPredictionBudgetUsage(currentPredictionRunId.value).catch(err => ({ data: { ledger: {} }, optionalError: err })),
    ])

    currentPredictionConfigId.value = statusRes.data?.prediction_config_id || currentPredictionConfigId.value
    statusPayload.value = statusRes.data || null
    predictionConfigSnapshot.value = {
      ...(predictionConfigSnapshot.value || {}),
      match_name: statusRes.data?.match_name,
      home_team: statusRes.data?.home_team,
      away_team: statusRes.data?.away_team,
    }
    scenarioSpaces.value = spacesRes.data?.scenario_spaces || []
    scenarioCases.value = casesRes.data?.scenario_cases || []
    teamStrengths.value = strengthsRes.data?.team_strengths || []
    scorelines.value = scorelinesRes.data?.scorelines || []
    matchEvents.value = eventsRes.data?.match_events || []
    analystNotes.value = notesRes.data?.analyst_notes || []
    predictionResult.value = resultRes.data || null
    runRoster.value = rosterRes.data || null
    budgetLedger.value = budgetRes.data?.ledger || {}

    if (rosterRes.optionalError) addLog(t('step3.logRosterUnavailable', { error: rosterRes.optionalError.message }))
    if (budgetRes.optionalError) addLog(t('step3.logBudgetUnavailable', { error: budgetRes.optionalError.message }))

    selectDefaultScenario()

    if (statusRes.data?.status === 'completed') {
      phase.value = 2
      emit('update-status', 'completed')
      addLog(t('step3.logComplete'))
    } else if (statusRes.data?.status === 'failed') {
      phase.value = 0
      emit('update-status', 'error')
    }
  } catch (err) {
    errorMessage.value = err.message || 'unknown error'
    phase.value = 0
    emit('update-status', 'error')
    addLog(t('step3.logLoadArtifactsFailed', { error: errorMessage.value }))
  } finally {
    isLoadingArtifacts.value = false
  }
}

const loadPredictionConfigSnapshot = async () => {
  if (!currentPredictionConfigId.value) return
  try {
    const response = await getPredictionConfig(currentPredictionConfigId.value)
    predictionConfigSnapshot.value = response.data || null
  } catch (err) {
    addLog(t('step3.logTeamNamesUnavailable', { error: err.message }))
  }
}

const selectDefaultScenario = () => {
  if (selectedScenarioCaseId.value && scenarioCases.value.some(item => item.id === selectedScenarioCaseId.value)) return
  const baseline = scenarioCases.value.find(item => scenarioKey(item) === 'home_normal_away_normal')
  selectedScenarioCaseId.value = baseline?.id || scenarioCases.value[0]?.id || null
}

const selectScenario = (scenarioId) => {
  selectedScenarioCaseId.value = scenarioId
  activeDetailTab.value = 'flow'
}

const handleNextStep = async () => {
  if (!currentPredictionRunId.value) return
  isGeneratingReport.value = true
  addLog(t('step3.logStartReport'))
  try {
    const response = await createPredictionReport(currentPredictionRunId.value)
    const reportId = response.data.report_id
    addLog(t('step3.logReportGenerated', { id: reportId }))
    emit('next-step', { reportId, predictionRunId: currentPredictionRunId.value, predictionConfigId: currentPredictionConfigId.value })
    router.push({ name: 'Report', params: { reportId } })
  } catch (err) {
    errorMessage.value = err.message || 'unknown error'
    emit('update-status', 'error')
    addLog(t('step3.logReportFailed', { error: errorMessage.value }))
  } finally {
    isGeneratingReport.value = false
  }
}

const scenarioKey = (scenario) => scenario?.scenario_key || scenario?.metadata?.scenario_key || '-'

const phaseDisplayName = (phase) => {
  const labels = {
    queued: t('step3.phaseQueuedShort'),
    loading_config: t('step3.phaseLoadingConfig'),
    running_simulation: t('step3.phaseRunningSimulation'),
    persisting_artifacts: t('step3.phaseSavingArtifacts'),
    completed: t('common.completed'),
    failed: t('common.failed'),
    running: t('common.running'),
  }
  return labels[phase] || phase || t('common.running')
}

const scenarioScore = (scenarioCaseId) => (
  scorelines.value.find(item => item.scenario_case_id === scenarioCaseId)?.most_likely_score || '-'
)

const scenarioWeight = (scenario) => {
  const numeric = Number(scenario?.weight)
  if (!Number.isFinite(numeric)) return '-'
  return `${Math.round(numeric <= 1 ? numeric * 100 : numeric)}%`
}

const scenarioSampleLabel = (scenario) => {
  const nSims = Number(scenario?.n_sims || statusPayload.value?.n_sims || 0)
  const nSimsLabel = nSims > 0 ? nSims.toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US') : '-'
  const firstGoal = scenario?.modal_trajectory_summary?.first_goal_minute
  return t('step3.sampleLabel', {
    nSims: nSimsLabel,
    firstGoal: firstGoal ? t('step3.firstGoalSuffix', { minute: firstGoal }) : '',
  })
}

const scenarioDrivers = (scenario) => (
  scenario?.key_drivers || scenario?.metadata?.key_drivers || scenario?.evidence?.key_drivers || []
)

const scenarioRisks = (scenario) => (
  scenario?.risk_factors || scenario?.metadata?.risk_factors || scenario?.evidence?.risk_factors || []
)

const mostLikelyScoreProb = (scenario) => {
  const score = scenario?.most_likely_score || scenarioScore(scenario?.id)
  const row = normalizeScoreDistribution(scenario?.scoreline_distribution).find(item => item.score === score)
  return row ? formatPercent(row.probability) : ''
}

const normalizeScoreDistribution = (input) => {
  if (Array.isArray(input)) {
    return input.map(row => ({
      score: row.score || row.scoreline || '-',
      probability: Number(row.probability ?? row.prob ?? 0),
    })).filter(row => row.score !== '-')
  }
  if (input && typeof input === 'object') {
    return Object.entries(input).map(([score, probability]) => ({ score, probability: Number(probability || 0) }))
  }
  return []
}

const roleLabel = (role) => roleLabelAdapter(role, t)
const stateLabel = (state) => stateLabelAdapter(state, t)
const formatXg = (value) => formatDecimal(value, 2)
const openRosterDrawer = () => {
  rosterDrawerOpen.value = true
}

const openConsensusDialog = () => {
  if (coachReview.value) consensusDialogOpen.value = true
}

const openBudgetDialog = () => {
  budgetDialogOpen.value = true
}

const focusFallbackEvent = (row) => {
  const event = row?.event
  if (!event) return
  if (event.scenario_case_id && event.scenario_case_id !== selectedScenarioCaseId.value) {
    selectedScenarioCaseId.value = event.scenario_case_id
  }
  activeDetailTab.value = 'flow'
}

const availabilityPercent = (team) => {
  if (!team?.total) return 0
  return (team.available / team.total) * 100
}

watch(() => props.predictionRunId, (value) => {
  if (value && value !== currentPredictionRunId.value) {
    currentPredictionRunId.value = value
    loadPredictionArtifacts()
  } else if (!value && currentPredictionRunId.value) {
    resetRunState()
  }
})

watch(() => props.predictionConfigId, (value) => {
  if (value) {
    currentPredictionConfigId.value = value
    loadPredictionConfigSnapshot()
  }
})

onMounted(() => {
  addLog(t('step3.logInit'))
  loadPredictionConfigSnapshot()
  reconcileActiveWorkflow().then(async (hasActiveRun) => {
    await recoverPredictionConfigFromRun()
    if (hasActiveRun && currentPredictionRunId.value) {
      pollPredictionStatus()
      startStatusPolling()
    } else if (!currentPredictionConfigId.value) {
      emit('update-status', 'error')
      errorMessage.value = t('step3.missingConfigError')
    } else {
      emit('update-status', 'processing')
    }
  })
})

watch(() => props.projectData?.project_id, (projectId) => {
  if (projectId && !workflowLoaded.value) {
    reconcileActiveWorkflow()
  }
})

onUnmounted(() => {
  stopStatusPolling()
})
</script>

<style scoped>
.match-simulation-panel {
  container-type: inline-size;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #F6F7F5;
  color: #111;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.simulation-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.simulation-header,
.summary-item,
.scenario-panel,
.selected-scenario-card,
.detail-tabs,
.detail-surface {
  background: #FFF;
  border: 1px solid #E2E6DE;
  border-radius: 8px;
}

.simulation-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  padding: 18px;
}

.header-copy {
  min-width: 0;
}

.eyebrow {
  display: block;
  color: #0F766E;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 8px;
}

.header-copy h2 {
  margin: 0;
  font-size: 24px;
  line-height: 1.15;
  letter-spacing: 0;
}

.header-copy p {
  margin: 8px 0 0;
  color: #555F58;
  line-height: 1.5;
  max-width: 68ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matchup-strip {
  margin-top: 10px;
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 8px;
  border: 1px solid #DDE4DD;
  border-radius: 6px;
  background: #FAFBFA;
  padding: 6px 8px;
  color: #5F6A63;
  font-size: 12px;
}

.matchup-strip span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matchup-strip b {
  color: #111;
  font-size: 13px;
}

.summary-strip {
  display: grid;
  grid-template-columns: minmax(180px, 1.35fr) repeat(6, minmax(88px, 1fr));
  gap: 10px;
}

.summary-item {
  min-width: 0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.summary-item span {
  color: #67706A;
  font-size: 11px;
}

.summary-item b,
.summary-item small,
.meta-btn {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-item b,
.meta-btn {
  font-size: 13px;
  font-weight: 800;
}

.summary-run b {
  font-size: 12px;
}

.summary-item small {
  color: #7C857E;
  font-size: 11px;
}

.meta-btn {
  border: none;
  background: transparent;
  color: #111;
  padding: 0;
  cursor: pointer;
  text-align: left;
}

.meta-btn:disabled {
  color: #8B948D;
  cursor: default;
}

.meta-btn:focus-visible,
.ghost-btn-xs:focus-visible,
.modal-close-btn:focus-visible,
.scenario-cell:focus-visible,
.action-btn:focus-visible,
.detail-tab:focus-visible {
  outline: 2px solid #111;
  outline-offset: 2px;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

.budget-warning {
  color: #FF4500;
}

.budget-error {
  color: #8A1F2D;
}

.action-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.action-btn {
  min-height: 40px;
  border: 1px solid #111;
  border-radius: 6px;
  padding: 0 12px;
  font-weight: 800;
  cursor: pointer;
  white-space: nowrap;
}

.action-btn.primary {
  background: #111;
  color: #FFF;
}

.action-btn.secondary {
  background: #FFF;
  color: #111;
}

.action-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,.35);
  border-top-color: #FFF;
  border-radius: 50%;
  display: inline-block;
  margin-right: 6px;
  animation: spin .8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.run-error {
  border: 1px solid #F5C2C7;
  background: #FFF5F5;
  color: #8A1F2D;
  border-radius: 8px;
  padding: 12px;
}

.run-error span {
  font-weight: 800;
}

.run-error p {
  margin: 6px 0 0;
}

.run-progress-card {
  background: #FFF;
  border: 1px solid #D8DED4;
  border-radius: 8px;
  padding: 14px;
  display: grid;
  gap: 10px;
}

.run-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.run-progress-head span {
  display: block;
  color: #0F766E;
  font-size: 11px;
  font-weight: 800;
  margin-bottom: 3px;
}

.run-progress-head b {
  font-size: 15px;
}

.run-progress-head strong {
  font-size: 18px;
}

.run-progress-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #E5EAE2;
}

.run-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: #0F766E;
  transition: width .25s ease;
}

.run-progress-card p {
  margin: 0;
  color: #526257;
  font-size: 13px;
}

.simulation-workspace {
  display: grid;
  grid-template-columns: minmax(308px, 380px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.scenario-panel {
  position: sticky;
  top: 0;
  min-width: 0;
  padding: 14px;
}

.scenario-detail-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.panel-title span {
  color: #FF4500;
  font-size: 12px;
  font-weight: 800;
}

.panel-title b {
  font-size: 15px;
}

.panel-title-spread {
  justify-content: space-between;
  align-items: flex-start;
}

.panel-title-spread div {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-title-spread em {
  color: #67706A;
  font-size: 12px;
  font-style: normal;
  padding-top: 1px;
}

.scenario-matrix {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.scenario-cell {
  min-height: 134px;
  border: 1px solid #E8ECE5;
  border-radius: 8px;
  background: #FAFBFA;
  color: inherit;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-family: inherit;
  padding: 10px;
  text-align: left;
  transition: background .15s ease, border-color .15s ease, box-shadow .15s ease;
}

.scenario-cell:hover {
  background: #FFF;
  border-color: #B9C1B9;
}

.scenario-cell.active {
  background: #FFF;
  border-color: #111;
  box-shadow: inset 0 0 0 1px #111;
}

.scenario-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
}

.scenario-title,
.scenario-cell small,
.sample-line {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-title {
  font-size: 13px;
  font-weight: 800;
}

.weight-pill {
  background: #111;
  color: #FFF;
  border-radius: 4px;
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 800;
}

.scenario-cell small,
.state-line,
.sample-line {
  color: #66706A;
  font-size: 12px;
}

.scenario-card-score {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid #EEF1ED;
}

.scenario-card-score b {
  font-size: 20px;
  line-height: 1;
}

.scenario-card-score span {
  color: #FF4500;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.state-line {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.state-line span {
  min-width: 0;
  max-width: 100%;
  border: 1px solid #DFE5DF;
  border-radius: 4px;
  padding: 2px 5px;
  background: #FFF;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-line {
  margin: 0;
  font-size: 11px;
}

.selected-scenario-card {
  padding: 16px;
  display: grid;
  gap: 14px;
}

.selected-scenario-main {
  min-width: 0;
}

.selected-scenario-main > span {
  display: block;
  color: #0F766E;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 6px;
  overflow-wrap: anywhere;
}

.selected-scenario-main h3 {
  margin: 0;
  font-size: 22px;
  line-height: 1.2;
  letter-spacing: 0;
}

.selected-state-line {
  margin-top: 10px;
}

.selected-score-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.selected-score-grid div,
.probability-card,
.coach-review-card,
.review-card,
.note-card {
  min-width: 0;
  border: 1px solid #EEF1ED;
  border-radius: 8px;
  background: #FAFBFA;
  padding: 12px;
}

.card-heading {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.selected-score-grid span,
.selected-scenario-evidence span,
.probability-card > span,
.coach-review-card > span,
.card-heading > span {
  display: block;
  color: #68716B;
  font-size: 12px;
}

.selected-score-grid b {
  display: block;
  overflow-wrap: anywhere;
}

.selected-scenario-evidence {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.selected-scenario-evidence div {
  min-width: 0;
}

.selected-scenario-evidence p {
  margin: 0;
  color: #334139;
  line-height: 1.5;
}

.detail-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
}

.detail-tab {
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #38433C;
  cursor: pointer;
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-weight: 800;
}

.detail-tab.active {
  background: #111;
  color: #FFF;
}

.detail-tab span {
  border-radius: 999px;
  background: #EDF2EF;
  color: #56615B;
  padding: 2px 7px;
  font-size: 11px;
}

.detail-tab.active span {
  background: rgba(255,255,255,.18);
  color: #FFF;
}

.detail-surface {
  padding: 16px;
}

.empty-state,
.mini-empty {
  border: 1px dashed #D7DDD6;
  border-radius: 8px;
  padding: 18px;
  color: #6E7871;
  text-align: center;
}

.mini-empty {
  padding: 10px;
}

.event-list,
.note-list,
.score-distribution {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.event-list {
  border: 1px solid #EEF1ED;
  border-radius: 8px;
  overflow: hidden;
}

.review-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.score-prob-row,
.vote-line,
.note-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.score-prob-row {
  border-bottom: 1px solid #EEF1ED;
  padding-bottom: 7px;
}

.score-prob-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.vote-line {
  flex-wrap: wrap;
}

.coach-review-summary-line {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.coach-review-summary-line span {
  min-width: 0;
  border: 1px solid #EEF1ED;
  border-radius: 6px;
  background: #FFF;
  padding: 7px;
  color: #68716B;
  font-size: 11px;
}

.coach-review-summary-line b {
  display: block;
  margin-top: 3px;
  color: #111;
  overflow-wrap: anywhere;
}

.vote-line b {
  border: 1px solid #DFE5DF;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 12px;
}

.coach-review-role-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.coach-review-role-list article {
  min-width: 0;
  border: 1px solid #E8ECE5;
  border-radius: 8px;
  background: #FFF;
  padding: 9px;
}

.coach-review-role-list article > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.coach-review-role-list article b {
  font-size: 12px;
}

.coach-review-role-list article span,
.coach-review-role-list article small {
  color: #66706A;
  font-size: 11px;
}

.coach-review-role-list article small {
  display: block;
  margin-top: 4px;
}

.coach-review-role-list article p {
  margin: 6px 0 0;
  color: #3F4A44;
  font-size: 12px;
  line-height: 1.45;
}

.coach-review-footnote {
  border-top: 1px dashed #DDE4DD;
  padding-top: 8px;
}

.coach-review-card p,
.note-card p,
.note-card small {
  margin: 6px 0 0;
  color: #4E5953;
  line-height: 1.5;
}

.review-card h4 {
  margin: 0 0 10px;
  color: #FF4500;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.review-card :deep(.meter) {
  margin-top: 0;
}

.review-card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  font-size: 11px;
  color: #66706A;
}

.review-card-stats small {
  color: #758079;
  margin-right: 4px;
}

.fallback-panel {
  min-width: 0;
  border: 1px solid #EEF1ED;
  border-radius: 8px;
  background: #FAFBFA;
  padding: 12px;
  margin-bottom: 12px;
}

.fallback-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.fallback-panel-head span:first-child {
  display: block;
  color: #FF4500;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 3px;
}

.fallback-panel-head h4 {
  margin: 0;
  font-size: 15px;
}

.fallback-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.fallback-counter {
  color: #66706A;
  font-size: 12px;
}

.fallback-reason-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.fallback-reason-strip span {
  border: 1px solid #F2D2D5;
  border-radius: 4px;
  background: #FFF;
  color: #8A1F2D;
  padding: 4px 6px;
  font-size: 11px;
}

.fallback-event-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.fallback-event-card {
  min-width: 0;
  border: 1px solid #E8ECE5;
  border-radius: 8px;
  background: #FFF;
  padding: 10px;
  display: grid;
  gap: 7px;
}

.fallback-event-card.clickable {
  cursor: pointer;
}

.fallback-event-card.clickable:hover {
  border-color: #111;
}

.fallback-event-top {
  min-width: 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.fallback-event-top b {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 12px;
}

.fallback-event-top span {
  color: #8A1F2D;
  font-size: 11px;
  white-space: nowrap;
}

.fallback-event-card p {
  margin: 0;
  color: #3F4A44;
  font-size: 12px;
  line-height: 1.45;
}

.fallback-event-meta {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #66706A;
  font-size: 11px;
}

.roster-card-row {
  display: grid;
  grid-template-columns: 36px auto 1fr;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 6px;
}

.roster-card-issues {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 8px 0;
  color: #8A4B00;
  font-size: 11px;
}

.ghost-btn-xs {
  padding: 4px 8px;
  border: 1px solid #111;
  background: #FFF;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
}

.ghost-btn-xs:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.note-header span {
  color: #0F766E;
  font-size: 12px;
  font-weight: 800;
}

.note-header b {
  color: #66706A;
}

.detail-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(17, 17, 17, .42);
  display: flex;
  justify-content: flex-end;
  padding: 18px;
}

.detail-modal {
  width: min(620px, 100%);
  max-height: 100%;
  background: #FFF;
  border: 1px solid #DDE4DD;
  border-radius: 8px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, .18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.detail-modal-wide {
  width: min(760px, 100%);
}

.detail-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  border-bottom: 1px solid #E8ECE5;
}

.detail-modal-header span {
  display: block;
  color: #0F766E;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 6px;
}

.detail-modal-header h3 {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
  letter-spacing: 0;
}

.modal-close-btn {
  width: 34px;
  height: 34px;
  border: 1px solid #DDE4DD;
  border-radius: 6px;
  background: #FFF;
  cursor: pointer;
  font-size: 22px;
  line-height: 1;
}

.detail-modal-body {
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.detail-kpi-grid div {
  min-width: 0;
  border: 1px solid #EEF1ED;
  border-radius: 8px;
  background: #FAFBFA;
  padding: 10px;
}

.detail-kpi-grid small {
  display: block;
  color: #68716B;
  font-size: 11px;
  margin-bottom: 5px;
}

.detail-kpi-grid b {
  display: block;
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 13px;
}

.detail-explain,
.raw-summary {
  margin: 0;
  color: #445049;
  line-height: 1.55;
}

.detail-explain {
  border-left: 3px solid #0F766E;
  padding-left: 10px;
}

.detail-section {
  min-width: 0;
}

.detail-section h4 {
  margin: 0 0 8px;
  color: #FF4500;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.detail-table {
  border: 1px solid #EEF1ED;
  border-radius: 8px;
  overflow: hidden;
}

.detail-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.25fr) minmax(76px, .8fr) 58px 72px;
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid #EEF1ED;
  align-items: center;
  font-size: 12px;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row-head {
  background: #F3F6F2;
  color: #66706A;
  font-weight: 800;
}

.detail-row p {
  grid-column: 1 / -1;
  margin: 0;
  color: #4E5953;
  line-height: 1.45;
}

.budget-role-row {
  grid-template-columns: minmax(140px, 1.4fr) 62px 62px 78px;
}

.failure-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.failure-summary span {
  border: 1px solid #F2D2D5;
  border-radius: 4px;
  background: #FFF5F5;
  color: #8A1F2D;
  padding: 5px 7px;
  font-size: 12px;
}

.failure-list {
  display: grid;
  gap: 8px;
}

.failure-list article {
  min-width: 0;
  border: 1px solid #EEF1ED;
  border-radius: 8px;
  background: #FAFBFA;
  padding: 10px;
  display: grid;
  gap: 5px;
}

.failure-row-head {
  min-width: 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.failure-list b {
  font-size: 12px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.failure-list span {
  color: #8A1F2D;
  font-size: 11px;
  white-space: nowrap;
}

.failure-list p,
.failure-list small,
.failure-list em {
  margin: 0;
  color: #5C665F;
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.failure-list em {
  font-style: normal;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity .16s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

@container (max-width: 1080px) {
  .summary-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .summary-run {
    grid-column: span 2;
  }

  .simulation-workspace {
    grid-template-columns: 1fr;
  }

  .scenario-panel {
    position: static;
  }

  .review-grid {
    grid-template-columns: 1fr;
  }

  .fallback-event-list {
    grid-template-columns: 1fr;
  }
}

@container (max-width: 720px) {
  .detail-modal-mask {
    padding: 8px;
  }

  .detail-modal,
  .detail-modal-wide {
    width: 100%;
  }

  .detail-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .detail-row,
  .budget-role-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .detail-row-head {
    display: none;
  }
}

@container (max-width: 720px) {
  .simulation-scroll {
    padding: 12px;
  }

  .simulation-header {
    grid-template-columns: 1fr;
  }

  .action-controls {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-run {
    grid-column: 1 / -1;
  }

  .scenario-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .selected-score-grid,
  .selected-scenario-evidence {
    grid-template-columns: 1fr;
  }
}

@container (max-width: 480px) {
  .summary-strip,
  .scenario-matrix,
  .detail-tabs {
    grid-template-columns: 1fr;
  }

  .header-copy p {
    white-space: normal;
  }
}
</style>
