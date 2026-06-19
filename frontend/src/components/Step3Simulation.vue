<template>
  <div class="match-simulation-panel">
    <div class="simulation-scroll">
      <header class="simulation-header">
        <div class="header-copy">
          <span class="eyebrow mono">STEP 03 · MATCH SIMULATION</span>
          <h2>比赛场景推演</h2>
          <p>{{ projectData?.simulation_requirement || projectData?.project_name || '九场景比赛推演' }}</p>
          <div class="matchup-strip" :title="matchIdentity.matchName">
            <span>主队 <b>{{ matchIdentity.home }}</b></span>
            <span class="mono">VS</span>
            <span>客队 <b>{{ matchIdentity.away }}</b></span>
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
            {{ isRunning ? '推演中...' : '开始比赛推演' }}
          </button>
          <button
            v-if="currentPredictionRunId"
            class="action-btn secondary"
            type="button"
            :disabled="isRunning || isGeneratingReport"
            @click="regenerateStep3"
          >
            重新生成推演
          </button>
          <button
            v-if="phase === 2"
            class="action-btn primary"
            type="button"
            :disabled="isGeneratingReport"
            @click="handleNextStep"
          >
            <span v-if="isGeneratingReport" class="spinner"></span>
            {{ isGeneratingReport ? '生成报告中...' : '生成赛事预测报告' }}
            <span v-if="!isGeneratingReport">→</span>
          </button>
          <button class="action-btn secondary" type="button" @click="$emit('go-back')">返回参数</button>
        </div>
      </header>

      <section class="summary-strip" aria-label="推演状态">
        <div class="summary-item summary-run">
          <span>运行 / 配置</span>
          <b class="mono">{{ currentPredictionRunId || '未创建' }}</b>
          <small class="mono">CFG {{ currentPredictionConfigId || '未绑定' }}</small>
        </div>
        <div class="summary-item">
          <span>阶段</span>
          <b>{{ phaseLabel }}</b>
        </div>
        <div class="summary-item">
          <span>模型</span>
          <b>{{ selectedScoreline?.model_name || '-' }}</b>
        </div>
        <div class="summary-item">
          <span>共识</span>
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
          <span>预算</span>
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
          <span>名册</span>
          <button class="meta-btn mono" type="button" @click="openRosterDrawer">{{ rosterSummary.total }} 人</button>
        </div>
        <div class="summary-item">
          <span>种子</span>
          <b class="mono">{{ simulationSeedShort }}</b>
        </div>
      </section>

      <div v-if="errorMessage" class="run-error" role="alert">
        <span>比赛推演失败</span>
        <p>{{ errorMessage }}</p>
      </div>

      <section v-if="phase === 1" class="run-progress-card" aria-label="比赛推演进度">
        <div class="run-progress-head">
          <div>
            <span class="mono">SIMULATION_PROGRESS</span>
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
              <span class="mono">3X3_MATRIX</span>
              <b>九种比赛可能</b>
            </div>
            <em class="mono">{{ orderedScenarioCases.length }}/9</em>
          </div>
          <div v-if="scenarioCases.length === 0" class="empty-state">
            使用 Step2 配置开始推演后展示九场景矩阵。
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
                <span class="mono">{{ mostLikelyScoreProb(scenario) || '概率 -' }}</span>
              </div>

              <div class="state-line">
                <span :title="matchIdentity.homeLabel">主队 {{ matchIdentity.home }} · {{ stateLabel(scenario.home_state) }}</span>
                <span :title="matchIdentity.awayLabel">客队 {{ matchIdentity.away }} · {{ stateLabel(scenario.away_state) }}</span>
              </div>
              <p class="sample-line mono">{{ scenarioSampleLabel(scenario) }}</p>
            </button>
          </div>
        </section>

        <section class="scenario-detail-panel">
          <div class="selected-scenario-card">
            <div class="selected-scenario-main">
              <span class="mono">{{ selectedScenarioKey }}</span>
              <h3>{{ selectedScenario?.scenario_name || selectedScenario?.scenario_module || '比赛进程' }}</h3>
              <div class="state-line selected-state-line">
                <span>主队 {{ matchIdentity.home }} · {{ stateLabel(selectedScenario?.home_state) }}</span>
                <span>客队 {{ matchIdentity.away }} · {{ stateLabel(selectedScenario?.away_state) }}</span>
                <span>权重 {{ selectedScenarioWeight }}</span>
              </div>
            </div>

            <div class="selected-score-grid">
              <div>
                <span>最可能比分</span>
                <b class="mono">{{ selectedMostLikelyScore }}</b>
              </div>
              <div>
                <span>xG</span>
                <b class="mono">{{ formatXg(selectedScoreline?.home_xg) }}-{{ formatXg(selectedScoreline?.away_xg) }}</b>
              </div>
              <div>
                <span>胜平负</span>
                <b>{{ selectedWdlLine }}</b>
              </div>
            </div>

            <div class="selected-scenario-evidence">
              <div>
                <span>驱动因素</span>
                <p>{{ selectedScenarioDrivers.join(' / ') || 'Monte Carlo modal path' }}</p>
              </div>
              <div>
                <span>风险因素</span>
                <p>{{ selectedScenarioRisks.join(' / ') || selectedScenario?.scenario_space || '-' }}</p>
              </div>
            </div>

            <ModalTrajectoryFootnote
              :trajectory="selectedScenario?.modal_trajectory_summary"
              :n-sims="selectedScenario?.n_sims || statusPayload?.n_sims || 0"
            />
          </div>

          <div class="detail-tabs" role="tablist" aria-label="场景详情">
            <button
              class="detail-tab"
              type="button"
              role="tab"
              :class="{ active: activeDetailTab === 'flow' }"
              :aria-selected="activeDetailTab === 'flow'"
              @click="activeDetailTab = 'flow'"
            >
              比赛流
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
              模型复核
              <span class="mono">{{ selectedNotes.length }}</span>
            </button>
          </div>

          <section v-show="activeDetailTab === 'flow'" class="detail-surface" role="tabpanel">
            <div class="panel-title">
              <span class="mono">MATCH_FLOW</span>
              <b>关键事件链</b>
            </div>

            <div v-if="selectedEvents.length === 0" class="empty-state">
              当前场景暂无事件链。
            </div>
            <div v-else class="event-list">
              <MatchEventRow v-for="event in selectedEvents" :key="event.id" :event="event" />
            </div>
          </section>

          <section v-show="activeDetailTab === 'review'" class="detail-surface" role="tabpanel">
            <div class="panel-title">
              <span class="mono">MODEL_REVIEW</span>
              <b>模型研判与教练复核</b>
            </div>

            <div class="review-grid">
              <div class="probability-card">
                <span>比分概率 Top</span>
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
                  <span>教练复核</span>
                  <button class="ghost-btn-xs" type="button" :disabled="!coachReview" @click="openConsensusDialog">详情</button>
                </div>
                <template v-if="coachReview">
                  <div class="coach-review-summary-line">
                    <span>共识 <b class="mono">{{ coachReviewMeta.label }}</b></span>
                    <span>来源 <b>{{ coachReviewMeta.source }}</b></span>
                    <span>公式 <b class="mono">{{ coachReviewMeta.formula }}</b></span>
                  </div>
                  <div class="vote-line">
                    <b>支持 {{ coachReviewMeta.supportVotes }}</b>
                    <b>反对 {{ coachReviewMeta.opposeVotes }}</b>
                    <b>观察 {{ coachReviewMeta.abstainVotes }}</b>
                  </div>
                  <div class="coach-review-role-list">
                    <article v-for="row in coachReviewPreviewRows" :key="`${row.role}-${row.verdict}`">
                      <div>
                        <b>{{ row.roleLabel }}</b>
                        <span>{{ row.verdictLabel }} · 权重 {{ row.weight }} · 置信 {{ row.confidence === null ? '-' : `${row.confidence}%` }}</span>
                      </div>
                      <small>{{ row.sourceNote }}</small>
                      <p>{{ row.rationale || '无补充理由。' }}</p>
                    </article>
                  </div>
                  <p class="coach-review-footnote">
                    置信度调整 {{ coachReviewMeta.confidenceDelta }}；Step3 复核只检查事件链和模态轨迹，不覆盖比分概率。
                  </p>
                </template>
                <p v-else>暂无复核摘要。</p>
              </div>

              <div class="review-card">
                <div class="card-heading">
                  <h4>评审支出</h4>
                  <button class="ghost-btn-xs" type="button" @click="openBudgetDialog">详情</button>
                </div>
                <LLMBudgetMeter :ledger="budgetLedger" compact />
                <div class="review-card-stats">
                  <span><small>总耗时</small> <b class="mono">{{ formatMs(budgetLedger.total_latency_ms) }}</b></span>
                  <span><small>tokens</small> <b class="mono">{{ budgetDetails.totalTokens }}</b></span>
                  <span><small>p95 延迟</small> <b class="mono">{{ formatMs(budgetLedger.p95_latency_ms) }}</b></span>
                </div>
              </div>

              <div class="review-card">
                <h4>名册可用度</h4>
                <div class="roster-card-summary">
                  <div class="roster-card-row">
                    <span>主队</span>
                    <span class="mono">{{ rosterSummary.home.available }}/{{ rosterSummary.home.total }}</span>
                    <ConfidenceBar :value="availabilityPercent(rosterSummary.home)" />
                  </div>
                  <div class="roster-card-row">
                    <span>客队</span>
                    <span class="mono">{{ rosterSummary.away.available }}/{{ rosterSummary.away.total }}</span>
                    <ConfidenceBar :value="availabilityPercent(rosterSummary.away)" />
                  </div>
                </div>
                <div class="roster-card-issues">
                  <span v-if="rosterSummary.injured > 0">伤 <b class="mono">{{ rosterSummary.injured }}</b></span>
                  <span v-if="rosterSummary.suspended > 0">停 <b class="mono">{{ rosterSummary.suspended }}</b></span>
                  <span v-if="rosterSummary.doubtful > 0">疑 <b class="mono">{{ rosterSummary.doubtful }}</b></span>
                </div>
                <button class="ghost-btn-xs" type="button" @click="openRosterDrawer">完整名册 →</button>
              </div>
            </div>

            <section class="fallback-panel">
              <div class="fallback-panel-head">
                <div>
                  <span class="mono">NARRATIVE_FALLBACKS</span>
                  <h4>叙述回退事件</h4>
                </div>
                <div class="fallback-actions">
                  <span class="fallback-counter">
                    当前 <b class="mono">{{ fallbackPanel.currentCount }}</b> / 全部 <b class="mono">{{ fallbackPanel.total }}</b>
                  </span>
                  <button
                    class="ghost-btn-xs"
                    type="button"
                    :disabled="budgetFailureRows.length === 0"
                    @click="showAllFallbacks = !showAllFallbacks"
                  >
                    {{ showAllFallbacks ? '仅当前场景' : '显示全部' }}
                  </button>
                  <button class="ghost-btn-xs" type="button" @click="openBudgetDialog">预算详情</button>
                </div>
              </div>

              <div v-if="fallbackPanel.reasonRows.length" class="fallback-reason-strip">
                <span v-for="row in fallbackPanel.reasonRows" :key="row.reason">
                  {{ row.reason }} <b class="mono">{{ row.count }}</b>
                </span>
              </div>
              <div v-if="fallbackPanel.visible.length === 0" class="mini-empty">
                当前场景暂无叙述回退事件。
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
                      查看事件
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
              <span class="mono">CONSENSUS_SOURCE</span>
              <h3 id="consensus-detail-title">Step3 共识来源</h3>
            </div>
            <button class="modal-close-btn" type="button" aria-label="关闭共识详情" @click="consensusDialogOpen = false">×</button>
          </header>

          <div class="detail-modal-body">
            <div class="detail-kpi-grid">
              <div>
                <small>当前场景</small>
                <b class="mono">{{ selectedScenarioKey }}</b>
              </div>
              <div>
                <small>共识</small>
                <b class="mono">{{ coachReviewMeta.label }}</b>
              </div>
              <div>
                <small>来源</small>
                <b>{{ coachReviewMeta.source }}</b>
              </div>
              <div>
                <small>公式</small>
                <b class="mono">{{ coachReviewMeta.formula }}</b>
              </div>
            </div>

            <p class="detail-explain">
              共识分按角色复核 verdict 加权：support=1，watch/adjust=0.5，reject=0，然后除以参与复核角色数。
            </p>

            <div class="detail-section">
              <h4>角色复核明细</h4>
              <div v-if="coachReviewMeta.reviewRows.length === 0" class="mini-empty">暂无角色复核明细。</div>
              <div v-else class="detail-table">
                <div class="detail-row detail-row-head">
                  <span>角色</span>
                  <span>结论</span>
                  <span>权重</span>
                  <span>置信</span>
                </div>
                <div v-for="row in coachReviewMeta.reviewRows" :key="`${row.role}-${row.verdict}`" class="detail-row">
                  <span>{{ row.roleLabel }}</span>
                  <span>{{ row.verdictLabel }}</span>
                  <span class="mono">{{ row.weight }}</span>
                  <span class="mono">{{ row.confidence === null ? '-' : `${row.confidence}%` }}</span>
                  <p>{{ row.rationale || '无补充理由。' }}</p>
                </div>
              </div>
            </div>

            <div class="detail-section">
              <h4>原始摘要</h4>
              <p class="raw-summary">{{ coachReviewMeta.summary || '暂无摘要。' }}</p>
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
              <span class="mono">BUDGET_SOURCE</span>
              <h3 id="budget-detail-title">预算调用详情</h3>
            </div>
            <button class="modal-close-btn" type="button" aria-label="关闭预算详情" @click="budgetDialogOpen = false">×</button>
          </header>

          <div class="detail-modal-body">
            <div class="detail-kpi-grid">
              <div>
                <small>使用 / 上限</small>
                <b class="mono" :class="budgetClass">{{ budgetDetails.usedLabel }}</b>
              </div>
              <div>
                <small>已消费</small>
                <b class="mono">{{ budgetDetails.spent }}</b>
              </div>
              <div>
                <small>缓存命中</small>
                <b class="mono">{{ budgetDetails.cached }}</b>
              </div>
              <div>
                <small>剩余</small>
                <b class="mono">{{ budgetDetails.remaining }}</b>
              </div>
            </div>

            <p class="detail-explain">
              预算数字来自当前 prediction run 的 LLM ledger。total_calls 是实际完成并记录的调用数，hard_cap 是本次 Step3 预算硬上限；超过上限的步骤会转 fallback。
            </p>

            <div class="detail-section">
              <h4>按角色统计</h4>
              <div v-if="budgetDetails.roleRows.length === 0" class="mini-empty">暂无调用记录。</div>
              <div v-else class="detail-table">
                <div class="detail-row detail-row-head budget-role-row">
                  <span>角色</span>
                  <span>调用</span>
                  <span>缓存</span>
                  <span>tokens</span>
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
              <h4>失败与 fallback</h4>
              <div class="failure-summary">
                <span v-for="row in budgetDetails.failureReasonRows" :key="row.reason">
                  {{ row.reason }} <b class="mono">{{ row.count }}</b>
                </span>
              </div>
              <div v-if="budgetFailureRows.length === 0" class="mini-empty">暂无失败记录。</div>
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
  if (statusPayload.value?.status === 'queued') return '比赛推演已进入 Celery 队列'
  if (statusPayload.value?.status === 'running') return '正在生成比分概率、事件链和复核结果'
  return '准备启动比赛推演'
})
const phaseLabel = computed(() => {
  if (phase.value === 2) return 'Completed'
  if (phase.value === 1) return phaseDisplayName(statusPayload.value?.current_phase || statusPayload.value?.status)
  return currentPredictionConfigId.value ? 'Ready' : 'Missing Config'
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

const coachReviewMeta = computed(() => coachReviewSummary(coachReview.value, budgetLedger.value || {}))
const coachReviewPreviewRows = computed(() => coachReviewMeta.value.reviewRows.slice(0, 3))

const coachConsensusLabel = computed(() => {
  if (!coachReview.value) return '-'
  return coachReviewMeta.value.label
})

const coachConsensusTooltip = computed(() => {
  if (!coachReview.value) return '当前场景暂无 Step3 教练复核'
  return `来源: ${coachReviewMeta.value.formula} = ${coachReviewMeta.value.label}; 点击查看角色 verdict`
})

const selectedWdlLine = computed(() => {
  const wdl = selectedScenario.value?.win_draw_loss_probability || {}
  const home = selectedScoreline.value?.home_win_probability ?? wdl.home ?? wdl.home_win ?? wdl.home_win_probability
  const draw = selectedScoreline.value?.draw_probability ?? wdl.draw ?? wdl.draw_probability
  const away = selectedScoreline.value?.away_win_probability ?? wdl.away ?? wdl.away_win ?? wdl.away_win_probability
  if (home === undefined && draw === undefined && away === undefined) return '-'
  return [`主 ${formatPercent(home)}`, `平 ${formatPercent(draw)}`, `客 ${formatPercent(away)}`].join(' / ')
})

const scoreDistribution = computed(() => (
  normalizeScoreDistribution(selectedScoreline.value?.scoreline_distribution || selectedScenario.value?.scoreline_distribution).slice(0, 5)
))

const budgetMeta = computed(() => budgetUsageMeta(budgetLedger.value || {}))
const budgetUsed = computed(() => budgetMeta.value.used)
const budgetCap = computed(() => budgetMeta.value.cap)
const budgetClass = computed(() => budgetMeta.value.className)
const budgetDetails = computed(() => budgetUsageDetails(budgetLedger.value || {}))
const budgetFailureRows = computed(() => failureEventRows(budgetDetails.value.failures, matchEvents.value))
const fallbackPanel = computed(() => fallbackPanelSummary(budgetFailureRows.value, selectedScenarioKey.value, showAllFallbacks.value))
const budgetTooltip = computed(() => `LLM 调用 ${budgetDetails.value.usedLabel}; 剩余 ${budgetDetails.value.remaining}; 点击查看角色和 fallback 明细`)
const rosterSummary = computed(() => availabilitySummary(runRoster.value || {}))
const matchIdentity = computed(() => matchTeamIdentity({
  statusPayload: statusPayload.value || {},
  predictionConfig: predictionConfigSnapshot.value || {},
  predictionResult: predictionResult.value || {},
  teamStrengths: teamStrengths.value,
  roster: runRoster.value || {},
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
        addLog('当前项目没有 active Step3 推演，已清理旧路由中的 prediction_run_id')
      }
      resetRunState()
      emit('update-status', currentPredictionConfigId.value ? 'processing' : 'error')
      errorMessage.value = currentPredictionConfigId.value
        ? ''
        : '缺少 active Step2 配置，请先完成 Step2。'
      return false
    }

    if (currentPredictionRunId.value && currentPredictionRunId.value !== active.prediction_run_id) {
      addLog('路由中的旧 Step3 推演已失效，已切换到当前 active 推演')
    }
    currentPredictionRunId.value = active.prediction_run_id
    return true
  } catch (err) {
    addLog(`读取项目 active workflow 失败: ${err.message}`)
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
    addLog(`从 Step3 运行状态恢复配置失败: ${err.message}`)
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
      onBefore: () => {
        resetRunState()
        emit('update-status', 'processing')
        addLog('Step3 已重新生成，旧 Step4 报告和 Step5 问答已失效')
      },
    })
    if (!regenerated) return
  } catch (err) {
    errorMessage.value = err.message || '重新生成推演失败'
    emit('update-status', 'error')
    addLog(`重新生成推演失败: ${errorMessage.value}`)
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
      progress_messages: [{ message: '比赛推演正在进入 Celery 队列', progress_percent: 1 }],
    },
  }
  emit('update-status', 'processing')
  addLog(`使用配置启动九场景推演: ${currentPredictionConfigId.value}`)

  try {
    const response = await runPrediction(props.projectData.project_id, {
      prediction_config_id: currentPredictionConfigId.value,
      async: true,
    })

    currentPredictionRunId.value = response.data.prediction_run_id
    currentPredictionConfigId.value = response.data.prediction_config_id || currentPredictionConfigId.value
    statusPayload.value = response.data || statusPayload.value
    addLog(`预测运行已进入后台队列: ${currentPredictionRunId.value}`)
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
    addLog(`比赛推演失败: ${errorMessage.value}`)
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
      errorMessage.value = statusRes.data?.error || '比赛推演失败'
      phase.value = 0
      emit('update-status', 'error')
      addLog(`比赛推演失败: ${errorMessage.value}`)
    }
  } catch (err) {
    addLog(`推演进度查询失败: ${err.message}`)
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

    if (rosterRes.optionalError) addLog(`名册数据暂不可用: ${rosterRes.optionalError.message}`)
    if (budgetRes.optionalError) addLog(`预算数据暂不可用: ${budgetRes.optionalError.message}`)

    selectDefaultScenario()

    if (statusRes.data?.status === 'completed') {
      phase.value = 2
      emit('update-status', 'completed')
      addLog('九场景比赛推演完成，所有产物已写入数据库')
    } else if (statusRes.data?.status === 'failed') {
      phase.value = 0
      emit('update-status', 'error')
    }
  } catch (err) {
    errorMessage.value = err.message || 'unknown error'
    phase.value = 0
    emit('update-status', 'error')
    addLog(`加载预测产物失败: ${errorMessage.value}`)
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
    addLog(`预测配置队名暂不可用: ${err.message}`)
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
  addLog('开始从九场景预测产物生成赛事预测报告')
  try {
    const response = await createPredictionReport(currentPredictionRunId.value)
    const reportId = response.data.report_id
    addLog(`赛事预测报告已生成: ${reportId}`)
    emit('next-step', { reportId, predictionRunId: currentPredictionRunId.value, predictionConfigId: currentPredictionConfigId.value })
    router.push({ name: 'Report', params: { reportId } })
  } catch (err) {
    errorMessage.value = err.message || 'unknown error'
    emit('update-status', 'error')
    addLog(`生成赛事预测报告失败: ${errorMessage.value}`)
  } finally {
    isGeneratingReport.value = false
  }
}

const scenarioKey = (scenario) => scenario?.scenario_key || scenario?.metadata?.scenario_key || '-'

const phaseDisplayName = (phase) => {
  const labels = {
    queued: 'Queued',
    loading_config: 'Loading Config',
    running_simulation: 'Running Simulation',
    persisting_artifacts: 'Saving Artifacts',
    completed: 'Completed',
    failed: 'Failed',
    running: 'Running',
  }
  return labels[phase] || phase || 'Running'
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
  const nSimsLabel = nSims > 0 ? nSims.toLocaleString('zh-CN') : '-'
  const firstGoal = scenario?.modal_trajectory_summary?.first_goal_minute
  return `采样 ${nSimsLabel}${firstGoal ? ` · 首球 ${firstGoal}'` : ''}`
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

const roleLabel = (role) => roleLabelAdapter(role)
const stateLabel = (state) => stateLabelAdapter(state)
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
  addLog('Step3 九场景比赛推演初始化')
  loadPredictionConfigSnapshot()
  reconcileActiveWorkflow().then(async (hasActiveRun) => {
    await recoverPredictionConfigFromRun()
    if (hasActiveRun && currentPredictionRunId.value) {
      pollPredictionStatus()
      startStatusPolling()
    } else if (!currentPredictionConfigId.value) {
      emit('update-status', 'error')
      errorMessage.value = '缺少 prediction_config_id，请先完成 Step2 配置准备。'
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
