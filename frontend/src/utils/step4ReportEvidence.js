const asObject = value => (value && typeof value === 'object' && !Array.isArray(value) ? value : {})
const asArray = value => (Array.isArray(value) ? value.filter(Boolean) : [])
const arrayLength = value => (Array.isArray(value) ? value.length : null)

const numberValue = value => {
  const normalized = typeof value === 'string' ? value.replace('%', '').trim() : value
  const num = Number(normalized)
  return Number.isFinite(num) ? num : null
}

const textValue = value => {
  const text = String(value ?? '').trim()
  return text || ''
}

const firstText = (...values) => {
  for (const value of values) {
    const text = textValue(value)
    if (text) return text
  }
  return ''
}

export const resolveReportProjectId = reportSnapshot => {
  const snapshot = asObject(reportSnapshot)
  const metadata = asObject(snapshot.report_metadata)
  const evidence = asObject(metadata.evidence_package)
  const match = asObject(evidence.match)
  const step1 = asObject(evidence.step1)
  const project = asObject(step1.project)
  return firstText(
    snapshot.project_id,
    metadata.project_id,
    match.project_id,
    project.project_id,
    evidence.project_id
  )
}

const formatInteger = value => {
  const num = numberValue(value)
  return num === null ? '-' : Math.round(num).toLocaleString('en-US')
}

const formatMetric = value => {
  const num = numberValue(value)
  if (num === null) return firstText(value, '-')
  if (Math.abs(num) >= 100) return Math.round(num).toLocaleString('en-US')
  return Number.isInteger(num) ? String(num) : num.toFixed(1)
}

const probabilityPercent = value => {
  const num = numberValue(value)
  if (num === null) return null
  const pct = num <= 1 ? num * 100 : num
  return Math.max(0, Math.min(100, pct))
}

const formatProbability = value => {
  const pct = probabilityPercent(value)
  if (pct === null) return '-'
  return `${pct.toFixed(1)}%`
}

const probabilityBar = value => {
  const pct = probabilityPercent(value)
  if (pct === null) {
    return {
      pct: 0,
      percentLabel: '-',
      bar: '░░░░░░░░░░',
      isKnown: false,
    }
  }
  const filled = Math.max(0, Math.min(10, Math.round(pct / 10)))
  return {
    pct,
    percentLabel: `${pct.toFixed(1)}%`,
    bar: `${'█'.repeat(filled)}${'░'.repeat(10 - filled)}`,
    isKnown: true,
  }
}

const formatWeight = value => {
  const pct = probabilityPercent(value)
  if (pct !== null) return `${pct.toFixed(pct >= 10 ? 0 : 1)}%`
  return firstText(value, '-')
}

const normalizeScore = value => String(value || '').trim().replace(/\s+/g, '')

const extractScoreFromSections = generatedSections => {
  const content = Object.values(asObject(generatedSections)).join('\n')
  const scoreMatch = content.match(/最可能比分[:：]\s*([0-9]+\s*[-:]\s*[0-9]+)/)
  const homeMatch = content.match(/主胜概率[:：]\s*([0-9.]+%?)/)
  const drawMatch = content.match(/平局概率[:：]\s*([0-9.]+%?)/)
  const awayMatch = content.match(/客胜概率[:：]\s*([0-9.]+%?)/)
  return {
    most_likely_score: scoreMatch ? normalizeScore(scoreMatch[1]).replace(':', '-') : '',
    win_draw_loss_probability: {
      home_win: homeMatch?.[1],
      draw: drawMatch?.[1],
      away_win: awayMatch?.[1],
    },
  }
}

const scoreParts = score => {
  const match = normalizeScore(score).match(/^(\d+)[-:](\d+)$/)
  return match ? [match[1], match[2]] : null
}

const reportContext = evidence => ({
  match: asObject(evidence.match),
  step1: asObject(evidence.step1),
  step2: asObject(evidence.step2),
  step3: asObject(evidence.step3),
  credibility: asObject(evidence.credibility),
})

const predictionConfig = evidence => {
  const context = reportContext(evidence)
  return {
    ...context.match,
    ...asObject(context.step2.prediction_config),
    ...asObject(evidence.prediction_config),
  }
}

const scorelineSummary = evidence => {
  const context = reportContext(evidence)
  return asObject(evidence.scoreline_summary ?? context.step3.scoreline_summary)
}

const scorelines = evidence => {
  const context = reportContext(evidence)
  return asArray(evidence.scorelines ?? context.step3.scorelines)
}

const topScores = evidence => {
  const context = reportContext(evidence)
  const summary = scorelineSummary(evidence)
  return asArray(
    evidence.top_scores
      ?? evidence.top_score_candidates
      ?? summary.top_scores
      ?? summary.top_score_candidates
      ?? context.step3.top_scores
  )
}

const events = evidence => {
  const context = reportContext(evidence)
  return asArray(evidence.match_events ?? evidence.events ?? context.step3.events)
}

const timelineBuckets = evidence => {
  const context = reportContext(evidence)
  return asArray(evidence.event_timeline ?? context.step3.event_timeline)
}

const scenarioSpaces = evidence => {
  const context = reportContext(evidence)
  return asArray(evidence.scenario_spaces ?? context.step3.scenario_spaces)
}

const scenarioCases = evidence => {
  const context = reportContext(evidence)
  return asArray(evidence.scenario_cases ?? context.step3.scenario_cases ?? context.step2.scenario_design)
}

const budgetCredibility = evidence => {
  const context = reportContext(evidence)
  return asObject(evidence.budget_credibility ?? context.credibility.budget)
}

const normalizeWidgets = ({ metadata, evidence }) => {
  const source = asObject(metadata.widgets ?? evidence.widgets)
  return {
    lineup: asObject(source.lineup_widget),
    tactics: asObject(source.tactics_widget),
    matchups: asArray(source.matchup_widget),
  }
}

const credibilityWarnings = evidence => {
  const context = reportContext(evidence)
  const budget = budgetCredibility(evidence)
  const step2Warnings = asArray(context.step2.budget_or_degradation?.warnings)
  return [
    ...asArray(evidence.warnings),
    ...asArray(context.credibility.warnings),
    ...asArray(budget.warnings),
    ...step2Warnings,
  ]
}

const teamName = (evidence, role) => {
  const config = predictionConfig(evidence)
  if (role === 'home') return config.home_team || '主队'
  if (role === 'away') return config.away_team || '客队'
  return ''
}

const buildVerdict = ({ evidence, generatedSections }) => {
  const config = predictionConfig(evidence)
  const scoreSummary = scorelineSummary(evidence)
  const fallbackScore = extractScoreFromSections(generatedSections)
  const mostLikely = scoreSummary.most_likely_score || fallbackScore.most_likely_score || ''
  const probabilities = asObject(scoreSummary.win_draw_loss_probability)
  const fallbackProbabilities = asObject(fallbackScore.win_draw_loss_probability)
  const homeTeam = config.home_team || '主队'
  const awayTeam = config.away_team || '客队'
  const parts = scoreParts(mostLikely)
  const title = parts ? `${homeTeam} ${parts[0]}-${parts[1]} ${awayTeam}` : (config.match_name || '比赛结论待生成')

  return {
    eyebrow: config.match_name || `${homeTeam} vs ${awayTeam}`,
    title,
    subtitle: [
      `主胜 ${formatProbability(probabilities.home_win ?? fallbackProbabilities.home_win)}`,
      `平 ${formatProbability(probabilities.draw ?? fallbackProbabilities.draw)}`,
      `客胜 ${formatProbability(probabilities.away_win ?? fallbackProbabilities.away_win)}`,
    ].join(' · '),
  }
}

const externalSourcesCount = sources => {
  if (Array.isArray(sources)) return sources.filter(Boolean).length
  return Object.values(asObject(sources)).filter(Boolean).length
}

const availabilityLabel = availability => {
  const home = asObject(availability.home)
  const away = asObject(availability.away)
  const homeLabel = `${formatInteger(home.available)}/${formatInteger(home.total)}`
  const awayLabel = `${formatInteger(away.available)}/${formatInteger(away.total)}`
  if (home.available == null && home.total == null && away.available == null && away.total == null) return '-'
  return `主 ${homeLabel} · 客 ${awayLabel}`
}

const buildModelInputs = evidence => {
  const context = reportContext(evidence)
  const config = predictionConfig(evidence)
  const budget = budgetCredibility(evidence)
  const dataset = asObject(budget.player_dataset)
  const sourceCount = externalSourcesCount(budget.external_sources ?? context.step1.external_sources)
  const modelLabel = [config.model_name, config.model_version].filter(Boolean).join(' ') || '-'
  const datasetLabel = dataset.players_count
    ? `${formatInteger(dataset.teams_count)}队 / ${formatInteger(dataset.players_count)}人`
    : (dataset.dataset_id || '-')

  return [
    { label: '模型', value: modelLabel },
    { label: '球员可用', value: availabilityLabel(asObject(budget.player_availability ?? context.step2.player_availability)) },
    { label: '数据集', value: datasetLabel },
    { label: '数据状态', value: `${config.fit_status || '-'} / ${config.data_sufficiency || '-'}` },
    { label: '外部源', value: sourceCount ? `${sourceCount} 组` : '-' },
  ]
}

const buildEvidenceStats = ({ evidence, predictionStatus }) => {
  const context = reportContext(evidence)
  const counts = asObject(predictionStatus?.counts)
  return [
    { label: '比分候选', value: formatInteger(evidence.scorelines_count ?? arrayLength(context.step3.scorelines)) },
    { label: '比赛事件', value: formatInteger(evidence.match_events_count ?? arrayLength(context.step3.events) ?? counts.match_events) },
    { label: '九场景', value: formatInteger(counts.scenario_cases ?? evidence.scenario_cases_count ?? arrayLength(context.step3.scenario_cases) ?? 9) },
    { label: '分析笔记', value: formatInteger(evidence.analyst_notes_count ?? arrayLength(context.step3.analyst_notes)) },
    { label: '教练讨论', value: formatInteger(evidence.coach_discussions_count ?? arrayLength(context.step2.coach_discussions)) },
  ]
}

const buildCredibilityItems = evidence => {
  const budget = budgetCredibility(evidence)
  const ledger = asObject(budget.ledger)
  const profile = asObject(budget.budget_profile)
  const totalCalls = formatInteger(ledger.total_calls)
  const hardCap = formatInteger(ledger.hard_cap ?? profile.hard_cap_calls)
  const cached = formatInteger(ledger.cached)
  const failuresValue = ledger.failures_count ?? (Array.isArray(ledger.failures) ? ledger.failures.length : null)
  const failures = formatInteger(failuresValue)

  return [
    {
      label: 'LLM 调用',
      detail: `${totalCalls}/${hardCap} · cached ${cached}`,
      tone: numberValue(ledger.total_calls) > numberValue(ledger.hard_cap ?? profile.hard_cap_calls) ? 'warn' : 'normal',
    },
    {
      label: '降级记录',
      detail: failures === '-' ? '未记录' : `${failures} 条`,
      tone: numberValue(failuresValue) ? 'warn' : 'normal',
    },
    {
      label: '预算档位',
      detail: profile.profile_key || '-',
      tone: 'normal',
    },
  ]
}

const roleStrengths = evidence => {
  const context = reportContext(evidence)
  const rows = asArray(evidence.team_strengths ?? context.step2.team_strengths)
  const result = {}
  rows.forEach((row, index) => {
    const item = asObject(row)
    const role = item.team_role || (index === 0 ? 'home' : index === 1 ? 'away' : '')
    if (role === 'home' || role === 'away') result[role] = item
  })
  return result
}

const roleAvailability = (evidence, role) => {
  const context = reportContext(evidence)
  const budget = budgetCredibility(evidence)
  return asObject(asObject(budget.player_availability ?? context.step2.player_availability)[role])
}

const roleAvailabilityLabel = (evidence, role) => {
  const row = roleAvailability(evidence, role)
  if (row.available == null && row.total == null) return '-'
  return `${formatInteger(row.available)}/${formatInteger(row.total)}`
}

const rankingText = row => {
  const ranking = asObject(row)
  const fifa = ranking.fifa_rank ? `FIFA ${formatInteger(ranking.fifa_rank)}` : ''
  const points = ranking.fifa_points ? `${formatMetric(ranking.fifa_points)}分` : ''
  const elo = ranking.elo_rank ? `Elo ${formatInteger(ranking.elo_rank)}` : ''
  return [fifa, points, elo].filter(Boolean).join(' · ') || '-'
}

const xgValue = value => {
  const num = numberValue(value)
  return num === null ? '-' : num.toFixed(2)
}

const buildProbabilityBars = ({ evidence, generatedSections }) => {
  const summary = scorelineSummary(evidence)
  const fallbackScore = extractScoreFromSections(generatedSections)
  const probabilities = asObject(summary.win_draw_loss_probability)
  const fallbackProbabilities = asObject(fallbackScore.win_draw_loss_probability)
  const home = teamName(evidence, 'home')
  const away = teamName(evidence, 'away')
  const rows = [
    {
      key: 'home_win',
      label: '主胜',
      team: home,
      detail: `${home} 赢球的模型概率。`,
      value: probabilities.home_win ?? fallbackProbabilities.home_win,
    },
    {
      key: 'draw',
      label: '平局',
      team: '平局',
      detail: '两队打平的模型概率，平局越高越需要防小比分。',
      value: probabilities.draw ?? fallbackProbabilities.draw,
    },
    {
      key: 'away_win',
      label: '客胜',
      team: away,
      detail: `${away} 赢球的模型概率。`,
      value: probabilities.away_win ?? fallbackProbabilities.away_win,
    },
  ]
  return rows.map(row => ({
    ...row,
    ...probabilityBar(row.value),
  }))
}

const buildTeamComparison = evidence => {
  const context = reportContext(evidence)
  const strengths = roleStrengths(evidence)
  const rankings = asObject(context.step2.team_rankings)
  const formations = asObject(context.step2.formations)
  const xg = asObject(context.step3.xg)
  return ['home', 'away'].map(role => {
    const row = asObject(strengths[role])
    return {
      key: role,
      team: firstText(row.team_name, teamName(evidence, role)),
      formation: firstText(formations[role], '-'),
      ranking: rankingText(rankings[role]),
      attack: formatMetric(row.attack_rating),
      defense: formatMetric(row.defense_rating),
      transition: formatMetric(row.transition_rating),
      goalkeeper: formatMetric(row.goalkeeper_rating),
      xg: xgValue(xg[role]),
      availability: roleAvailabilityLabel(evidence, role),
      confidence: row.confidence == null ? '-' : formatProbability(row.confidence),
    }
  })
}

const scoreCandidateFromItem = (item, index) => {
  const row = asObject(item)
  const score = firstText(row.score, row.scoreline, row.most_likely_score)
  if (!score) return null
  const value = row.probability ?? row.probability_pct ?? row.prob
  return {
    key: `score-${index}-${score}`,
    rank: index + 1,
    score,
    probability: formatProbability(value),
    bar: probabilityBar(value).bar,
    pct: probabilityBar(value).pct,
    context: firstText(row.scenario, row.scenario_label, row.scenario_space, row.space, 'Top 候选比分'),
  }
}

const buildScoreCandidates = evidence => {
  const direct = topScores(evidence)
    .map(scoreCandidateFromItem)
    .filter(Boolean)
    .slice(0, 5)
  if (direct.length) return direct

  const seen = new Set()
  return scorelines(evidence)
    .map((row, index) => {
      const item = asObject(row)
      const score = firstText(item.score, item.scoreline, item.most_likely_score)
      if (!score || seen.has(score)) return null
      seen.add(score)
      return {
        key: `scenario-score-${index}-${score}`,
        rank: seen.size,
        score,
        probability: '-',
        bar: '░░░░░░░░░░',
        pct: 0,
        context: firstText(item.scenario_label, item.scenario_space, item.xg ? `xG ${item.xg}` : '场景候选'),
      }
    })
    .filter(Boolean)
    .slice(0, 5)
}

const strongestPlayerTag = player => {
  const row = asObject(player)
  const metrics = [
    ['进攻', row.attack],
    ['防守', row.defense],
    ['射门', row.finishing],
    ['传球', row.passing],
    ['总评', row.overall],
  ]
    .map(([label, value]) => ({ label, value: numberValue(value) }))
    .filter(item => item.value !== null)
    .sort((a, b) => b.value - a.value)
  return metrics[0] ? `${metrics[0].label} ${formatMetric(metrics[0].value)}` : '-'
}

const buildKeyPlayers = evidence => {
  const context = reportContext(evidence)
  const attrs = asObject(context.step2.player_attributes)
  const lineups = asObject(context.step2.lineups)
  const result = []
  for (const role of ['home', 'away']) {
    const players = asArray(attrs[role]).length ? asArray(attrs[role]) : asArray(lineups[role])
    players.slice(0, 4).forEach((player, index) => {
      const row = asObject(player)
      result.push({
        key: `${role}-${index}-${row.name || row.position || 'player'}`,
        team: teamName(evidence, role),
        name: firstText(row.name, row.full_name, row.name_en, '-'),
        position: firstText(row.position, row.position_primary, row.position_class, '-'),
        overall: formatMetric(row.overall),
        tag: strongestPlayerTag(row),
        availability: firstText(row.availability, row.status, '-'),
      })
    })
  }
  return result.slice(0, 8)
}

const buildCoachNotes = evidence => {
  const context = reportContext(evidence)
  return asArray(context.step2.coach_discussions)
    .map((item, index) => {
      const row = asObject(item)
      return {
        key: `coach-${index}`,
        topic: firstText(row.topic, '教练讨论'),
        summary: firstText(row.summary, '资料未明确'),
        consensus: row.consensus_score == null ? '-' : formatMetric(row.consensus_score),
      }
    })
    .filter(item => item.summary !== '资料未明确')
    .slice(0, 3)
}

const buildScenarioHighlights = evidence => {
  const spaces = scenarioSpaces(evidence)
  const source = spaces.length ? spaces : scenarioCases(evidence)
  return source
    .map((item, index) => {
      const row = asObject(item)
      const drivers = asArray(row.key_drivers ?? row.drivers ?? row.risk_factors)
        .map(value => String(value).trim())
        .filter(Boolean)
      return {
        key: `scenario-${index}`,
        name: firstText(row.space_name, row.scenario, row.scenario_name, row.scenario_space, row.space, '场景'),
        weight: formatWeight(row.weight ?? row.final_weight ?? row.probability),
        summary: firstText(row.summary, drivers.slice(0, 2).join('；'), row.xg ? `xG ${row.xg}` : '资料未明确'),
      }
    })
    .slice(0, 5)
}

const eventLabel = type => {
  const labels = {
    GOAL: '进球',
    CHANCE_CREATED: '机会',
    SHOT: '射门',
    SAVE: '扑救',
    YELLOW_CARD: '黄牌',
    RED_CARD: '红牌',
    VAR_CHECK: 'VAR',
    SUBSTITUTION: '换人',
    PRESSURE_SHIFT: '节奏变化',
    FINAL_SCORE_HYPOTHESIS: '比分假设',
  }
  return labels[type] || firstText(type, '事件')
}

const buildEventTimeline = evidence => {
  const buckets = timelineBuckets(evidence)
  if (buckets.length) {
    return buckets.slice(0, 4).map((item, index) => {
      const row = asObject(item)
      return {
        key: `timeline-${index}`,
        period: firstText(row.period, '-'),
        trigger: firstText(row.trigger, '资料未明确'),
        event: firstText(row.event, row.description, '资料未明确'),
        scoreImpact: firstText(row.score_impact, row.score, '可能改变节奏'),
      }
    })
  }

  const allEvents = events(evidence)
  const ranges = [
    ['0-30', 0, 30],
    ['31-60', 31, 60],
    ['61-75', 61, 75],
    ['76-90+', 76, 130],
  ]
  return ranges.map(([period, start, end], index) => {
    const selected = allEvents.find(item => {
      const minute = numberValue(asObject(item).minute)
      return minute !== null && minute >= start && minute <= end
    })
    const row = asObject(selected)
    return {
      key: `timeline-${index}`,
      period,
      trigger: selected ? `${eventLabel(row.event_type)} 出现` : '资料未明确',
      event: firstText(row.description, selected ? eventLabel(row.event_type) : '资料未明确'),
      scoreImpact: firstText(row.score, '可能改变节奏'),
    }
  })
}

const buildEventItems = evidence => events(evidence)
  .slice(0, 6)
  .map((item, index) => {
    const row = asObject(item)
    return {
      key: `event-${index}`,
      minute: row.minute == null ? '-' : `${row.minute}'`,
      label: firstText(row.event_label, eventLabel(row.event_type)),
      team: firstText(row.team, '-'),
      score: firstText(row.score, '-'),
      description: firstText(row.description, '资料未明确'),
    }
  })

const textCorpus = evidence => {
  const context = reportContext(evidence)
  const parts = [
    ...asArray(context.step1.key_narratives),
    ...asArray(context.step1.tactical_notes).map(item => asObject(item).note || item),
    ...asArray(context.step3.uncertainty_factors),
  ]
  return parts.map(item => String(item)).join(' ')
}

const buildRiskItems = evidence => {
  const context = reportContext(evidence)
  const injuryCount = asArray(context.step1.injury_reports).length
  const allEvents = events(evidence)
  const warnings = credibilityWarnings(evidence)
  const corpus = textCorpus(evidence)
  const lineups = asObject(context.step2.lineups)
  const uncertainty = asArray(context.step3.uncertainty_factors)
  const cardEvents = allEvents.filter(item => /CARD|VAR/.test(String(asObject(item).event_type || '')))
  const lineupCount = asArray(lineups.home).length + asArray(lineups.away).length
  return [
    {
      key: 'injury',
      label: '伤停',
      signal: injuryCount ? `${injuryCount} 条伤停线索` : '未见明确伤停',
      impact: '主力缺席会让比分向对手或平局移动',
      tone: injuryCount ? 'warn' : 'normal',
    },
    {
      key: 'weather',
      label: '天气',
      signal: /天气|大雨|小雨|雨|风|高温|湿度/.test(corpus) ? '材料提到天气因素' : '资料未明确',
      impact: '坏天气通常压低节奏和总进球',
      tone: /天气|大雨|小雨|雨|风|高温|湿度/.test(corpus) ? 'warn' : 'normal',
    },
    {
      key: 'cards',
      label: '红黄牌/VAR',
      signal: cardEvents.length ? `${cardEvents.length} 个牌/VAR相关事件` : '事件链未突出',
      impact: '红牌或点球会快速改变胜平负方向',
      tone: cardEvents.length ? 'warn' : 'normal',
    },
    {
      key: 'fitness',
      label: '体能',
      signal: /体能|疲劳|轮换|换人/.test(corpus) ? '材料提到体能/轮换' : '主要看 60 分钟后',
      impact: '体能下降会提高末段丢球概率',
      tone: /体能|疲劳|轮换|换人/.test(corpus) ? 'warn' : 'normal',
    },
    {
      key: 'lineup',
      label: '首发变动',
      signal: lineupCount >= 22 ? '两队预计首发已记录' : '首发资料不完整',
      impact: '关键位置变动会影响阵型和对位',
      tone: lineupCount >= 22 ? 'normal' : 'warn',
    },
    {
      key: 'data_gap',
      label: '数据缺口',
      signal: warnings.length ? `${warnings.length} 条警告/降级记录` : (uncertainty.length ? `${uncertainty.length} 条不确定因素` : '未见明显缺口'),
      impact: '数据缺口越多，最高概率越不能当确定结果',
      tone: warnings.length || uncertainty.length ? 'warn' : 'normal',
    },
  ]
}

const buildSourceHighlights = evidence => {
  const context = reportContext(evidence)
  const budget = budgetCredibility(evidence)
  const dataset = asObject(budget.player_dataset)
  const counts = asObject(context.credibility.data_counts)
  const sourceCount = externalSourcesCount(budget.external_sources ?? context.step1.external_sources)
  return [
    {
      label: '图谱',
      value: `${formatInteger(context.step1.graph_entities_count ?? counts.step1_graph_entities)} 实体 · ${formatInteger(context.step1.graph_relationships_count ?? counts.step1_graph_relationships)} 关系`,
      detail: 'Step1',
    },
    {
      label: '阵容',
      value: `${formatInteger(counts.step2_lineup_players)} 名球员`,
      detail: 'Step2',
    },
    {
      label: '推演',
      value: `${formatInteger(counts.step3_scorelines ?? scorelines(evidence).length)} 比分 · ${formatInteger(counts.step3_match_events ?? events(evidence).length)} 事件`,
      detail: 'Step3',
    },
    {
      label: '来源',
      value: sourceCount ? `${sourceCount} 组外部源` : '资料未明确',
      detail: dataset.players_count ? `${formatInteger(dataset.players_count)} 球员` : '数据集',
    },
  ]
}

const sectionHint = title => {
  if (/结论|摘要/.test(title)) return '比赛判断、比分倾向和核心理由'
  if (/基本面|图谱|证据/.test(title)) return '球队资料、伤停、交锋和证据来源'
  if (/战术|阵型|首发/.test(title)) return '教练讨论、预计首发和攻防 matchup'
  if (/胜平负|比分/.test(title)) return '比分概率、xG 与最可能赛果'
  if (/九场景|矩阵/.test(title)) return '场景权重、比赛画面和状态组合'
  if (/进程|事件/.test(title)) return '基准事件链和关键节点'
  if (/教练|笔记/.test(title)) return '复核意见、风险和战术解释'
  if (/裁判|不确定|风险/.test(title)) return 'VAR、红黄牌、伤退和换人风险'
  if (/预算|可信度/.test(title)) return '数据源、调用预算和降级链路'
  return '报告证据整理'
}

const buildSectionSteps = ({ reportOutline, workflowSteps }) => {
  const steps = Array.isArray(workflowSteps) && workflowSteps.length
    ? workflowSteps.filter(step => step.key !== 'planning' && step.key !== 'complete')
    : (reportOutline?.sections || []).map((section, index) => ({
        key: `section-${index + 1}`,
        noLabel: String(index + 1).padStart(2, '0'),
        title: section.title,
        status: 'todo',
      }))

  return steps.map(step => ({
    ...step,
    hint: sectionHint(step.title || ''),
  }))
}

const widgetPlayerCount = widgets => {
  const lineup = asObject(widgets?.lineup)
  return asArray(asObject(lineup.home).players).length + asArray(asObject(lineup.away).players).length
}

const buildInsightTabs = panel => [
  { key: 'overview', label: '概览', meta: `${panel.sourceHighlights.length}项` },
  { key: 'scores', label: '比分', meta: `${panel.scoreCandidates.length || panel.probabilityBars.length}项` },
  { key: 'lineups', label: '阵容', meta: `${widgetPlayerCount(panel.widgets) || panel.keyPlayers.length}人` },
  { key: 'events', label: '事件', meta: `${panel.eventTimeline.length}段` },
  { key: 'risks', label: '风险', meta: `${panel.riskItems.filter(item => item.tone === 'warn').length}警告` },
]

export const buildStep4ReportEvidence = ({
  reportSnapshot = null,
  predictionStatus = null,
  reportOutline = null,
  generatedSections = {},
  workflowSteps = [],
  statusText = '',
} = {}) => {
  const metadata = asObject(reportSnapshot?.report_metadata)
  const evidence = asObject(metadata.evidence_package)
  const widgets = normalizeWidgets({ metadata, evidence })
  const panel = {
    statusText,
    widgets,
    verdict: buildVerdict({ evidence, generatedSections }),
    modelInputs: buildModelInputs(evidence),
    evidenceStats: buildEvidenceStats({ evidence, predictionStatus }),
    credibilityItems: buildCredibilityItems(evidence),
    probabilityBars: buildProbabilityBars({ evidence, generatedSections }),
    teamComparison: buildTeamComparison(evidence),
    scoreCandidates: buildScoreCandidates(evidence),
    keyPlayers: buildKeyPlayers(evidence),
    coachNotes: buildCoachNotes(evidence),
    scenarioHighlights: buildScenarioHighlights(evidence),
    eventTimeline: buildEventTimeline(evidence),
    eventItems: buildEventItems(evidence),
    riskItems: buildRiskItems(evidence),
    sourceHighlights: buildSourceHighlights(evidence),
    sectionSteps: buildSectionSteps({ reportOutline, workflowSteps }),
  }
  return {
    ...panel,
    insightTabs: buildInsightTabs(panel),
  }
}
