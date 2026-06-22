import snapshot from './api-snapshot.json'

const PROJECT_ID = 'proj_2aa9775eb4c6'
const GRAPH_ID = snapshot.meta.graphId
const CONFIG_ID = snapshot.meta.predictionConfigId
const RUN_ID = snapshot.meta.predictionRunId
const REPORT_ID = snapshot.meta.reportId
const CONVERSATION_ID = '80e62f97-dffc-40c5-bebe-9d9bf25edada'
const ONTOLOGY_DELAY_MS = 5200
const STEP2_PROGRESS_STEPS = [
  { milestone: 'loading_squads', text: '加载 突尼斯 日本 名册', progress_percent: 10 },
  { milestone: 'querying_graph', text: '查询图谱伤停事实 (48 球员)', progress_percent: 20 },
  { milestone: 'extracting_facts', text: 'LLM 抽取上传文档结构化事实', progress_percent: 30 },
  { milestone: 'fetching_external', text: '拉取外部数据源 (intl_results, national_elo, fifa_ranking, statsbomb_xg)', progress_percent: 40 },
  { milestone: 'fitting_model', text: '拟合 Dixon-Coles (1600 场)', progress_percent: 55 },
  { milestone: 'estimating_strengths', text: '聚合球员→球队强度', progress_percent: 65 },
  { milestone: 'panel_role_head_coach', text: '战术主教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_attack', text: '进攻教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_defense', text: '防守教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_transition', text: '转换/压迫教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_set_piece', text: '定位球教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_goalkeeper', text: '门将/防线教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_fitness', text: '体能/换人教练 评审中...', progress_percent: 70 },
  { milestone: 'panel_role_risk', text: '风险/裁判/天气教练 评审中...', progress_percent: 70 },
  { milestone: 'applying_weights', text: '应用 9 场景权重', progress_percent: 82 },
  { milestone: 'persisting', text: '落库', progress_percent: 92 },
  { milestone: 'ready', text: '配置就绪', progress_percent: 100, status: 'ready' },
]
const STEP3_PROGRESS_STEPS = [
  { status: 'queued', current_phase: 'queued', progress_percent: 1, message: '比赛推演正在进入 Celery 队列' },
  { status: 'running', current_phase: 'loading_config', progress_percent: 8, message: '读取预测配置' },
  { status: 'running', current_phase: 'running_simulation', progress_percent: 28, message: '执行九场景比赛模拟' },
  { status: 'running', current_phase: 'persisting_artifacts', progress_percent: 88, message: '保存比分、事件链和复核结果' },
  { status: 'completed', current_phase: 'completed', progress_percent: 100, message: '九场景比赛推演完成' },
]
const STEP4_AGENT_VISIBLE_COUNTS = [2, 3, 4, 6, 8, 10, 12, 14, 16, 17]
const STEP4_AGENT_TIMELINE_SECONDS = [0, 8, 14, 20, 26, 32, 38, 44, 50, 56]
const INJURY_EVIDENCE = {
  id: 'static-demo-jpn-kubo-out',
  name: '久保建英',
  player: '久保建英',
  player_name: '久保建英',
  status: 'out',
  team_iso3: 'JPN',
  evidence_span: '首轮第75分钟与 Dumfries 相撞致左膝伤，MRI 确认几乎无望出战第二轮。',
}
const BUILD_STEPS = [
  { progress: 20, graphRatio: 0.2, message: 'GraphRAG 构建 1/5：写入核心球队、比赛与赛制节点' },
  { progress: 24, graphRatio: 0.2, message: 'GraphRAG 构建 1/5：核心节点索引同步中' },
  { progress: 28, graphRatio: 0.2, message: 'GraphRAG 构建 1/5：核心节点关系校验中' },
  { progress: 32, graphRatio: 0.2, message: 'GraphRAG 构建 1/5：准备扩展球员与教练节点' },
  { progress: 36, graphRatio: 0.2, message: 'GraphRAG 构建 1/5：核心快照稳定' },
  { progress: 40, graphRatio: 0.4, message: 'GraphRAG 构建 2/5：写入球员、教练与阵型节点' },
  { progress: 44, graphRatio: 0.4, message: 'GraphRAG 构建 2/5：球员证据摘要生成中' },
  { progress: 48, graphRatio: 0.4, message: 'GraphRAG 构建 2/5：教练与阵型关系校验中' },
  { progress: 52, graphRatio: 0.4, message: 'GraphRAG 构建 2/5：准备伤停、赛程和天气节点' },
  { progress: 56, graphRatio: 0.4, message: 'GraphRAG 构建 2/5：阵容快照稳定' },
  { progress: 60, graphRatio: 0.6, message: 'GraphRAG 构建 3/5：写入伤停、赛程、天气和状态证据' },
  { progress: 64, graphRatio: 0.6, message: 'GraphRAG 构建 3/5：证据节点摘要生成中' },
  { progress: 68, graphRatio: 0.6, message: 'GraphRAG 构建 3/5：风险关系校验中' },
  { progress: 72, graphRatio: 0.6, message: 'GraphRAG 构建 3/5：准备战术与对位关系' },
  { progress: 76, graphRatio: 0.6, message: 'GraphRAG 构建 3/5：证据快照稳定' },
  { progress: 80, graphRatio: 0.8, message: 'GraphRAG 构建 4/5：写入战术、对位和关键事件关系' },
  { progress: 84, graphRatio: 0.8, message: 'GraphRAG 构建 4/5：关系边去重中' },
  { progress: 88, graphRatio: 0.8, message: 'GraphRAG 构建 4/5：episode 绑定与一致性校验中' },
  { progress: 92, graphRatio: 0.8, message: 'GraphRAG 构建 4/5：准备最终图谱快照' },
  { progress: 96, graphRatio: 0.8, message: 'GraphRAG 构建 4/5：关系快照稳定' },
  { progress: 100, graphRatio: 1, status: 'completed', message: 'GraphRAG 构建 5/5：图谱构建完成' },
]

const demoState = {
  graphTaskPolls: 0,
  graphBuildStarted: false,
  graphBuildCompleted: false,
  graphRatio: 1,
  step2Prepared: false,
  step2Preparing: false,
  step2ProgressPolls: 0,
  step3Started: false,
  step3Completed: false,
  step3StatusPolls: 0,
  reportStarted: false,
  reportCompleted: false,
  reportStartedAt: null,
  reportAgentPolls: 0,
  reportConsolePolls: 0,
}

const clone = (value) => JSON.parse(JSON.stringify(value))

const endpointBody = (key) => clone(snapshot.endpoints[key]?.data || { success: true, data: null })
const endpointData = (key, fallback = null) => clone(snapshot.endpoints[key]?.data?.data ?? fallback)

const ok = (data = null, extra = {}) => ({ success: true, data, ...extra })

const delay = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const resetReportGeneration = () => {
  demoState.reportStarted = false
  demoState.reportCompleted = false
  demoState.reportStartedAt = null
  demoState.reportAgentPolls = 0
  demoState.reportConsolePolls = 0
}

const startReportGeneration = () => {
  demoState.reportStarted = true
  demoState.reportCompleted = false
  demoState.reportStartedAt = Date.now()
  demoState.reportAgentPolls = 0
  demoState.reportConsolePolls = 0
}

const ensureReportGenerationStarted = () => {
  if (!demoState.reportStarted && !demoState.reportCompleted) {
    startReportGeneration()
  }
}

const reportElapsedSeconds = () => {
  if (!demoState.reportStartedAt) return 0
  return Math.max(0, (Date.now() - demoState.reportStartedAt) / 1000)
}

const refreshReportCompletionByTime = () => {
  if (demoState.reportStarted && reportElapsedSeconds() >= STEP4_AGENT_TIMELINE_SECONDS[STEP4_AGENT_TIMELINE_SECONDS.length - 1]) {
    demoState.reportCompleted = true
  }
}

const staticGraphTask = () => {
  const index = Math.min(demoState.graphTaskPolls, BUILD_STEPS.length - 1)
  const step = BUILD_STEPS[index]
  demoState.graphTaskPolls += 1
  demoState.graphRatio = step.graphRatio
  demoState.graphBuildCompleted = step.status === 'completed'

  return ok({
    task_id: 'static_graph_task',
    project_id: PROJECT_ID,
    graph_id: GRAPH_ID,
    status: step.status || 'running',
    progress: step.progress,
    message: step.message,
    result: step.status === 'completed'
      ? {
          graph_id: GRAPH_ID,
          node_count: snapshot.derived.rawCounts.graphNodes,
          edge_count: snapshot.derived.rawCounts.graphEdges,
          project_id: PROJECT_ID,
        }
      : null,
  })
}

const graphDataForCurrentBuild = () => {
  const graphData = endpointData('graphData', {})
  if (!demoState.graphBuildStarted || demoState.graphBuildCompleted) return graphData

  const ratio = demoState.graphRatio
  if (ratio >= 1) {
    demoState.graphBuildCompleted = true
    return graphData
  }

  const nodes = graphData.nodes || []
  const edges = graphData.edges || []
  const nodeCount = Math.max(0, Math.floor(nodes.length * ratio))
  const visibleNodeIds = new Set(nodes.slice(0, nodeCount).map((node) => node.uuid))
  const slicedEdges = edges
    .filter((edge) => visibleNodeIds.has(edge.source_node_uuid) && visibleNodeIds.has(edge.target_node_uuid))
    .slice(0, Math.max(0, Math.floor(edges.length * ratio)))

  return {
    ...graphData,
    nodes: nodes.slice(0, nodeCount),
    edges: slicedEdges,
    node_count: nodeCount,
    edge_count: slicedEdges.length,
  }
}

const withStaticArtifacts = (payload = {}) => ({
  ...payload,
  project_id: PROJECT_ID,
  graph_id: GRAPH_ID,
  prediction_config_id: payload.prediction_config_id || CONFIG_ID,
  prediction_run_id: payload.prediction_run_id || RUN_ID,
  report_id: payload.report_id || REPORT_ID,
})

const withWorkflowArtifacts = (workflow = {}) => ({
  ...workflow,
  active_artifacts: {
    ...(workflow.active_artifacts || {}),
    graph_id: GRAPH_ID,
    prediction_config_id: demoState.step2Prepared ? CONFIG_ID : null,
    prediction_run_id: demoState.step3Started || demoState.step3Completed ? RUN_ID : null,
    report_id: demoState.reportStarted || demoState.reportCompleted ? REPORT_ID : null,
  },
})

const projectResponse = () => {
  const body = endpointBody('project')
  body.data = withStaticArtifacts(body.data || {})
  if (demoState.graphBuildStarted && !demoState.graphBuildCompleted) {
    body.data.status = 'graph_building'
    body.data.graph_build_task_id = 'static_graph_task'
  } else {
    body.data.status = 'graph_completed'
  }
  return body
}

const ontologyProjectResponse = () => {
  const body = projectResponse()
  body.data.status = 'ontology_generated'
  body.data.graph_id = null
  body.data.graph_build_task_id = null
  return body
}

const noLatestConfigResponse = () => ok(null, {
  message: '静态演示：Step2 尚未生成预测配置',
})

const currentStep2ProgressIndex = () => Math.min(
  demoState.step2ProgressPolls,
  STEP2_PROGRESS_STEPS.length - 1,
)

const step2PreparingConfig = () => {
  const source = patchConfig(endpointBody('latestPredictionConfig')).data || {}
  const progress = STEP2_PROGRESS_STEPS[currentStep2ProgressIndex()]
  return ok({
    prediction_config_id: CONFIG_ID,
    project_id: PROJECT_ID,
    graph_id: GRAPH_ID,
    match_name: source.match_name,
    home_team: source.home_team,
    away_team: source.away_team,
    player_dataset_id: source.player_dataset_id,
    dataset_summary: source.dataset_summary,
    external_sources: source.external_sources,
    status: 'preparing',
    current_phase: progress.milestone,
    progress_percent: progress.progress_percent,
    fit_status: 'preparing',
    model_name: source.model_name,
    data_sufficiency: '-',
    llm_budget: source.llm_budget,
    metadata: {
      ...(source.metadata || {}),
      artifact_status: 'preparing',
    },
  })
}

const step2EmptyArtifact = (key) => {
  const payloads = {
    agents: { coach_agents: [] },
    discussions: { coach_discussions: [] },
    scenarios: { scenario_cases: [] },
    resume: { resume_nodes: [] },
    strengths: { team_strengths: [] },
  }
  return ok(payloads[key] || {})
}

const step2ProgressResponse = () => {
  const index = currentStep2ProgressIndex()
  const messages = STEP2_PROGRESS_STEPS.slice(0, index + 1).map((step, messageIndex) => ({
    ...step,
    timestamp: new Date(Date.now() - (index - messageIndex) * 1500).toISOString(),
  }))
  const current = STEP2_PROGRESS_STEPS[index]

  if (current.status === 'ready') {
    demoState.step2Preparing = false
    demoState.step2Prepared = true
  } else {
    demoState.step2ProgressPolls += 1
  }

  return ok({
    status: current.status || 'preparing',
    current_phase: current.milestone,
    current_milestone: current.milestone,
    progress_percent: current.progress_percent,
    progress_messages: messages,
  })
}

const workflowResponse = () => {
  const body = endpointBody('projectWorkflow')
  body.data = withWorkflowArtifacts(body.data || {})
  return body
}

const reportResponse = ({ forceComplete = false } = {}) => {
  if (!forceComplete) {
    ensureReportGenerationStarted()
    refreshReportCompletionByTime()
  }
  const body = endpointBody('report')
  body.data = withStaticArtifacts(body.data || {})
  body.data.active_prediction_run_id = RUN_ID
  body.data.simulation_id = RUN_ID
  body.data.report_metadata = {
    ...(body.data.report_metadata || {}),
    project_id: PROJECT_ID,
    graph_id: GRAPH_ID,
    prediction_config_id: CONFIG_ID,
    prediction_run_id: RUN_ID,
  }

  if (!forceComplete && demoState.reportStarted && !demoState.reportCompleted) {
    body.data.status = 'running'
    body.data.completed_at = null
    body.data.markdown_content = null
    if (demoState.reportAgentPolls <= 1) {
      body.data.outline = null
    }
  } else {
    body.data.status = 'completed'
  }

  return body
}

const currentStep3Status = () => {
  if (demoState.step3Completed) return STEP3_PROGRESS_STEPS[STEP3_PROGRESS_STEPS.length - 1]
  return STEP3_PROGRESS_STEPS[Math.min(demoState.step3StatusPolls, STEP3_PROGRESS_STEPS.length - 1)]
}

const predictionRunResponse = ({ advance = false } = {}) => {
  const current = currentStep3Status()
  if (advance && !demoState.step3Completed) {
    if (current.status === 'completed') {
      demoState.step3Completed = true
    } else {
      demoState.step3StatusPolls += 1
      if (STEP3_PROGRESS_STEPS[Math.min(demoState.step3StatusPolls, STEP3_PROGRESS_STEPS.length - 1)].status === 'completed') {
        demoState.step3Completed = true
      }
    }
  }

  const body = endpointBody('predictionRunStatus')
  body.data = withStaticArtifacts(body.data || {})
  const status = currentStep3Status()
  body.data.status = status.status
  body.data.current_phase = status.current_phase
  body.data.progress_percent = status.progress_percent
  body.data.metadata = {
    ...(body.data.metadata || {}),
    progress_messages: STEP3_PROGRESS_STEPS
      .slice(0, Math.min(demoState.step3StatusPolls + 1, STEP3_PROGRESS_STEPS.length))
      .map((step, index) => ({
        message: step.message,
        progress_percent: step.progress_percent,
        phase: step.current_phase,
        timestamp: new Date(Date.now() - (demoState.step3StatusPolls - index) * 2500).toISOString(),
      })),
  }
  return body
}

const history = () => ok([
  {
    project_id: PROJECT_ID,
    graph_id: GRAPH_ID,
    prediction_config_id: CONFIG_ID,
    prediction_run_id: RUN_ID,
    report_id: REPORT_ID,
    match_name: snapshot.derived.match.matchName,
    home_team: snapshot.derived.match.homeTeam,
    away_team: snapshot.derived.match.awayTeam,
    most_likely_score: snapshot.derived.prediction.mostLikelyScore,
    confidence: snapshot.derived.prediction.confidence,
    status: 'completed',
    created_at: snapshot.meta.projectCreatedAt,
    completed_at: snapshot.meta.reportCompletedAt,
  },
])

const markKuboUnavailable = (player) => {
  const names = [player?.name, player?.name_en, player?.name_zh].filter(Boolean)
  if (!names.some((name) => String(name).includes('Kubo') || String(name).includes('久保'))) return player
  return {
    ...player,
    availability: {
      ...(player.availability || {}),
      status: 'injured',
      evidence_refs: [INJURY_EVIDENCE],
      return_date: null,
    },
    expected_minutes_share: 0,
  }
}

const patchRoster = (body) => {
  const patched = clone(body)
  for (const team of patched.data?.teams || []) {
    if (team.iso3 !== 'JPN' && team.team_iso3 !== 'JPN' && team.name !== '日本') continue
    team.players = (team.players || []).map(markKuboUnavailable)
  }
  return patched
}

const patchTeamStrengths = (body) => {
  const patched = clone(body)
  for (const team of patched.data?.team_strengths || []) {
    if (team.team_iso3 !== 'JPN' && team.team_name !== '日本') continue
    team.injury_adjustment = Number(team.injury_adjustment || 0) - 4
    team.injury_evidence_refs = [INJURY_EVIDENCE]
    team.metadata = {
      ...(team.metadata || {}),
      available_players_count: Math.max(0, Number(team.metadata?.available_players_count || 25) - 1),
      injury_evidence_refs: [INJURY_EVIDENCE],
    }
  }
  return patched
}

const patchConfig = (body) => {
  const patched = clone(body)
  patched.data = {
    ...(patched.data || {}),
    prediction_config_id: CONFIG_ID,
    project_id: PROJECT_ID,
    graph_id: GRAPH_ID,
    status: 'ready',
  }
  patched.data.dataset_summary = {
    ...(patched.data.dataset_summary || {}),
    away: {
      ...(patched.data.dataset_summary?.away || {}),
      team_name: '日本',
      team_iso3: 'JPN',
      players_count: patched.data.dataset_summary?.away?.players_count || 25,
      available: 24,
      injured: 1,
      suspended: 0,
      doubtful: patched.data.dataset_summary?.away?.doubtful || 0,
    },
  }
  patched.data.model_input_snapshot = {
    ...(patched.data.model_input_snapshot || {}),
    extracted: {
      ...(patched.data.model_input_snapshot?.extracted || {}),
      injury_reports: [
        INJURY_EVIDENCE,
        ...(patched.data.model_input_snapshot?.extracted?.injury_reports || []).filter((item) => item.player !== '久保建英'),
      ],
    },
  }
  return patched
}

const datasets = () => ok({
  datasets: [
    {
      dataset_id: 'wc2026_fifa_v2',
      label: 'WC2026 FIFA Squad List v2',
      scope_label: 'fifa_world_cup_2026_squads',
      source_label: 'fifa_squad_list_v1_2026_06_12',
      created_at: snapshot.meta.generatedAt,
      is_default: true,
    },
  ],
})

const reportVisibleCount = () => {
  refreshReportCompletionByTime()
  const elapsed = reportElapsedSeconds()
  let index = 0
  for (let stepIndex = 0; stepIndex < STEP4_AGENT_TIMELINE_SECONDS.length; stepIndex += 1) {
    if (elapsed >= STEP4_AGENT_TIMELINE_SECONDS[stepIndex]) index = stepIndex
  }
  return STEP4_AGENT_VISIBLE_COUNTS[index]
}

const reportVisibleSectionCount = () => {
  const count = reportVisibleCount()
  if (count <= 3) return 0
  return Math.min(6, Math.floor((count - 3) / 2))
}

const reportSectionsResponse = () => {
  refreshReportCompletionByTime()
  const body = endpointBody('reportSections')
  const sections = body.data?.sections || []
  const visibleSections = demoState.reportCompleted ? sections.length : reportVisibleSectionCount()
  body.data = {
    ...(body.data || {}),
    sections: sections.slice(0, visibleSections),
    is_complete: demoState.reportCompleted || visibleSections >= sections.length,
  }
  return body
}

const completeReportSectionsResponse = () => {
  const body = endpointBody('reportSections')
  body.data = {
    ...(body.data || {}),
    is_complete: true,
  }
  return body
}

const reportProgress = () => {
  refreshReportCompletionByTime()
  const totalSections = endpointData('reportSections', {})?.sections?.length || 6
  const currentSection = demoState.reportCompleted ? totalSections : reportVisibleSectionCount()
  const progress = demoState.reportCompleted
    ? 100
    : Math.min(96, Math.max(5, Math.round((currentSection / totalSections) * 88)))
  return ok({
    report_id: REPORT_ID,
    status: demoState.reportCompleted ? 'completed' : 'running',
    progress,
    current_section: currentSection,
    total_sections: totalSections,
    message: demoState.reportCompleted ? '静态演示：报告已生成' : '静态演示：报告生成中',
  })
}

const agentLogPayload = (fromLine = 0, { forceComplete = false } = {}) => {
  if (!forceComplete) {
    ensureReportGenerationStarted()
    refreshReportCompletionByTime()
  }
  const outline = endpointData('report', {})?.outline || null
  const sections = endpointData('reportSections', {})?.sections || []
  const logs = [
    {
      timestamp: snapshot.meta.generatedAt,
      elapsed_seconds: 0,
      report_id: REPORT_ID,
      action: 'report_start',
      stage: 'planning',
      details: {
        prediction_run_id: RUN_ID,
        prediction_config_id: CONFIG_ID,
      },
    },
    {
      timestamp: snapshot.meta.generatedAt,
      elapsed_seconds: 2,
      report_id: REPORT_ID,
      action: 'planning_start',
      stage: 'planning',
      details: {
        message: '组装 Step1 图谱证据、Step2 配置和 Step3 九场景推演产物',
      },
    },
    {
      timestamp: snapshot.meta.generatedAt,
      elapsed_seconds: 4,
      report_id: REPORT_ID,
      action: 'planning_complete',
      stage: 'planning',
      details: { outline },
    },
    ...sections.flatMap((section) => {
      const sectionIndex = Number(section.section_index || 1)
      const sectionTitle = outline?.sections?.[sectionIndex - 1]?.title
      const elapsedBase = 4 + sectionIndex * 2
      return [
        {
          timestamp: snapshot.meta.generatedAt,
          elapsed_seconds: elapsedBase - 1,
          report_id: REPORT_ID,
          action: 'section_start',
          stage: 'generating',
          section_index: section.section_index,
          section_title: sectionTitle,
          details: { section_title: sectionTitle },
        },
        {
          timestamp: snapshot.meta.generatedAt,
          elapsed_seconds: elapsedBase,
          report_id: REPORT_ID,
          action: 'section_complete',
          stage: 'generating',
          section_index: section.section_index,
          section_title: sectionTitle,
          details: {
            content: section.content,
            filename: section.filename,
          },
        },
      ]
    }),
    {
      timestamp: snapshot.meta.generatedAt,
      elapsed_seconds: 18,
      report_id: REPORT_ID,
      action: 'report_complete',
      stage: 'completed',
      details: {
        report_id: REPORT_ID,
        total_sections: sections.length,
      },
    },
  ]
  const visibleCount = forceComplete || demoState.reportCompleted ? logs.length : reportVisibleCount()
  const visibleLogs = logs.slice(0, visibleCount)
  if (visibleCount >= logs.length) demoState.reportCompleted = true
  return ok({
    logs: visibleLogs.slice(Number(fromLine || 0)),
    from_line: Number(fromLine || 0),
    total_lines: logs.length,
    has_more: !demoState.reportCompleted,
  })
}

const consoleLogPayload = (fromLine = 0) => {
  ensureReportGenerationStarted()
  refreshReportCompletionByTime()
  const logs = [
    `[static-demo] Step4 report job created: ${REPORT_ID}`,
    `[static-demo] Loading prediction run ${RUN_ID}`,
    `[static-demo] Assembling graph evidence: ${GRAPH_ID}`,
    `[static-demo] Planning report outline`,
    `[static-demo] Writing section 1/6`,
    `[static-demo] Writing section 2/6`,
    `[static-demo] Writing section 3/6`,
    `[static-demo] Writing section 4/6`,
    `[static-demo] Writing section 5/6`,
    `[static-demo] Writing section 6/6`,
    `[static-demo] Report ${REPORT_ID}: completed`,
  ]
  const visibleCount = demoState.reportCompleted
    ? logs.length
    : Math.min(logs.length - 1, Math.max(1, Math.ceil(reportElapsedSeconds() / 3) + 1))
  return ok({
    logs: logs.slice(0, visibleCount).slice(Number(fromLine || 0)),
    from_line: Number(fromLine || 0),
    total_lines: logs.length,
    has_more: !demoState.reportCompleted,
  })
}

const conversationRecord = () => ({
  id: CONVERSATION_ID,
  report_id: REPORT_ID,
  simulation_id: RUN_ID,
  target_agent_id: null,
  target_type: 'report_agent',
  title: 'Prediction Q&A',
  created_at: '2026-06-19T14:43:33.184413+00:00',
  updated_at: '2026-06-22T09:53:20.519415+00:00',
  metadata: {
    artifact_status: 'active',
    prediction_run_id: RUN_ID,
    report_id: REPORT_ID,
    updated_at: '2026-06-22T09:53:20.519110+00:00',
    workflow_revision: 1,
  },
})

const existingStep5UserMessage = () => ({
  id: 'af140261-7bcb-43de-a54b-f319dc0d03b3',
  conversation_id: CONVERSATION_ID,
  role: 'user',
  content: '如果你是突尼斯新任主帅，如何对于战术和人员安排上做出合理的规划，打破赛前人们都不看好的颓势击败日本队？',
  created_at: '2026-06-19T14:44:24.625352+00:00',
  metadata: {},
  tool_calls: [],
  sources: [],
})

const existingStep5AssistantMessage = () => ({
  id: 'e31cd889-29da-41e3-95d6-8dcd07b2ef6b',
  conversation_id: CONVERSATION_ID,
  role: 'assistant',
  content: `根据报告，**最可能比分** 是 **0-2**。

基于报告内容，若站在突尼斯新帅勒纳尔的视角，要在不被看好的情况下击败日本，需针对报告揭示的双方薄弱环节进行针对性部署。以下是合理的战术与人员规划：

### 一、阵型选择：放弃首轮3-5-2，改打四后卫稳固防线
首轮1-5惨败瑞典时使用的3-5-2防线完全失守，报告明确指出新帅可能改用四后卫体系。面对日本犀利的快速转换与边路推进，应采用**4-3-3或4-5-1防守落位**，增加禁区前沿的保护密度。防守端需重点保持阵型距离，避免被日本反击轻易打穿。

### 二、防守端：重点保护左路，切断日本转换通道
报告关键对位分析指出，左路Ali Abdi（防守评分63.8）是薄弱环节，而日本大概率会通过堂安律或伊东纯也在此侧发起反击。必须安排中场球员对其侧应保护，限制日本边路推进。同时，首轮Skhiri后场短传失误已导致丢球，后场出球必须简化，避免在危险区域被日本前场逼抢断球。

### 三、进攻端：死磕定位球与传中，打击日本防空弱点
日本防守定位球存在明确隐患——首轮正是被荷兰范戴克头球破门。突尼斯应将定位球和传中作为最核心得分通道：
1. **主罚与抢点**：安排Hannibal主罚定位球，利用Rekik和Talbi的身高优势进行头球攻门。首轮突尼斯唯一进球正是Rekik的头球，这一战术已被验证有效。
2. **耐心制造定位球**：在运动战难以打穿日本紧凑的5-4-1低位防守时，应主动在边路寻求突破制造角球和任意球，避免与日本在中场拼控球。

### 四、体能与节奏管理：应对蒙特雷高温
比赛在34-35°C的高温下进行，这对双方都是考验。突尼斯首轮惨败后存在心理与体能双重消耗，需合理分配体能：
- **上半场稳守**：不与日本盲目对攻，降低节奏，消耗对方耐心。
- **下半场发力**：60-75分钟阶段集中通过定位球寻求破门，若能追平或领先，在75分钟后利用日本体能下降期加强逼抢。

### 五、关键不确定性提示
需注意，报告标注突尼斯首发与阵型为**低置信度**，门将人选及多个位置存在轮换可能。此外，日本虽折损久保建英，但其替补深度（如前田大然等速度型球员）在75分钟后仍具威胁，突尼斯需预留换人名额应对后段防守。`,
  created_at: '2026-06-19T14:44:39.529216+00:00',
  metadata: {
    static_demo_replay: true,
    answer_mode: 'captured_step5_qa',
  },
  tool_calls: [
    { tool_name: 'scoreline_distribution', parameters: { prediction_run_id: RUN_ID } },
    { tool_name: 'match_event_timeline', parameters: { prediction_run_id: RUN_ID } },
    { tool_name: 'prediction_config_lookup', parameters: { prediction_config_id: CONFIG_ID } },
    { tool_name: 'coach_discussion_lookup', parameters: { prediction_config_id: CONFIG_ID } },
    { tool_name: 'report_sections_lookup', parameters: { report_id: REPORT_ID } },
  ],
  sources: [
    { type: 'report_sections', report_id: REPORT_ID, count: 6 },
    { type: 'prediction_config', prediction_config_id: CONFIG_ID },
    { type: 'coach_discussions', prediction_config_id: CONFIG_ID, count: 2 },
    { type: 'prediction_result', prediction_run_id: RUN_ID },
    { type: 'match_events', count: 8 },
    { type: 'graph_evidence', graph_id: GRAPH_ID, count: 20 },
  ],
})

const conversations = () => ok({
  conversations: [conversationRecord()],
  count: 1,
})

const conversation = () => ok(conversationRecord())

const messages = () => ok({
  conversation: conversationRecord(),
  messages: [existingStep5UserMessage(), existingStep5AssistantMessage()],
  count: 2,
})

const sendMessage = () => ok({
  conversation: conversationRecord(),
  user_message: existingStep5UserMessage(),
  assistant_message: existingStep5AssistantMessage(),
  response: existingStep5AssistantMessage().content,
  tool_calls: existingStep5AssistantMessage().tool_calls,
  sources: existingStep5AssistantMessage().sources,
})

const reportRouteResponse = (pathname, method, searchParams, body) => {
  const match = pathname.match(/^\/api\/report\/([^/]+)(?:\/(.+))?$/)
  if (!match) return null

  const tail = match[2] || ''
  const isInteractionView = searchParams.get('view') === 'interaction'
  if (method === 'GET' && tail === '') return reportResponse({ forceComplete: isInteractionView })
  if (method === 'GET' && tail === 'sections') return isInteractionView ? completeReportSectionsResponse() : reportSectionsResponse()
  if (method === 'GET' && tail === 'progress') return reportProgress()
  if (method === 'GET' && tail === 'agent-log') return agentLogPayload(searchParams.get('from_line'), { forceComplete: isInteractionView })
  if (method === 'GET' && tail === 'console-log') return consoleLogPayload(searchParams.get('from_line'))
  if (method === 'GET' && tail === 'conversations') return conversations()
  if (method === 'POST' && tail === 'conversations') return conversation()
  if (method === 'GET' && tail === `conversations/${CONVERSATION_ID}/messages`) return messages()
  if (method === 'POST' && tail === `conversations/${CONVERSATION_ID}/messages`) return sendMessage()

  return null
}

const normalizeUrl = (input) => {
  const url = new URL(input, window.location.origin)
  return {
    pathname: url.pathname,
    searchParams: url.searchParams,
  }
}

const response = (body, init = {}) => new Response(JSON.stringify(body), {
  status: init.status || 200,
  headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
})

const parseBody = (rawBody) => {
  if (!rawBody || typeof rawBody !== 'string') return {}
  try {
    return JSON.parse(rawBody)
  } catch {
    return {}
  }
}

async function handleStaticApi(input, init = {}) {
  const method = (init.method || 'GET').toUpperCase()
  const { pathname, searchParams } = normalizeUrl(input)
  const body = parseBody(init.body)

  if (method === 'POST' && pathname === '/api/graph/ontology/generate') {
    demoState.graphTaskPolls = 0
    demoState.graphBuildStarted = false
    demoState.graphBuildCompleted = false
    demoState.graphRatio = 0
    demoState.step2Prepared = false
    demoState.step2Preparing = false
    demoState.step2ProgressPolls = 0
    demoState.step3Started = false
    demoState.step3Completed = false
    demoState.step3StatusPolls = 0
    resetReportGeneration()
    await delay(ONTOLOGY_DELAY_MS)
    return ontologyProjectResponse()
  }
  if (method === 'POST' && pathname === '/api/graph/build') {
    demoState.graphTaskPolls = 0
    demoState.graphBuildStarted = true
    demoState.graphBuildCompleted = false
    demoState.graphRatio = 0
    return staticGraphTask()
  }
  if (method === 'GET' && pathname.startsWith('/api/graph/task/')) return staticGraphTask()
  if (method === 'GET' && pathname === `/api/tasks/by-project/${PROJECT_ID}/snapshot`) return endpointBody('taskSnapshot')
  if (method === 'GET' && pathname === `/api/graph/project/${PROJECT_ID}`) return projectResponse()
  if (method === 'GET' && pathname === `/api/graph/data/${GRAPH_ID}`) return ok(graphDataForCurrentBuild())
  if (method === 'GET' && pathname === `/api/projects/${PROJECT_ID}/workflow`) return workflowResponse()
  if (method === 'POST' && pathname.match(/^\/api\/projects\/.+\/steps\/\d+\/regenerate$/)) return workflowResponse()

  if (method === 'GET' && pathname === `/api/prediction/${PROJECT_ID}/configs/latest`) {
    return demoState.step2Prepared
      ? patchConfig(endpointBody('latestPredictionConfig'))
      : noLatestConfigResponse()
  }
  if (method === 'POST' && pathname === `/api/prediction/${PROJECT_ID}/prepare`) {
    demoState.step2Prepared = false
    demoState.step2Preparing = true
    demoState.step2ProgressPolls = 0
    return ok({
      prediction_config_id: CONFIG_ID,
      project_id: PROJECT_ID,
      graph_id: GRAPH_ID,
      status: 'preparing',
      current_phase: 'initializing',
      progress_percent: 1,
      already_prepared: false,
    })
  }
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}`) {
    return demoState.step2Prepared
      ? patchConfig(endpointBody('predictionConfig'))
      : step2PreparingConfig()
  }
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/status`) {
    return demoState.step2Prepared
      ? ok(patchConfig(endpointBody('latestPredictionConfig')).data)
      : step2PreparingConfig()
  }
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/progress`) return step2ProgressResponse()
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/roster`) return patchRoster(endpointBody('predictionConfigRoster'))
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/coach-agents`) return demoState.step2Prepared ? endpointBody('predictionCoachAgents') : step2EmptyArtifact('agents')
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/coach-discussions`) return demoState.step2Prepared ? endpointBody('predictionCoachDiscussions') : step2EmptyArtifact('discussions')
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/scenario-design`) return demoState.step2Prepared ? endpointBody('predictionScenarioDesign') : step2EmptyArtifact('scenarios')
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/resume-policy`) return demoState.step2Prepared ? endpointBody('predictionResumePolicy') : step2EmptyArtifact('resume')
  if (method === 'GET' && pathname === `/api/prediction/configs/${CONFIG_ID}/team-strengths`) return demoState.step2Prepared ? patchTeamStrengths(endpointBody('predictionConfigTeamStrengths')) : step2EmptyArtifact('strengths')
  if (method === 'GET' && pathname === '/api/prediction/datasets') return datasets()
  if (method === 'PATCH' && pathname === `/api/prediction/configs/${CONFIG_ID}/dataset`) {
    demoState.step2Prepared = false
    demoState.step2Preparing = true
    demoState.step2ProgressPolls = 0
    demoState.step3Started = false
    demoState.step3Completed = false
    demoState.step3StatusPolls = 0
    resetReportGeneration()
    return ok({
      prediction_config_id: CONFIG_ID,
      project_id: PROJECT_ID,
      graph_id: GRAPH_ID,
      status: 'preparing',
      current_phase: 'dataset_switch_requested',
      progress_percent: 0,
    })
  }

  if (method === 'POST' && pathname === `/api/prediction/${PROJECT_ID}/run`) {
    demoState.step3Started = true
    demoState.step3Completed = false
    demoState.step3StatusPolls = 0
    resetReportGeneration()
    return predictionRunResponse()
  }
  if (method === 'POST' && pathname === `/api/prediction/${RUN_ID}/resume`) {
    demoState.step3Started = true
    demoState.step3Completed = false
    demoState.step3StatusPolls = 0
    resetReportGeneration()
    return predictionRunResponse()
  }
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/status`) return predictionRunResponse({ advance: demoState.step3Started && !demoState.step3Completed })
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/roster`) return patchRoster(endpointBody('predictionRunRoster'))
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/budget-usage`) return endpointBody('predictionBudgetUsage')
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/scenario-cases`) return endpointBody('predictionScenarioCases')
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/scenario-spaces`) return endpointBody('predictionScenarioSpaces')
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/team-strengths`) return patchTeamStrengths(endpointBody('predictionTeamStrengths'))
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/scorelines`) return endpointBody('predictionScorelines')
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/match-events`) return endpointBody('predictionMatchEvents')
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/analyst-notes`) return endpointBody('predictionAnalystNotes')
  if (method === 'GET' && pathname === `/api/prediction/${RUN_ID}/result`) return endpointBody('predictionResult')
  if (method === 'GET' && pathname === '/api/prediction/history') return history()
  if (method === 'POST' && pathname === `/api/prediction/${RUN_ID}/report`) {
    demoState.step3Started = true
    demoState.step3Completed = true
    startReportGeneration()
    return reportResponse()
  }

  if (method === 'POST' && pathname === '/api/report/generate') {
    startReportGeneration()
    return reportResponse()
  }

  const reportStaticResponse = reportRouteResponse(pathname, method, searchParams, body)
  if (reportStaticResponse) return reportStaticResponse

  return { success: false, error: `Static demo API route not captured: ${method} ${pathname}` }
}

export function installStaticApiMock() {
  const originalFetch = window.fetch.bind(window)
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url
    if (new URL(url, window.location.origin).pathname.startsWith('/api/')) {
      return response(await handleStaticApi(url, init))
    }
    return originalFetch(input, init)
  }

  const NativeXMLHttpRequest = window.XMLHttpRequest

  class StaticDemoXMLHttpRequest extends EventTarget {
    static UNSENT = 0
    static OPENED = 1
    static HEADERS_RECEIVED = 2
    static LOADING = 3
    static DONE = 4

    UNSENT = 0
    OPENED = 1
    HEADERS_RECEIVED = 2
    LOADING = 3
    DONE = 4

    readyState = 0
    status = 0
    statusText = ''
    response = null
    responseText = ''
    responseType = ''
    responseURL = ''
    timeout = 0
    withCredentials = false
    upload = new EventTarget()

    onabort = null
    onerror = null
    onload = null
    onloadend = null
    onloadstart = null
    onprogress = null
    onreadystatechange = null
    ontimeout = null

    #method = 'GET'
    #url = ''
    #async = true
    #requestHeaders = {}
    #responseHeaders = { 'content-type': 'application/json' }
    #native = null
    #aborted = false

    open(method, url, async = true, user, password) {
      const parsed = new URL(url, window.location.origin)
      if (!parsed.pathname.startsWith('/api/')) {
        this.#native = new NativeXMLHttpRequest()
        this.#mirrorNativeEvents()
        this.#native.open(method, url, async, user, password)
        return
      }

      this.#method = String(method || 'GET').toUpperCase()
      this.#url = url
      this.#async = async !== false
      this.responseURL = parsed.href
      this.#setReadyState(this.OPENED)
    }

    setRequestHeader(name, value) {
      if (this.#native) {
        this.#native.setRequestHeader(name, value)
        return
      }
      this.#requestHeaders[String(name).toLowerCase()] = String(value)
    }

    getAllResponseHeaders() {
      if (this.#native) return this.#native.getAllResponseHeaders()
      if (this.readyState < this.HEADERS_RECEIVED) return ''
      return Object.entries(this.#responseHeaders)
        .map(([name, value]) => `${name}: ${value}`)
        .join('\r\n')
    }

    getResponseHeader(name) {
      if (this.#native) return this.#native.getResponseHeader(name)
      if (this.readyState < this.HEADERS_RECEIVED) return null
      return this.#responseHeaders[String(name).toLowerCase()] || null
    }

    overrideMimeType(mimeType) {
      if (this.#native) {
        this.#native.overrideMimeType(mimeType)
      }
    }

    abort() {
      if (this.#native) {
        this.#native.abort()
        return
      }
      this.#aborted = true
      this.status = 0
      this.statusText = ''
      this.#dispatch('abort')
      this.#dispatch('loadend')
    }

    async send(body = null) {
      if (this.#native) {
        this.#native.timeout = this.timeout
        this.#native.withCredentials = this.withCredentials
        if (this.responseType) this.#native.responseType = this.responseType
        this.#native.send(body)
        return
      }

      if (this.readyState !== this.OPENED) {
        throw new DOMException('XMLHttpRequest has not been opened.', 'InvalidStateError')
      }

      this.#dispatch('loadstart')

      const execute = async () => {
        if (this.#aborted) return
        try {
          const payload = await handleStaticApi(this.#url, {
            method: this.#method,
            body: typeof body === 'string' ? body : null,
            headers: this.#requestHeaders,
          })
          const serialized = JSON.stringify(payload)
          this.status = 200
          this.statusText = 'OK'
          this.responseText = serialized
          this.response = this.responseType && this.responseType !== 'text'
            ? payload
            : serialized
          this.#setReadyState(this.HEADERS_RECEIVED)
          this.#setReadyState(this.LOADING)
          this.#setReadyState(this.DONE)
          this.#dispatch('load')
          this.#dispatch('loadend')
        } catch (error) {
          this.status = 500
          this.statusText = 'Static Demo Mock Error'
          this.responseText = JSON.stringify({
            success: false,
            error: error?.message || 'Static demo mock failed',
          })
          this.response = this.responseText
          this.#setReadyState(this.DONE)
          this.#dispatch('error')
          this.#dispatch('loadend')
        }
      }

      if (this.#async) {
        window.setTimeout(execute, 0)
      } else {
        await execute()
      }
    }

    #setReadyState(value) {
      this.readyState = value
      this.#dispatch('readystatechange')
    }

    #dispatch(type) {
      const event = new Event(type)
      this.dispatchEvent(event)
      const handler = this[`on${type}`]
      if (typeof handler === 'function') {
        handler.call(this, event)
      }
    }

    #mirrorNativeEvents() {
      const events = ['abort', 'error', 'load', 'loadend', 'loadstart', 'progress', 'readystatechange', 'timeout']
      events.forEach((type) => {
        this.#native.addEventListener(type, (event) => {
          this.readyState = this.#native.readyState
          this.status = this.#native.status
          this.statusText = this.#native.statusText
          this.response = this.#native.response
          this.responseText = this.#native.responseText
          this.responseURL = this.#native.responseURL
          this.dispatchEvent(event)
          const handler = this[`on${type}`]
          if (typeof handler === 'function') {
            handler.call(this, event)
          }
        })
      })
    }
  }

  window.XMLHttpRequest = StaticDemoXMLHttpRequest
}
