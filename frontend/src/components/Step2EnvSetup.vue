<template>
  <div class="prediction-setup-panel">
    <div class="scroll-container">
      <section class="setup-header">
        <div>
          <span class="eyebrow">STEP 02</span>
          <h2>预测配置准备</h2>
          <p>{{ config?.match_name || preview?.match_name || projectData?.simulation_requirement || '等待赛事预测需求' }}</p>
        </div>
        <div class="header-actions">
          <button class="ghost-btn" type="button" @click="$emit('go-back')">返回图谱</button>
          <button class="ghost-btn" type="button" :disabled="isPreparing" @click="prepareConfig(true)">
            <span v-if="isPreparing" class="spinner dark"></span>
            {{ predictionConfigId ? '重新生成配置' : '生成配置' }}
          </button>
        </div>
      </section>

      <section class="metrics-grid">
        <div class="metric">
          <span class="metric-label">
            配置
            <InfoTooltip
              align="left"
              title="配置 ID"
              text="当前 Step2 生成出的预测配置编号。后续 Step3 会用它读取球队强度、场景矩阵、评审记录和恢复策略。"
            />
          </span>
          <span class="metric-value mono">{{ predictionConfigId || '-' }}</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            状态
            <InfoTooltip
              title="准备状态"
              text="pending 表示尚未完成，preparing 表示正在生成，ready 表示配置可进入 Step3，failed 或 error 表示需要重新生成。"
            />
          </span>
          <span class="metric-value">{{ statusLabel }}</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            进度
            <InfoTooltip
              title="生成进度"
              text="后端按里程碑更新的准备进度，覆盖名册匹配、数据源读取、球队强度估计、场景设计和恢复节点生成。"
            />
          </span>
          <span class="metric-value mono">{{ config?.progress_percent ?? 0 }}%</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            模型
            <InfoTooltip
              title="预测模型"
              text="当前配置采用的底层足球进球模型。数据足够时会使用拟合模型，数据不足时会降级为先验或规则模型。"
            />
          </span>
          <span class="metric-value">{{ config?.model_name || '-' }}</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            拟合
            <InfoTooltip
              title="拟合状态"
              text="说明模型是否从结构化赛果中拟合出参数。fitted 可信度较高；fallback_prior 或 insufficient 表示样本不足，更多依赖名册、排名和图谱证据。"
            />
          </span>
          <span class="metric-value">{{ config?.fit_status || '-' }}</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            名册
            <InfoTooltip
              title="球员数据"
              text="两队可用于建模的球员总数。名册影响能力评分、位置深度、伤停风险、门将强度和事件参与者抽样。"
            />
          </span>
          <span class="metric-value mono">{{ rosterSummaryLabel }}</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            数据源
            <InfoTooltip
              title="外部数据快照"
              text="已同步的数据源数 / 可用数据源总数。包含国际赛果、Elo、FIFA 排名和可选 xG 数据；同步失败时会使用本地缓存或降级特征。"
            />
          </span>
          <span class="metric-value mono">{{ externalSourcesActive }}/{{ externalSourcesTotal }}</span>
        </div>
        <div class="metric">
          <span class="metric-label">
            评审 ★
            <InfoTooltip
              align="right"
              title="LLM 调用预算"
              text="显示实际 LLM 调用数 / 计划调用数，cap 是硬上限。fresh/cached 是生成完成后的实际账本；准备中或禁用 LLM 时实际调用可以暂时为 0。"
            />
          </span>
          <span class="metric-value-stack">
            <span class="metric-value mono" :class="budgetClass">{{ budgetUsed }}/{{ budgetPlanned }}</span>
            <span class="metric-subvalue mono">cap {{ budgetCap }}</span>
          </span>
        </div>
      </section>

      <div v-if="errorMessage" class="setup-error" role="alert">
        <b>配置准备失败</b>
        <span>{{ errorMessage }}</span>
      </div>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">01</span>
          <h3>数据源与名册</h3>
          <InfoTooltip
            title="数据源与名册"
            text="这里决定模型可用的客观输入：外部赛果/排名/xG 快照提供球队近期和长期强度，球员名册提供阵容深度、位置能力、伤停和门将信息。"
          />
        </div>
        <div class="data-source-roster-grid">
          <DataSourcesCard :sources="externalSources" @refresh="refreshSources" />
          <RosterSummaryCard
            :summary="rosterSummary"
            :dataset-id="config?.player_dataset_id || preview?.player_dataset_id"
            @open-drawer="openRosterDrawer"
            @switch-dataset="openDatasetPicker"
          />
        </div>
      </section>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">02</span>
          <h3>评审预算</h3>
          <InfoTooltip
            title="评审预算"
            text="控制 Step2/Step3 中 LLM 参与的深度。启用更多角色、场景叙述、分析师笔记和复核通常会增加耗时和模型费用；实际费用取决于你配置的模型。"
          />
        </div>

        <LLMBudgetSelector
          :model-value="selectedProfile"
          :preview="{ calls: estimatedCalls }"
          :disabled="isPreparing"
          @update:model-value="selectBudgetProfile"
        />
        <LLMBudgetCustomPanel
          v-if="selectedProfile.profile_key === 'custom'"
          :model-value="selectedProfile"
          :disabled="isPreparing"
          @update:model-value="updateCustomBudget"
          @apply="prepareConfig(true)"
        />
        <p v-if="isPreparing" class="budget-lock-note">
          当前配置正在生成，预算已锁定；如需调整，请等待本次生成完成后再应用。
        </p>
        <LLMBudgetMeter :ledger="budgetLedger" />
      </section>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">03</span>
          <h3>100 教练评审团</h3>
          <InfoTooltip
            title="教练评审团"
            text="系统会生成 100 个教练代理，但只有预算启用的角色会参与关键讨论。不同角色从进攻、防守、转换、定位球、门将、体能和风险角度审视同一场比赛。"
          />
        </div>
        <div class="coach-grid">
          <div
            v-for="item in agentRoleCounts"
            :key="item.role"
            class="coach-role"
            :class="{
              'coach-role-disabled': !isRoleEnabled(item.role),
              'coach-role-active': isRoleSpoken(item.role)
            }"
          >
            <span class="coach-role-label">
              {{ roleLabel(item.role) }}
              <InfoTooltip
                :title="roleLabel(item.role)"
                :text="roleDescription(item.role)"
              />
            </span>
            <b class="mono">{{ item.count }}</b>
            <span v-if="isRoleSpoken(item.role)" class="coach-spoken">✦</span>
            <small v-else-if="!isRoleEnabled(item.role)" class="coach-budget-hint">未启用 (预算)</small>
          </div>
        </div>
        <div class="discussion-list">
          <article v-for="discussion in discussions" :key="discussion.id" class="discussion-item">
            <div>
              <b>{{ discussion.topic }}</b>
              <p>{{ discussion.summary }}</p>
              <small v-if="discussion.metadata?.tokens" class="discussion-cost mono">
                ↳ cost {{ formatTokens(discussion.metadata.tokens) }} · {{ discussion.metadata.latency_ms || '-' }}ms
              </small>
            </div>
            <span class="mono">{{ Math.round(Number(discussion.consensus_score || 0) * 100) }}%</span>
          </article>
          <div v-if="discussions.length === 0" class="mini-empty">暂无评审讨论。</div>
        </div>
      </section>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">04</span>
          <h3>场景空间设计</h3>
          <InfoTooltip
            title="场景空间设计"
            text="把比赛拆成若干可能世界，例如基准、主队上行、客队失误或高波动。每个场景会有初始权重和评审后权重，Step3 会按这些权重抽样比赛过程。"
          />
        </div>
        <div class="scenario-matrix">
          <article v-for="scenario in scenarioCases" :key="scenario.id" class="scenario-cell">
            <div class="scenario-head">
              <b>{{ scenario.scenario_name }}</b>
              <ScenarioWeightDelta
                :initial="scenario.initial_weight"
                :final="scenario.final_weight"
                :weight-change="scenario.weight_change"
              />
            </div>
            <small>{{ scenario.scenario_key }}</small>
            <div class="state-line">
              <span>{{ stateLabel(scenario.home_state) }}</span>
              <span>{{ stateLabel(scenario.away_state) }}</span>
              <span>{{ spaceLabel(scenario.scenario_space) }}</span>
            </div>
            <p>{{ (scenario.key_drivers || []).join(' / ') || '-' }}</p>
            <em>{{ (scenario.risk_factors || []).join(' / ') || '-' }}</em>
          </article>
          <div v-if="scenarioCases.length === 0" class="mini-empty">暂无场景矩阵。</div>
        </div>
      </section>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">05</span>
          <h3>恢复与回看策略</h3>
          <InfoTooltip
            title="恢复与回看策略"
            text="定义预测流程中哪些节点必须持久化，以及中断或重跑时从哪里恢复。它保证 Step3、报告生成和回放能复用同一份配置，不重复昂贵步骤。"
          />
        </div>
        <div class="resume-table">
          <div class="resume-row resume-head">
            <span>
              序列
              <InfoTooltip
                align="left"
                title="序列"
                text="节点在预测流程中的执行顺序。序号越小越早生成，后续节点依赖前序产物。"
              />
            </span>
            <span>
              节点
              <InfoTooltip
                title="节点"
                text="可恢复的流程步骤，例如生成球队强度、九宫格场景、比赛事件或报告摘要。"
              />
            </span>
            <span>
              持久化
              <InfoTooltip
                title="持久化"
                text="“是”表示该节点产物会写入数据库，刷新页面、重启后端或重跑后仍可复用。"
              />
            </span>
            <span>
              策略
              <InfoTooltip
                align="right"
                title="恢复策略"
                text="说明中断后如何处理该节点：复用已有结果、重新计算，或从最近稳定节点继续。"
              />
            </span>
          </div>
          <div v-for="node in resumeNodes" :key="node.id" class="resume-row">
            <span class="mono">{{ node.sequence }}</span>
            <span>{{ node.label }}</span>
            <span>{{ node.must_persist ? '是' : '否' }}</span>
            <span>{{ node.resume_strategy }}</span>
          </div>
        </div>
      </section>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">06</span>
          <h3>球队强度 & 基础概率</h3>
          <InfoTooltip
            title="球队强度与基础概率"
            text="把图谱、名册、排名和赛果转换成 0-100 的球队维度评分。进攻看机会创造和终结，防守看限制机会能力，控球看中场出球与节奏，转换看反抢和反击，定位球看高空球与二点保护，门将看扑救、出球和高球处理。评分右上角的来源按钮可展开查看模型融合、球员名册等证据来源。主队和客队使用同一套定义，所以说明集中在这里。"
          />
        </div>
        <div class="team-grid">
          <article v-for="team in orderedTeamStrengths" :key="team.team_role" class="team-card">
            <div class="team-head">
              <span>{{ team.team_role === 'home' ? '主队' : '客队' }}</span>
              <b>{{ team.team_name }}</b>
              <em class="mono">{{ team.confidence }}%</em>
            </div>
            <div class="rating-grid">
              <div v-for="rating in ratingItems(team)" :key="rating.key" class="rating-cell">
                <span class="rating-meta">
                  <span class="rating-name">{{ rating.label }}</span>
                  <EvidenceChip
                    v-if="rating.refs.length || rating.source"
                    compact
                    class="rating-source-chip"
                    :source="rating.source"
                    :refs="rating.refs"
                  />
                </span>
                <b class="rating-score">{{ rating.value }}</b>
              </div>
            </div>
            <div class="team-adjustments">
              <small>状态调整</small>
              <div>
                伤停 <b>{{ signed(team.injury_adjustment) }}</b>
                <EvidenceChip
                  v-for="ref in team.injury_evidence_refs || []"
                  :key="ref.id || ref.name"
                  source="injury"
                  :refs="[ref]"
                />
              </div>
              <div>
                状态 <b>{{ signed(team.form_adjustment) }}</b>
                <EvidenceChip
                  v-for="ref in team.form_evidence_refs || []"
                  :key="ref.id || ref.name"
                  source="form"
                  :refs="[ref]"
                />
              </div>
              <div>主场 <b>{{ homeAwayText(team) }}</b></div>
            </div>
          </article>
          <div v-if="teamStrengths.length === 0" class="mini-empty">暂无球队强度。</div>
        </div>
      </section>

      <section class="setup-section">
        <div class="section-title-row">
          <span class="section-index mono">07</span>
          <h3>模型输入与数据充分性</h3>
          <InfoTooltip
            title="模型输入与数据充分性"
            text="展示模型实际吃到的关键输入和降级原因。这里能判断结果是由结构化数据强支撑，还是主要依赖报告文本、名册和先验规则。"
          />
        </div>
        <div class="input-grid">
          <div class="input-row">
            <span>
              比赛
              <InfoTooltip
                title="比赛"
                text="后端从需求文本、图谱实体或显式入参中识别出的主客队和赛事名称。识别错误会影响后续名册匹配和强度估计。"
              />
            </span>
            <b>{{ config?.match_name || '-' }}</b>
          </div>
          <div class="input-row">
            <span>
              图谱
              <InfoTooltip
                title="图谱"
                text="Step1 生成的知识图谱 ID。Step2 会从图谱节点中读取球队、球员、战术、天气、伤停和赛制信息。"
              />
            </span>
            <b class="mono">{{ config?.graph_id || projectData?.graph_id || '-' }}</b>
          </div>
          <div class="input-row">
            <span>
              数据充分性
              <InfoTooltip
                title="数据充分性"
                text="模型对当前输入质量的总体判断。sufficient 表示结构化样本较完整；partial 表示可用但有缺口；insufficient 表示会明显依赖降级逻辑。"
              />
            </span>
            <b>{{ config?.data_sufficiency || '-' }}</b>
          </div>
          <div class="input-row">
            <span>
              结构化赛果
              <InfoTooltip
                title="结构化赛果"
                text="已匹配到的历史比赛记录数量。数量越多，球队强度和近期状态估计越稳定；数量少时会回退到排名、名册和文本证据。"
              />
            </span>
            <b class="mono">{{ structuredMatchCount }}</b>
          </div>
          <div class="input-row">
            <span>
              xG 样本
              <InfoTooltip
                title="xG 样本"
                text="可用的预期进球样本数量。xG 能补充比分无法体现的机会质量；缺失时模型仍可运行，但对攻防质量的判断会更粗。"
              />
            </span>
            <b class="mono">{{ structuredXgCount }}</b>
          </div>
          <div class="input-row input-row-detail">
            <span>
              fallback
              <InfoTooltip
                title="降级链路"
                text="当结构化数据不足、模型无法拟合或外部源失败时采用的替代逻辑。展开详情可以看到具体降级原因和诊断字段。"
              />
            </span>
            <div class="fallback-detail">
              <b>{{ modelDiagnostics.fit_status || modelDiagnostics.fallback_reason || '-' }}</b>
              <button class="ghost-btn-xs" type="button" @click="diagOpen = !diagOpen">
                详情 {{ diagOpen ? '▴' : '▾' }}
              </button>
              <div v-if="diagOpen" class="diag-block">
                <div v-for="row in diagnosticRows" :key="row.key" class="diag-row">
                  <span class="mono">{{ row.key }}</span>
                  <span>{{ row.value }}</span>
                </div>
                <div v-if="warnings.length" class="diag-warnings">
                  <small>降级链路:</small>
                  <ul>
                    <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="action-section">
        <button class="primary-btn" type="button" :disabled="!canContinue" @click="enterPredictionRun">
          进入比赛场景推演
          <span>→</span>
        </button>
      </section>
    </div>

    <div class="system-logs">
      <div class="log-header">
        <span class="log-title">PREDICTION CONFIG</span>
        <span class="log-id">{{ predictionConfigId || projectData?.project_id || 'NO_CONFIG' }}</span>
      </div>
      <div ref="logContent" class="log-content">
        <div v-for="(log, idx) in systemLogs" :key="idx" class="log-line">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
      </div>
    </div>

    <PlayerRosterDrawer
      :open="rosterDrawerOpen"
      mode="config"
      :config-id="predictionConfigId || ''"
      :dataset-id="config?.player_dataset_id || preview?.player_dataset_id || ''"
      :roster="roster"
      @update:open="rosterDrawerOpen = $event"
      @close="rosterDrawerOpen = false"
    />
    <DatasetPickerModal
      :open="datasetPickerOpen"
      :datasets="datasets"
      :current-dataset-id="config?.player_dataset_id || preview?.player_dataset_id || ''"
      :loading="isDatasetSwitching"
      @close="datasetPickerOpen = false"
      @apply="applyDatasetSelection"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getPredictionCoachAgents,
  getPredictionCoachDiscussions,
  getPredictionConfig,
  getPredictionConfigProgress,
  getPredictionConfigRoster,
  getPredictionConfigStatus,
  getPredictionConfigTeamStrengths,
  getPredictionDatasets,
  getLatestPredictionConfig,
  getPredictionResumePolicy,
  getPredictionScenarioDesign,
  preparePredictionConfig,
  switchPredictionConfigDataset
} from '../api/prediction'
import DataSourcesCard from './prediction/DataSourcesCard.vue'
import DatasetPickerModal from './prediction/DatasetPickerModal.vue'
import EvidenceChip from './prediction/EvidenceChip.vue'
import InfoTooltip from './prediction/InfoTooltip.vue'
import LLMBudgetCustomPanel from './prediction/LLMBudgetCustomPanel.vue'
import LLMBudgetMeter from './prediction/LLMBudgetMeter.vue'
import LLMBudgetSelector from './prediction/LLMBudgetSelector.vue'
import PlayerRosterDrawer from './prediction/PlayerRosterDrawer.vue'
import RosterSummaryCard from './prediction/RosterSummaryCard.vue'
import ScenarioWeightDelta from './prediction/ScenarioWeightDelta.vue'
import {
  orderTeamStrengths,
  teamStrengthRatingItems,
} from '../utils/step2TeamStrength.js'
import { estimateLLMBudgetCalls, MAX_LLM_HARD_CAP_CALLS } from '../utils/llmBudget.js'
import { regenerateStepWithConfirm } from '../utils/workflowRegenerate.js'

const props = defineProps({
  projectData: Object,
  graphData: Object,
  systemLogs: { type: Array, default: () => [] }
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const ROLE_ORDER = ['head_coach', 'attack', 'defense', 'transition', 'set_piece', 'goalkeeper', 'fitness', 'risk']

const defaultMaxProfile = () => ({
  profile_key: 'max',
  coach_panel_roles: ['head_coach', 'attack', 'defense', 'transition', 'set_piece', 'goalkeeper', 'fitness', 'risk'],
  coach_deliberation_rounds: 2,
  enable_llm_data_extraction: true,
  narrative_polish_count: 9,
  analyst_note_groups: ['baseline', 'home_upside', 'away_upside', 'home_error', 'away_error', 'volatility'],
  coach_review_roles: ['head_coach', 'risk'],
  n_sims: 3000,
  enable_statsbomb: true,
  hard_cap_calls: MAX_LLM_HARD_CAP_CALLS
})

const BUDGET_PROFILE_FIELDS = [
  'profile_key',
  'coach_panel_roles',
  'coach_deliberation_rounds',
  'enable_llm_data_extraction',
  'narrative_polish_count',
  'analyst_note_groups',
  'coach_review_roles',
  'n_sims',
  'enable_statsbomb',
  'hard_cap_calls'
]

const logContent = ref(null)
const predictionConfigId = ref(null)
const config = ref(null)
const agents = ref([])
const discussions = ref([])
const scenarioCases = ref([])
const resumeNodes = ref([])
const teamStrengths = ref([])
const roster = ref(null)
const preview = ref(null)
const datasets = ref([])
const isPreparing = ref(false)
const isDatasetSwitching = ref(false)
const errorMessage = ref('')
const rosterDrawerOpen = ref(false)
const datasetPickerOpen = ref(false)
const diagOpen = ref(false)
const selectedProfile = ref(defaultMaxProfile())
const budgetTouched = ref(false)
const pendingBudgetProfile = ref(null)
const progressTimer = ref(null)
const seenProgressKeys = ref(new Set())

const statusLabel = computed(() => {
  if (isPreparing.value) return 'preparing'
  if (!config.value && preview.value) return 'preview'
  return config.value?.status || 'pending'
})

const modelInput = computed(() => config.value?.model_input_snapshot || {})
const modelDiagnostics = computed(() => modelInput.value?.scientific_model_diagnostics || {})
const warnings = computed(() => modelInput.value?.warnings || [])
const structuredInputs = computed(() => modelInput.value?.structured_inputs || {})
const structuredRecentMatches = computed(() => (
  modelInput.value?.structured_recent_matches
  || structuredInputs.value?.structured_recent_matches
  || []
))
const structuredXgSamples = computed(() => (
  modelInput.value?.structured_xg_samples
  || structuredInputs.value?.structured_xg_samples
  || []
))
const structuredMatchCount = computed(() => structuredRecentMatches.value.length)
const structuredXgCount = computed(() => structuredXgSamples.value.length)
const orderedTeamStrengths = computed(() => orderTeamStrengths(teamStrengths.value))

const rosterSummary = computed(() => config.value?.dataset_summary || preview.value?.dataset_summary || null)
const rosterSummaryLabel = computed(() => {
  const total = Number(rosterSummary.value?.home?.players_count || 0) + Number(rosterSummary.value?.away?.players_count || 0)
  if (total) return `${total}人`
  const rosterTotal = (roster.value?.teams || []).reduce((sum, team) => sum + (team.players?.length || 0), 0)
  return rosterTotal ? `${rosterTotal}人` : '-'
})

const externalSources = computed(() => normalizeExternalSources(config.value?.external_sources || preview.value?.external_sources || []))
const externalSourcesActive = computed(() => externalSources.value.filter(src => src.status === 'synced').length)
const externalSourcesTotal = computed(() => externalSources.value.length)

const budgetLedger = computed(() => {
  if (pendingBudgetProfile.value) {
    const profile = pendingBudgetProfile.value
    return {
      total_calls: 0,
      cached: 0,
      hard_cap: Number(profile.hard_cap_calls ?? profile.hard_cap ?? 0),
      calls_planned: estimateBudgetCalls(profile),
      failures: [],
      pending: true
    }
  }
  const llmBudget = config.value?.llm_budget || {}
  const ledger = config.value?.metadata?.llm_ledger || config.value?.config_metadata?.llm_ledger || {}
  const budgetSource = Object.keys(llmBudget).length ? llmBudget : selectedProfile.value
  return {
    ...ledger,
    total_calls: ledger.total_calls ?? llmBudget.calls_used ?? 0,
    cached: ledger.cached ?? llmBudget.calls_cached ?? 0,
    calls_planned: llmBudget.calls_planned ?? ledger.calls_planned ?? estimateBudgetCalls(budgetSource),
    hard_cap: ledger.hard_cap ?? llmBudget.hard_cap ?? llmBudget.hard_cap_calls ?? selectedProfile.value.hard_cap_calls ?? 0,
    failures: ledger.failures || []
  }
})

const budgetUsed = computed(() => Number(budgetLedger.value.total_calls || 0))
const budgetPlanned = computed(() => Number(budgetLedger.value.calls_planned ?? estimateBudgetCalls(selectedProfile.value) ?? 0))
const budgetCap = computed(() => Number(budgetLedger.value.hard_cap || selectedProfile.value.hard_cap_calls || 0))
const budgetClass = computed(() => {
  if (budgetCap.value > 0 && budgetUsed.value > budgetCap.value) return 'metric-value-error'
  if (budgetCap.value > 0 && budgetUsed.value >= budgetCap.value) return 'metric-value-warning'
  return ''
})

const enabledRoles = computed(() => new Set(selectedProfile.value.coach_panel_roles || []))
const spokenRoles = computed(() => {
  const roles = new Set()
  const byRole = budgetLedger.value.by_role || {}
  Object.keys(byRole).forEach(role => roles.add(role))
  discussions.value.forEach(discussion => {
    const metadata = discussion.metadata || {}
    ;[metadata.role, metadata.agent_role, discussion.agent_role].filter(Boolean).forEach(role => roles.add(role))
    ;(metadata.roles || metadata.coach_roles || []).forEach(role => roles.add(role))
  })
  return roles
})

const agentRoleCounts = computed(() => {
  const counts = agents.value.reduce((acc, agent) => {
    acc[agent.role] = (acc[agent.role] || 0) + 1
    return acc
  }, {})
  return ROLE_ORDER.map(role => ({ role, count: counts[role] || 0 }))
})

const diagnosticRows = computed(() => Object.entries(modelDiagnostics.value || {}).map(([key, value]) => ({
  key,
  value: typeof value === 'object' ? JSON.stringify(value) : String(value)
})))

const estimatedCalls = computed(() => estimateBudgetCalls(selectedProfile.value))

const canContinue = computed(() => (
  Boolean(predictionConfigId.value) && config.value?.status === 'ready' && !isPreparing.value
))

const graphEntities = computed(() => {
  const nodes = props.graphData?.nodes || []
  return nodes.slice(0, 120).map(node => ({
    name: node.name || node.label || node.id,
    entity_type: node.entity_type || node.type || node.labels?.[0],
    summary: node.summary || node.description || ''
  }))
})

const addLog = (message) => emit('add-log', message)

const prepareConfig = async (forceRegenerate = false, datasetId = null) => {
  if (!props.projectData?.project_id || isPreparing.value) return
  if (forceRegenerate && predictionConfigId.value) {
    try {
      const regenerated = await regenerateStepWithConfirm({
        projectId: props.projectData.project_id,
        step: 2,
        reason: 'step2_reconfigure',
        onBefore: () => {
          predictionConfigId.value = null
          config.value = null
          agents.value = []
          discussions.value = []
          scenarioCases.value = []
          resumeNodes.value = []
          teamStrengths.value = []
          roster.value = null
          emit('update-status', 'processing')
          addLog('Step2 已重新配置，旧 Step3/Step4/Step5 已失效')
        },
      })
      if (!regenerated) return
    } catch (err) {
      errorMessage.value = err.message || '重新配置失败'
      addLog(`重新配置失败: ${errorMessage.value}`)
      return
    }
  }

  isPreparing.value = true
  errorMessage.value = ''
  emit('update-status', 'processing')
  addLog(forceRegenerate ? '重新生成预测配置' : '准备或复用预测配置')

  try {
    const payload = {
      graph_id: props.projectData.graph_id,
      prediction_requirement: props.projectData.simulation_requirement || '',
      force_regenerate: forceRegenerate,
      graph_entities: graphEntities.value
    }

    const playerDatasetId = datasetId || config.value?.player_dataset_id || preview.value?.player_dataset_id
    if (playerDatasetId) payload.player_dataset_id = playerDatasetId
    const shouldSendBudget = forceRegenerate || budgetTouched.value || !config.value
    if (shouldSendBudget) {
      payload.llm_budget = serializeBudgetProfile(selectedProfile.value)
      pendingBudgetProfile.value = normalizeBudgetProfile(payload.llm_budget)
    } else {
      pendingBudgetProfile.value = null
    }

    const response = await preparePredictionConfig(props.projectData.project_id, payload)
    predictionConfigId.value = response.data.prediction_config_id
    startProgressPolling()
    await loadConfigArtifacts(predictionConfigId.value)

    if (config.value?.status === 'ready') {
      emit('update-status', 'completed')
      addLog(`预测配置已就绪: ${predictionConfigId.value}`)
      stopProgressPolling()
    }
  } catch (err) {
    errorMessage.value = err.message || 'unknown error'
    emit('update-status', 'error')
    addLog(`预测配置准备失败: ${errorMessage.value}`)
    stopProgressPolling()
  } finally {
    isPreparing.value = false
    pendingBudgetProfile.value = null
  }
}

const loadConfigArtifacts = async (configId) => {
  if (!configId) return
  const [configRes, agentsRes, discussionsRes, scenarioRes, resumeRes, strengthsRes, rosterRes] = await Promise.all([
    getPredictionConfig(configId),
    getPredictionCoachAgents(configId),
    getPredictionCoachDiscussions(configId),
    getPredictionScenarioDesign(configId),
    getPredictionResumePolicy(configId),
    getPredictionConfigTeamStrengths(configId),
    getPredictionConfigRoster(configId)
  ])

  config.value = configRes.data
  agents.value = agentsRes.data?.coach_agents || []
  discussions.value = discussionsRes.data?.coach_discussions || []
  scenarioCases.value = scenarioRes.data?.scenario_cases || []
  resumeNodes.value = resumeRes.data?.resume_nodes || []
  teamStrengths.value = strengthsRes.data?.team_strengths || []
  roster.value = rosterRes.data
  preview.value = null

  if (config.value?.llm_budget) {
    selectedProfile.value = normalizeBudgetProfile(config.value.llm_budget)
  }
  pendingBudgetProfile.value = null
}

const startProgressPolling = () => {
  stopProgressPolling()
  seenProgressKeys.value = new Set()
  if (!predictionConfigId.value) return
  progressTimer.value = setInterval(pollProgress, 1500)
}

const stopProgressPolling = () => {
  if (progressTimer.value) {
    clearInterval(progressTimer.value)
    progressTimer.value = null
  }
}

const pollProgress = async () => {
  if (!predictionConfigId.value) return
  try {
    const response = await getPredictionConfigProgress(predictionConfigId.value)
    const data = response.data || {}
    appendProgressMessages(data.progress_messages || data.messages || [])
    if (data.status === 'ready') {
      stopProgressPolling()
      await loadConfigArtifacts(predictionConfigId.value)
      isPreparing.value = false
      emit('update-status', 'completed')
    }
  } catch (err) {
    const status = await getPredictionConfigStatus(predictionConfigId.value)
    if (status.data?.status === 'ready') stopProgressPolling()
  }
}

const appendProgressMessages = (messages) => {
  messages.forEach(message => {
    const key = `${message.timestamp || ''}:${message.milestone || ''}:${message.text || ''}`
    if (seenProgressKeys.value.has(key)) return
    seenProgressKeys.value.add(key)
    addLog(`[${message.milestone || 'progress'}] ${message.text || ''}`)
  })
}

const enterPredictionRun = () => {
  if (!canContinue.value) return
  addLog('进入比赛场景推演')
  emit('update-status', 'completed')
  emit('next-step', { predictionConfigId: predictionConfigId.value })
}

const refreshSources = () => {
  addLog('刷新数据源快照')
  prepareConfig(true)
}

const openRosterDrawer = async () => {
  if (!roster.value && predictionConfigId.value) {
    const response = await getPredictionConfigRoster(predictionConfigId.value)
    roster.value = response.data
  }
  rosterDrawerOpen.value = true
}

const openDatasetPicker = async () => {
  await loadDatasets()
  datasetPickerOpen.value = true
}

const loadDatasets = async () => {
  const response = await getPredictionDatasets()
  datasets.value = response.data?.datasets || []
}

const applyDatasetSelection = async (playerDatasetId) => {
  if (!playerDatasetId) return
  if (!predictionConfigId.value) {
    await prepareConfig(true, playerDatasetId)
    datasetPickerOpen.value = false
    return
  }
  isDatasetSwitching.value = true
  errorMessage.value = ''
  try {
    await switchPredictionConfigDataset(predictionConfigId.value, playerDatasetId)
    datasetPickerOpen.value = false
    addLog(`切换名册数据集: ${playerDatasetId}`)
    await prepareConfig(true, playerDatasetId)
  } catch (err) {
    errorMessage.value = err.message || '切换数据集失败'
    addLog(`切换数据集失败: ${errorMessage.value}`)
  } finally {
    isDatasetSwitching.value = false
  }
}

const selectBudgetProfile = (profile) => {
  selectedProfile.value = normalizeBudgetProfile(profile)
  budgetTouched.value = true
}

const updateCustomBudget = (profile) => {
  selectedProfile.value = normalizeBudgetProfile(profile)
  budgetTouched.value = true
}

const isRoleEnabled = (role) => enabledRoles.value.has(role)
const isRoleSpoken = (role) => spokenRoles.value.has(role)

const roleLabel = (role) => ({
  head_coach: '战术主教练',
  attack: '进攻教练',
  defense: '防守教练',
  transition: '转换/压迫教练',
  set_piece: '定位球教练',
  goalkeeper: '门将/防线教练',
  fitness: '体能/换人教练',
  risk: '风险/裁判/天气教练'
}[role] || role)

const roleDescription = (role) => ({
  head_coach: '综合各专项意见，形成整体战术判断、基准比分倾向和关键胜负手。',
  attack: '关注进攻创造、锋线效率、边路突破、禁区触球和关键球员终结能力。',
  defense: '关注防线结构、禁区保护、中卫对抗、边后卫身后空间和失误风险。',
  transition: '关注高位压迫、反抢、防反速度、二点球归属和攻守转换中的空间暴露。',
  set_piece: '关注角球、任意球、后点保护、身高对抗和定位球进失球风险。',
  goalkeeper: '关注门将扑救、出球、高球处理、身后球清理和门将对高位防线的保护。',
  fitness: '关注旅行、时差、赛程负荷、伤停存疑、替补冲击力和换人窗口。',
  risk: '关注裁判尺度、红黄牌、天气、草皮、赛制压力和极端比分波动。'
}[role] || '该角色从特定专业角度审视比赛，并影响场景权重和风险提示。')

const stateLabel = (state) => ({
  normal: '正常',
  overperform: '超常',
  underperform: '低迷'
}[state] || state)

const spaceLabel = (space) => ({
  baseline: '基准',
  home_upside: '主队上行',
  away_upside: '客队上行',
  home_error: '主队失误',
  away_error: '客队失误',
  volatility: '高波动'
}[space] || space)

const ratingItems = teamStrengthRatingItems

const signed = (value) => {
  const numeric = Number(value || 0)
  return numeric > 0 ? `+${numeric}` : String(numeric)
}

const homeAwayText = (team) => {
  const adjustment = Number(team.home_away_adjustment || 0)
  if (!adjustment) return '+0 (中立)'
  const reason = team.home_away_adjustment_reason || '主队顺位'
  return `${adjustment > 0 ? '+' : ''}${adjustment} (${reason})`
}

const formatTokens = (tokens) => {
  const numeric = Number(tokens || 0)
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}k tok`
  return `${numeric} tok`
}

const normalizeExternalSources = (sources) => (sources || []).map(src => ({
  key: src.key,
  label: src.label,
  status: src.status || 'skipped',
  rows: src.rows,
  fetched_at: src.fetched_at,
  etag: src.etag,
  error: src.error,
  url: src.url
}))

const normalizeBudgetProfile = (profile = {}) => {
  const normalized = {
    ...defaultMaxProfile(),
    ...profile,
    profile_key: profile.profile_key || 'custom'
  }
  normalized.coach_panel_roles = [...(profile.coach_panel_roles || normalized.coach_panel_roles || [])]
  normalized.analyst_note_groups = [...(profile.analyst_note_groups || normalized.analyst_note_groups || [])]
  normalized.coach_review_roles = [...(profile.coach_review_roles || normalized.coach_review_roles || [])]
  normalized.hard_cap_calls = Number(profile.hard_cap_calls ?? profile.hard_cap ?? normalized.hard_cap_calls ?? 1)
  return normalized
}

const serializeBudgetProfile = (profile = {}) => {
  const normalized = normalizeBudgetProfile(profile)
  return BUDGET_PROFILE_FIELDS.reduce((payload, field) => {
    payload[field] = Array.isArray(normalized[field]) ? [...normalized[field]] : normalized[field]
    return payload
  }, {})
}

const estimateBudgetCalls = estimateLLMBudgetCalls

const applyProjectPreview = () => {
  const payload = props.projectData?.project_metadata?.step2_preview
  preview.value = payload && typeof payload === 'object' ? payload : null
  if (!config.value && preview.value?.roster) {
    roster.value = preview.value.roster
  }
}

const initializeStep2 = async () => {
  if (!props.projectData?.project_id) return
  addLog('Step2 预测配置准备初始化')
  applyProjectPreview()
  try {
    const latest = await getLatestPredictionConfig(props.projectData.project_id, {
      graph_id: props.projectData.graph_id || undefined
    })
    if (latest.data?.prediction_config_id) {
      predictionConfigId.value = latest.data.prediction_config_id
      await loadConfigArtifacts(predictionConfigId.value)
      emit('update-status', 'completed')
      addLog(`加载已有预测配置: ${predictionConfigId.value}`)
    }
  } catch (err) {
    addLog(`读取已有预测配置失败: ${err.message}`)
  }
}

watch(() => props.systemLogs?.length, () => {
  nextTick(() => {
    if (logContent.value) {
      logContent.value.scrollTop = logContent.value.scrollHeight
    }
  })
})

watch(() => props.projectData?.project_id, (value) => {
  if (value && !predictionConfigId.value && !isPreparing.value) {
    initializeStep2()
  }
})

onMounted(() => {
  initializeStep2()
})

onBeforeUnmount(() => {
  stopProgressPolling()
})
</script>

<style scoped>
.prediction-setup-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.scroll-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.setup-header,
.setup-section,
.action-section,
.setup-error {
  background: #FFF;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  padding: 20px;
}

.setup-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.eyebrow,
.metric-label,
.section-index,
.log-title,
.log-id,
.mono {
  font-family: 'JetBrains Mono', monospace;
}

.eyebrow {
  color: #FF4500;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .08em;
}

h2, h3, p {
  margin: 0;
}

h2 {
  margin-top: 8px;
  font-size: 28px;
  font-weight: 650;
}

.setup-header p {
  margin-top: 10px;
  color: #555;
  line-height: 1.6;
}

.ghost-btn,
.primary-btn {
  border: 1px solid #111;
  background: #FFF;
  color: #111;
  border-radius: 6px;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}

.primary-btn {
  background: #111;
  color: #FFF;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.ghost-btn:disabled,
.primary-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.ghost-btn-xs {
  padding: 4px 8px;
  font-size: 11px;
  border: 1px solid #111;
  background: #FFF;
  border-radius: 4px;
  cursor: pointer;
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

.spinner.dark {
  border-color: rgba(17,17,17,.2);
  border-top-color: #111;
}

@keyframes spin { to { transform: rotate(360deg); } }

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 12px;
}

.metric {
  background: #FFF;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  padding: 14px;
  min-width: 0;
}

.metric-label {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #777;
  font-size: 11px;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.metric-value {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 800;
}

.metric-value-stack {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.metric-subvalue {
  color: #999;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}

.metric-value-warning {
  color: #8A4B00;
}

.metric-value-error {
  color: #8A1F2D;
}

.budget-lock-note {
  margin-top: 12px;
  color: #777;
  font-size: 12px;
  line-height: 1.5;
}

.setup-error {
  border-color: #F5C2C7;
  background: #FFF5F5;
  color: #8A1F2D;
  display: flex;
  gap: 10px;
}

.section-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.section-title-row h3 {
  min-width: 0;
}

.section-index {
  color: #FF4500;
  font-weight: 800;
}

.data-source-roster-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.input-grid,
.coach-grid,
.team-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.input-row,
.coach-role,
.team-card,
.discussion-item,
.scenario-cell {
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  background: #FCFCFC;
  padding: 12px;
  min-width: 0;
}

.input-row,
.coach-role,
.discussion-item,
.team-head,
.scenario-head {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
}

.input-row span,
.coach-role span {
  color: #666;
}

.input-row > span,
.coach-role-label,
.resume-head span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.resume-head span {
  color: #FFF;
}

.input-row b,
.coach-role b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.input-row-detail {
  align-items: flex-start;
}

.fallback-detail {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.diag-block {
  flex: 1 0 100%;
  border-top: 1px solid #EFEFEF;
  padding-top: 8px;
  margin-top: 4px;
  display: grid;
  gap: 6px;
}

.diag-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 8px;
  font-size: 12px;
  color: #555;
}

.diag-row span:last-child {
  overflow-wrap: anywhere;
}

.diag-warnings {
  color: #8A4B00;
  font-size: 12px;
}

.diag-warnings ul {
  margin: 4px 0 0 16px;
}

.coach-role {
  position: relative;
}

.coach-role-disabled {
  opacity: .35;
}

.coach-role-disabled::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(45deg, transparent 49%, #EAEAEA 49%, #EAEAEA 51%, transparent 51%);
  background-size: 8px 8px;
  pointer-events: none;
}

.coach-spoken {
  color: #FF4500 !important;
  font-size: 12px;
  font-weight: 800;
  margin-left: 4px;
}

.coach-budget-hint {
  font-size: 11px;
  color: #999;
  font-family: 'JetBrains Mono', monospace;
}

.discussion-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.discussion-item p {
  margin-top: 6px;
  color: #555;
  line-height: 1.5;
  font-size: 13px;
}

.discussion-cost {
  display: block;
  margin-top: 6px;
  color: #999;
  font-size: 11px;
}

.scenario-matrix {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.scenario-head b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-cell small {
  display: block;
  margin-top: 6px;
  color: #777;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.state-line {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.state-line span {
  border: 1px solid #E1E1E1;
  background: #FFF;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 12px;
}

.scenario-cell p,
.scenario-cell em {
  display: block;
  margin: 10px 0 0;
  color: #555;
  line-height: 1.45;
  font-style: normal;
  font-size: 12px;
}

.scenario-cell em {
  color: #8A4B00;
}

.resume-table {
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  overflow: hidden;
}

.resume-row {
  display: grid;
  grid-template-columns: 70px minmax(0, 1fr) 88px 120px;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid #EFEFEF;
  font-size: 13px;
}

.resume-row:last-child {
  border-bottom: none;
}

.resume-head {
  background: #111;
  color: #FFF;
  font-weight: 800;
}

.team-head {
  justify-content: flex-start;
}

.team-head span {
  color: #FF4500;
  font-weight: 800;
  font-size: 12px;
}

.team-head b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.team-head em {
  margin-left: auto;
  color: #666;
  font-style: normal;
  font-size: 12px;
}

.rating-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin-top: 10px;
}

.rating-cell {
  background: #FFF;
  border: 1px solid #EFEFEF;
  border-radius: 4px;
  padding: 7px 8px;
  color: #666;
  font-size: 12px;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 5px;
  min-height: 58px;
}

.rating-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  min-height: 20px;
}

.rating-name {
  color: #666;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rating-score {
  color: #111;
  font-size: 20px;
  line-height: 1.05;
  font-weight: 800;
  justify-self: start;
  white-space: nowrap;
}

.rating-source-chip {
  min-width: 0;
  flex: 0 0 auto;
}

.team-adjustments {
  margin-top: 10px;
  border-top: 1px solid #EFEFEF;
  padding-top: 10px;
  display: grid;
  gap: 6px;
  color: #666;
  font-size: 12px;
}

.team-adjustments small {
  color: #777;
}

.mini-empty {
  border: 1px dashed #DDD;
  border-radius: 8px;
  padding: 16px;
  color: #777;
  text-align: center;
  font-size: 13px;
  grid-column: 1 / -1;
}

.action-section {
  display: flex;
  justify-content: flex-end;
}

.system-logs {
  height: 150px;
  background: #111;
  color: #EEE;
  display: flex;
  flex-direction: column;
}

.log-header {
  display: flex;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #333;
  color: #AAA;
  font-size: 12px;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 10px 16px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.log-line {
  display: flex;
  gap: 10px;
  line-height: 1.6;
}

.log-time {
  color: #777;
  flex: 0 0 auto;
}

@media (max-width: 1100px) {
  .metrics-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .scenario-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .metrics-grid,
  .data-source-roster-grid,
  .input-grid,
  .coach-grid,
  .team-grid,
  .scenario-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .setup-header,
  .header-actions {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 640px) {
  .metrics-grid,
  .data-source-roster-grid,
  .input-grid,
  .coach-grid,
  .team-grid,
  .scenario-matrix {
    grid-template-columns: 1fr;
  }

  .resume-row {
    grid-template-columns: 52px minmax(0, 1fr);
  }

  .rating-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
