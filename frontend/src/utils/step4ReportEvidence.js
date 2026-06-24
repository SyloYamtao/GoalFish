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

const interpolateParams = (template, params = {}) => String(template ?? '').replace(/\{(\w+)\}/g, (match, key) => (
  params[key] === undefined || params[key] === null ? match : String(params[key])
))

const ui = (t, key, fallback, params) => {
  const fallbackText = interpolateParams(fallback, params)
  if (typeof t !== 'function') return fallbackText
  const translated = t(`step4.${key}`, params)
  return translated && translated !== `step4.${key}` ? interpolateParams(translated, params) : fallbackText
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

const teamName = (evidence, role, t) => {
  const config = predictionConfig(evidence)
  if (role === 'home') return config.home_team || ui(t, 'homeTeam', 'Home')
  if (role === 'away') return config.away_team || ui(t, 'awayTeam', 'Away')
  return ''
}

const buildVerdict = ({ evidence, generatedSections, t }) => {
  const config = predictionConfig(evidence)
  const scoreSummary = scorelineSummary(evidence)
  const fallbackScore = extractScoreFromSections(generatedSections)
  const mostLikely = scoreSummary.most_likely_score || fallbackScore.most_likely_score || ''
  const probabilities = asObject(scoreSummary.win_draw_loss_probability)
  const fallbackProbabilities = asObject(fallbackScore.win_draw_loss_probability)
  const homeTeam = config.home_team || ui(t, 'homeTeam', 'Home')
  const awayTeam = config.away_team || ui(t, 'awayTeam', 'Away')
  const parts = scoreParts(mostLikely)
  const title = parts ? `${homeTeam} ${parts[0]}-${parts[1]} ${awayTeam}` : (config.match_name || ui(t, 'verdictPending', 'Match verdict pending'))
  const homeProb = formatProbability(probabilities.home_win ?? fallbackProbabilities.home_win)
  const drawProb = formatProbability(probabilities.draw ?? fallbackProbabilities.draw)
  const awayProb = formatProbability(probabilities.away_win ?? fallbackProbabilities.away_win)

  return {
    eyebrow: config.match_name || `${homeTeam} vs ${awayTeam}`,
    title,
    subtitle: ui(t, 'wdlSubtitle', 'Home win {home} · Draw {draw} · Away win {away}', {
      home: homeProb,
      draw: drawProb,
      away: awayProb,
    }),
  }
}

const externalSourcesCount = sources => {
  if (Array.isArray(sources)) return sources.filter(Boolean).length
  return Object.values(asObject(sources)).filter(Boolean).length
}

const availabilityLabel = (availability, t) => {
  const home = asObject(availability.home)
  const away = asObject(availability.away)
  const homeLabel = `${formatInteger(home.available)}/${formatInteger(home.total)}`
  const awayLabel = `${formatInteger(away.available)}/${formatInteger(away.total)}`
  if (home.available == null && home.total == null && away.available == null && away.total == null) return '-'
  return ui(t, 'availabilityLabel', 'Home {home} · Away {away}', { home: homeLabel, away: awayLabel })
}

const buildModelInputs = (evidence, t) => {
  const context = reportContext(evidence)
  const config = predictionConfig(evidence)
  const budget = budgetCredibility(evidence)
  const dataset = asObject(budget.player_dataset)
  const sourceCount = externalSourcesCount(budget.external_sources ?? context.step1.external_sources)
  const modelLabel = [config.model_name, config.model_version].filter(Boolean).join(' ') || '-'
  const datasetLabel = dataset.players_count
    ? ui(t, 'datasetTeamsPlayers', '{teams} teams / {players} players', {
        teams: formatInteger(dataset.teams_count),
        players: formatInteger(dataset.players_count),
      })
    : (dataset.dataset_id || '-')

  return [
    { label: ui(t, 'model', 'Model'), value: modelLabel },
    { label: ui(t, 'playerAvailability', 'Player availability'), value: availabilityLabel(asObject(budget.player_availability ?? context.step2.player_availability), t) },
    { label: ui(t, 'dataset', 'Dataset'), value: datasetLabel },
    { label: ui(t, 'dataStatus', 'Data status'), value: `${config.fit_status || '-'} / ${config.data_sufficiency || '-'}` },
    { label: ui(t, 'externalSources', 'External sources'), value: sourceCount ? ui(t, 'sourceGroups', '{count} groups', { count: sourceCount }) : '-' },
  ]
}

const buildEvidenceStats = ({ evidence, predictionStatus, t }) => {
  const context = reportContext(evidence)
  const counts = asObject(predictionStatus?.counts)
  return [
    { label: ui(t, 'scoreCandidates', 'Score candidates'), value: formatInteger(evidence.scorelines_count ?? arrayLength(context.step3.scorelines)) },
    { label: ui(t, 'matchEvents', 'Match events'), value: formatInteger(evidence.match_events_count ?? arrayLength(context.step3.events) ?? counts.match_events) },
    { label: ui(t, 'nineScenarios', 'Nine scenarios'), value: formatInteger(counts.scenario_cases ?? evidence.scenario_cases_count ?? arrayLength(context.step3.scenario_cases) ?? 9) },
    { label: ui(t, 'analystNotes', 'Analyst notes'), value: formatInteger(evidence.analyst_notes_count ?? arrayLength(context.step3.analyst_notes)) },
    { label: ui(t, 'coachDiscussions', 'Coach discussions'), value: formatInteger(evidence.coach_discussions_count ?? arrayLength(context.step2.coach_discussions)) },
  ]
}

const buildCredibilityItems = (evidence, t) => {
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
      label: ui(t, 'llmCalls', 'LLM calls'),
      detail: `${totalCalls}/${hardCap} · cached ${cached}`,
      tone: numberValue(ledger.total_calls) > numberValue(ledger.hard_cap ?? profile.hard_cap_calls) ? 'warn' : 'normal',
    },
    {
      label: ui(t, 'degradationRecords', 'Degradation records'),
      detail: failures === '-'
        ? ui(t, 'notRecorded', 'Not recorded')
        : ui(t, 'recordsUnit', '{count} records', { count: failures }),
      tone: numberValue(failuresValue) ? 'warn' : 'normal',
    },
    {
      label: ui(t, 'budgetProfile', 'Budget profile'),
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

const rankingText = (row, t) => {
  const ranking = asObject(row)
  const fifa = ranking.fifa_rank ? `FIFA ${formatInteger(ranking.fifa_rank)}` : ''
  const points = ranking.fifa_points ? ui(t, 'fifaPoints', '{value} pts', { value: formatMetric(ranking.fifa_points) }) : ''
  const elo = ranking.elo_rank ? `Elo ${formatInteger(ranking.elo_rank)}` : ''
  return [fifa, points, elo].filter(Boolean).join(' · ') || '-'
}

const xgValue = value => {
  const num = numberValue(value)
  return num === null ? '-' : num.toFixed(2)
}

const buildProbabilityBars = ({ evidence, generatedSections, t }) => {
  const summary = scorelineSummary(evidence)
  const fallbackScore = extractScoreFromSections(generatedSections)
  const probabilities = asObject(summary.win_draw_loss_probability)
  const fallbackProbabilities = asObject(fallbackScore.win_draw_loss_probability)
  const home = teamName(evidence, 'home', t)
  const away = teamName(evidence, 'away', t)
  const rows = [
    {
      key: 'home_win',
      label: ui(t, 'homeWin', 'Home win'),
      team: home,
      detail: ui(t, 'homeWinDetail', '{team} model win probability.', { team: home }),
      value: probabilities.home_win ?? fallbackProbabilities.home_win,
    },
    {
      key: 'draw',
      label: ui(t, 'draw', 'Draw'),
      team: ui(t, 'draw', 'Draw'),
      detail: ui(t, 'drawDetail', 'Model draw probability. Higher draw probability means guarding against low-score outcomes.'),
      value: probabilities.draw ?? fallbackProbabilities.draw,
    },
    {
      key: 'away_win',
      label: ui(t, 'awayWin', 'Away win'),
      team: away,
      detail: ui(t, 'awayWinDetail', '{team} model win probability.', { team: away }),
      value: probabilities.away_win ?? fallbackProbabilities.away_win,
    },
  ]
  return rows.map(row => ({
    ...row,
    ...probabilityBar(row.value),
  }))
}

const buildTeamComparison = (evidence, t) => {
  const context = reportContext(evidence)
  const strengths = roleStrengths(evidence)
  const rankings = asObject(context.step2.team_rankings)
  const formations = asObject(context.step2.formations)
  const xg = asObject(context.step3.xg)
  return ['home', 'away'].map(role => {
    const row = asObject(strengths[role])
    return {
      key: role,
      team: firstText(row.team_name, teamName(evidence, role, t)),
      formation: firstText(formations[role], '-'),
      ranking: rankingText(rankings[role], t),
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

const scoreCandidateFromItem = (item, index, t) => {
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
    context: firstText(row.scenario, row.scenario_label, row.scenario_space, row.space, ui(t, 'scoreCandidateContext', 'Top score candidate')),
  }
}

const buildScoreCandidates = (evidence, t) => {
  const direct = topScores(evidence)
    .map((item, index) => scoreCandidateFromItem(item, index, t))
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
        context: firstText(item.scenario_label, item.scenario_space, item.xg ? `xG ${item.xg}` : ui(t, 'scenarioCandidateContext', 'Scenario candidate')),
      }
    })
    .filter(Boolean)
    .slice(0, 5)
}

const strongestPlayerTag = (player, t) => {
  const row = asObject(player)
  const metrics = [
    [ui(t, 'metricAttack', 'Attack'), row.attack],
    [ui(t, 'metricDefense', 'Defense'), row.defense],
    [ui(t, 'metricFinishing', 'Finishing'), row.finishing],
    [ui(t, 'metricPassing', 'Passing'), row.passing],
    [ui(t, 'metricOverall', 'Overall'), row.overall],
  ]
    .map(([label, value]) => ({ label, value: numberValue(value) }))
    .filter(item => item.value !== null)
    .sort((a, b) => b.value - a.value)
  return metrics[0] ? `${metrics[0].label} ${formatMetric(metrics[0].value)}` : '-'
}

const buildKeyPlayers = (evidence, t) => {
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
        team: teamName(evidence, role, t),
        name: firstText(row.name, row.full_name, row.name_en, '-'),
        position: firstText(row.position, row.position_primary, row.position_class, '-'),
        overall: formatMetric(row.overall),
        tag: strongestPlayerTag(row, t),
        availability: firstText(row.availability, row.status, '-'),
      })
    })
  }
  return result.slice(0, 8)
}

const buildCoachNotes = (evidence, t) => {
  const context = reportContext(evidence)
  return asArray(context.step2.coach_discussions)
    .map((item, index) => {
      const row = asObject(item)
      return {
        key: `coach-${index}`,
        topic: firstText(row.topic, ui(t, 'coachDiscussion', 'Coach discussion')),
        summary: firstText(row.summary, ui(t, 'unknownMaterial', 'Not specified')),
        consensus: row.consensus_score == null ? '-' : formatMetric(row.consensus_score),
      }
    })
    .filter(item => item.summary !== ui(t, 'unknownMaterial', 'Not specified'))
    .slice(0, 3)
}

const buildScenarioHighlights = (evidence, t) => {
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
        name: firstText(row.space_name, row.scenario, row.scenario_name, row.scenario_space, row.space, ui(t, 'scenario', 'Scenario')),
        weight: formatWeight(row.weight ?? row.final_weight ?? row.probability),
        summary: firstText(row.summary, drivers.slice(0, 2).join('; '), row.xg ? `xG ${row.xg}` : ui(t, 'unknownMaterial', 'Not specified')),
      }
    })
    .slice(0, 5)
}

const eventLabel = (type, t) => {
  const labels = {
    GOAL: ui(t, 'event_GOAL', 'Goal'),
    CHANCE_CREATED: ui(t, 'event_CHANCE_CREATED', 'Chance'),
    SHOT: ui(t, 'event_SHOT', 'Shot'),
    SAVE: ui(t, 'event_SAVE', 'Save'),
    YELLOW_CARD: ui(t, 'event_YELLOW_CARD', 'Yellow card'),
    RED_CARD: ui(t, 'event_RED_CARD', 'Red card'),
    VAR_CHECK: 'VAR',
    SUBSTITUTION: ui(t, 'event_SUBSTITUTION', 'Substitution'),
    PRESSURE_SHIFT: ui(t, 'tempoShift', 'Tempo shift'),
    FINAL_SCORE_HYPOTHESIS: ui(t, 'scoreHypothesis', 'Score hypothesis'),
  }
  return labels[type] || firstText(type, ui(t, 'event', 'Event'))
}

const buildEventTimeline = (evidence, t) => {
  const buckets = timelineBuckets(evidence)
  if (buckets.length) {
    return buckets.slice(0, 4).map((item, index) => {
      const row = asObject(item)
      return {
        key: `timeline-${index}`,
        period: firstText(row.period, '-'),
        trigger: firstText(row.trigger, ui(t, 'unknownTrigger', 'Not specified')),
        event: firstText(row.event, row.description, ui(t, 'unknownMaterial', 'Not specified')),
        scoreImpact: firstText(row.score_impact, row.score, ui(t, 'possibleTempoChange', 'Possible tempo change')),
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
      trigger: selected ? ui(t, 'eventAppears', '{event} appears', { event: eventLabel(row.event_type, t) }) : ui(t, 'unknownTrigger', 'Not specified'),
      event: firstText(row.description, selected ? eventLabel(row.event_type, t) : ui(t, 'unknownMaterial', 'Not specified')),
      scoreImpact: firstText(row.score, ui(t, 'possibleTempoChange', 'Possible tempo change')),
    }
  })
}

const buildEventItems = (evidence, t) => events(evidence)
  .slice(0, 6)
  .map((item, index) => {
    const row = asObject(item)
    return {
      key: `event-${index}`,
      minute: row.minute == null ? '-' : `${row.minute}'`,
      label: firstText(row.event_label, eventLabel(row.event_type, t)),
      team: firstText(row.team, '-'),
      score: firstText(row.score, '-'),
      description: firstText(row.description, ui(t, 'unknownMaterial', 'Not specified')),
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

const buildRiskItems = (evidence, t) => {
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
      label: ui(t, 'injury', 'Injury'),
      signal: injuryCount ? ui(t, 'injurySignal', '{count} injury clues', { count: injuryCount }) : ui(t, 'noClearInjury', 'No clear injury'),
      impact: ui(t, 'injuryImpact', 'Missing starters can move the scoreline toward the opponent or draw.'),
      tone: injuryCount ? 'warn' : 'normal',
    },
    {
      key: 'weather',
      label: ui(t, 'weather', 'Weather'),
      signal: /天气|大雨|小雨|雨|风|高温|湿度/.test(corpus) ? ui(t, 'weatherMentioned', 'Materials mention weather') : ui(t, 'unknownMaterial', 'Not specified'),
      impact: ui(t, 'weatherImpact', 'Bad weather usually lowers tempo and total goals.'),
      tone: /天气|大雨|小雨|雨|风|高温|湿度/.test(corpus) ? 'warn' : 'normal',
    },
    {
      key: 'cards',
      label: ui(t, 'cardsVar', 'Cards/VAR'),
      signal: cardEvents.length ? ui(t, 'cardsSignal', '{count} card/VAR events', { count: cardEvents.length }) : ui(t, 'eventChainNotProminent', 'Event chain not prominent'),
      impact: ui(t, 'cardsImpact', 'Red cards or penalties can quickly change W/D/L direction.'),
      tone: cardEvents.length ? 'warn' : 'normal',
    },
    {
      key: 'fitness',
      label: ui(t, 'fitness', 'Fitness'),
      signal: /体能|疲劳|轮换|换人/.test(corpus) ? ui(t, 'fitnessMentioned', 'Materials mention fitness/rotation') : ui(t, 'fitnessAfter60', 'Mainly after minute 60'),
      impact: ui(t, 'fitnessImpact', 'Fitness drop raises late conceded-goal probability.'),
      tone: /体能|疲劳|轮换|换人/.test(corpus) ? 'warn' : 'normal',
    },
    {
      key: 'lineup',
      label: ui(t, 'lineupChange', 'Lineup changes'),
      signal: lineupCount >= 22 ? ui(t, 'lineupRecorded', 'Expected lineups recorded for both teams') : ui(t, 'lineupIncomplete', 'Lineup data incomplete'),
      impact: ui(t, 'lineupImpact', 'Key-position changes affect shape and matchups.'),
      tone: lineupCount >= 22 ? 'normal' : 'warn',
    },
    {
      key: 'data_gap',
      label: ui(t, 'dataGap', 'Data gaps'),
      signal: warnings.length
        ? ui(t, 'warningRecords', '{count} warning/degradation records', { count: warnings.length })
        : (uncertainty.length ? ui(t, 'uncertaintyFactors', '{count} uncertainty factors', { count: uncertainty.length }) : ui(t, 'noObviousGap', 'No obvious gap')),
      impact: ui(t, 'dataGapImpact', 'More data gaps mean the highest probability should not be treated as certainty.'),
      tone: warnings.length || uncertainty.length ? 'warn' : 'normal',
    },
  ]
}

const buildSourceHighlights = (evidence, t) => {
  const context = reportContext(evidence)
  const budget = budgetCredibility(evidence)
  const dataset = asObject(budget.player_dataset)
  const counts = asObject(context.credibility.data_counts)
  const sourceCount = externalSourcesCount(budget.external_sources ?? context.step1.external_sources)
  return [
    {
      label: ui(t, 'graphSource', 'Graph'),
      value: ui(t, 'graphSourceValue', '{entities} entities · {relationships} relationships', {
        entities: formatInteger(context.step1.graph_entities_count ?? counts.step1_graph_entities),
        relationships: formatInteger(context.step1.graph_relationships_count ?? counts.step1_graph_relationships),
      }),
      detail: 'Step1',
    },
    {
      label: ui(t, 'lineupSource', 'Lineup'),
      value: ui(t, 'lineupSourceValue', '{count} players', { count: formatInteger(counts.step2_lineup_players) }),
      detail: 'Step2',
    },
    {
      label: ui(t, 'simulationSource', 'Simulation'),
      value: ui(t, 'simulationSourceValue', '{scorelines} scorelines · {events} events', {
        scorelines: formatInteger(counts.step3_scorelines ?? scorelines(evidence).length),
        events: formatInteger(counts.step3_match_events ?? events(evidence).length),
      }),
      detail: 'Step3',
    },
    {
      label: ui(t, 'source', 'Source'),
      value: sourceCount ? ui(t, 'externalSourceValue', '{count} external sources', { count: sourceCount }) : ui(t, 'unknownMaterial', 'Not specified'),
      detail: dataset.players_count
        ? ui(t, 'datasetDetail', '{count} players', { count: formatInteger(dataset.players_count) })
        : ui(t, 'datasetDetailFallback', 'Dataset'),
    },
  ]
}

const sectionHint = (title, t) => {
  if (/结论|摘要|conclusion|summary/i.test(title)) return ui(t, 'sectionHintConclusion', 'Match judgment, score tendency, and core rationale')
  if (/基本面|图谱|证据|evidence|graph/i.test(title)) return ui(t, 'sectionHintBasics', 'Team data, injuries, head-to-head context, and evidence sources')
  if (/战术|阵型|首发|tactics|lineup/i.test(title)) return ui(t, 'sectionHintTactics', 'Coach discussion, expected lineups, and attack-defense matchups')
  if (/胜平负|比分|score/i.test(title)) return ui(t, 'sectionHintScore', 'Score probabilities, xG, and most likely result')
  if (/九场景|矩阵|scenario|matrix/i.test(title)) return ui(t, 'sectionHintMatrix', 'Scenario weights, match picture, and state combinations')
  if (/进程|事件|event/i.test(title)) return ui(t, 'sectionHintEvents', 'Baseline event chain and key nodes')
  if (/教练|笔记|coach|note/i.test(title)) return ui(t, 'sectionHintCoach', 'Review opinions, risk, and tactical explanation')
  if (/裁判|不确定|风险|risk|uncertainty/i.test(title)) return ui(t, 'sectionHintRisk', 'VAR, cards, injury exit, and substitution risks')
  if (/预算|可信度|budget|credibility/i.test(title)) return ui(t, 'sectionHintBudget', 'Data sources, call budget, and degradation chain')
  return ui(t, 'sectionHintDefault', 'Report evidence summary')
}

const buildSectionSteps = ({ reportOutline, workflowSteps, t }) => {
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
    hint: sectionHint(step.title || '', t),
  }))
}

const widgetPlayerCount = widgets => {
  const lineup = asObject(widgets?.lineup)
  return asArray(asObject(lineup.home).players).length + asArray(asObject(lineup.away).players).length
}

const buildInsightTabs = (panel, t) => [
  { key: 'overview', label: ui(t, 'tabOverview', 'Overview'), meta: ui(t, 'itemsUnit', '{count} items', { count: panel.sourceHighlights.length }) },
  { key: 'scores', label: ui(t, 'tabScores', 'Scores'), meta: ui(t, 'itemsUnit', '{count} items', { count: panel.scoreCandidates.length || panel.probabilityBars.length }) },
  { key: 'lineups', label: ui(t, 'tabLineups', 'Lineups'), meta: ui(t, 'peopleUnit', '{count} players', { count: widgetPlayerCount(panel.widgets) || panel.keyPlayers.length }) },
  { key: 'events', label: ui(t, 'tabEvents', 'Events'), meta: ui(t, 'segmentsUnit', '{count} periods', { count: panel.eventTimeline.length }) },
  { key: 'risks', label: ui(t, 'tabRisks', 'Risks'), meta: ui(t, 'warningsUnit', '{count} warnings', { count: panel.riskItems.filter(item => item.tone === 'warn').length }) },
]

export const buildStep4ReportEvidence = ({
  reportSnapshot = null,
  predictionStatus = null,
  reportOutline = null,
  generatedSections = {},
  workflowSteps = [],
  statusText = '',
  t,
} = {}) => {
  const metadata = asObject(reportSnapshot?.report_metadata)
  const evidence = asObject(metadata.evidence_package)
  const widgets = normalizeWidgets({ metadata, evidence })
  const panel = {
    statusText,
    widgets,
    verdict: buildVerdict({ evidence, generatedSections, t }),
    modelInputs: buildModelInputs(evidence, t),
    evidenceStats: buildEvidenceStats({ evidence, predictionStatus, t }),
    credibilityItems: buildCredibilityItems(evidence, t),
    probabilityBars: buildProbabilityBars({ evidence, generatedSections, t }),
    teamComparison: buildTeamComparison(evidence, t),
    scoreCandidates: buildScoreCandidates(evidence, t),
    keyPlayers: buildKeyPlayers(evidence, t),
    coachNotes: buildCoachNotes(evidence, t),
    scenarioHighlights: buildScenarioHighlights(evidence, t),
    eventTimeline: buildEventTimeline(evidence, t),
    eventItems: buildEventItems(evidence, t),
    riskItems: buildRiskItems(evidence, t),
    sourceHighlights: buildSourceHighlights(evidence, t),
    sectionSteps: buildSectionSteps({ reportOutline, workflowSteps, t }),
  }
  return {
    ...panel,
    insightTabs: buildInsightTabs(panel, t),
  }
}
