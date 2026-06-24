export const EVENT_LABELS = {
  KICKOFF: ['step3.event_KICKOFF', 'Kickoff'],
  TACTICAL_PHASE: ['step3.event_TACTICAL_PHASE', 'Tactical phase'],
  CHANCE_CREATED: ['step3.event_CHANCE_CREATED', 'Chance'],
  CHANCE: ['step3.event_CHANCE', 'Chance'],
  SHOT: ['step3.event_SHOT', 'Shot'],
  SAVE: ['step3.event_SAVE', 'Save'],
  GOAL: ['step3.event_GOAL', 'Goal'],
  ET_GOAL: ['step3.event_ET_GOAL', 'Extra-time goal'],
  FOUL: ['step3.event_FOUL', 'Foul'],
  CARD: ['step3.event_CARD', 'Card'],
  YELLOW_CARD: ['step3.event_YELLOW_CARD', 'Yellow card'],
  RED_CARD: ['step3.event_RED_CARD', 'Red card'],
  VAR: [null, 'VAR'],
  VAR_CHECK: [null, 'VAR'],
  SUB: ['step3.event_SUB', 'Substitution'],
  SUBSTITUTION: ['step3.event_SUBSTITUTION', 'Substitution'],
  PRESS: ['step3.event_PRESS', 'Press'],
  PRESSURE_SHIFT: ['step3.event_PRESSURE_SHIFT', 'Pressure shift'],
  PSO: ['step3.event_PSO', 'Penalty shootout'],
  FINAL_SCORE_HYPOTHESIS: ['step3.event_FINAL_SCORE_HYPOTHESIS', 'Final score hypothesis'],
}

export const ROLE_LABELS = {
  data: ['step3.role_data', 'Data analyst'],
  tactics: ['step3.role_tactics', 'Tactics analyst'],
  risk: ['step3.role_risk', 'Risk analyst'],
  event_simulation: ['step3.role_event_simulation', 'Event simulation'],
  coach_review: ['step3.role_coach_review', 'Coach review'],
  head_coach: ['step3.role_head_coach', 'Head coach'],
  attack: ['step3.role_attack', 'Attack coach'],
  defense: ['step3.role_defense', 'Defense coach'],
  set_piece: ['step3.role_set_piece', 'Set-piece coach'],
  fitness: ['step3.role_fitness', 'Fitness coach'],
  goalkeeper: ['step3.role_goalkeeper', 'Goalkeeper coach'],
  transition: ['step3.role_transition', 'Transition coach'],
  narrative_polisher: ['step3.role_narrative_polisher', 'Narrative polish'],
  analyst_notes: ['step3.role_analyst_notes', 'Analyst notes'],
  step3_review_head_coach: ['step3.role_step3_review_head_coach', 'Step 3 head-coach review'],
  step3_review_risk: ['step3.role_step3_review_risk', 'Step 3 risk review'],
  step3_review_attack: ['step3.role_step3_review_attack', 'Step 3 attack review'],
}

export const STATE_LABELS = {
  normal: ['step3.state_normal', 'Normal'],
  overperform: ['step3.state_overperform', 'Overperforming'],
  underperform: ['step3.state_underperform', 'Underperforming'],
}

export function seedShortCode(seed) {
  if (seed === undefined || seed === null || seed === '') return '-'
  const numeric = Number(seed)
  if (!Number.isFinite(numeric)) return '-'
  return String(Math.abs(Math.trunc(numeric)) % 100000).padStart(5, '0')
}

export function budgetUsageMeta(ledger = {}) {
  const used = toInt(ledger.total_calls ?? ledger.spent)
  const cap = toInt(ledger.hard_cap ?? ledger.hard_cap_calls)
  const ratio = cap > 0 ? used / cap : 0
  let className = 'budget-normal'
  if (cap > 0 && used > cap) {
    className = 'budget-error'
  } else if (cap > 0 && ratio >= 0.8) {
    className = 'budget-warning'
  }
  return { used, cap, ratio, className }
}

export function availabilitySummary(roster = {}) {
  const blankTeam = { total: 0, available: 0 }
  const result = {
    total: 0,
    home: { ...blankTeam },
    away: { ...blankTeam },
    injured: 0,
    suspended: 0,
    doubtful: 0,
  }

  for (const team of roster.teams || []) {
    const players = Array.isArray(team.players) ? team.players : []
    const role = team.role === 'away' ? 'away' : 'home'
    result[role].total = players.length
    result.total += players.length

    for (const player of players) {
      const status = normalizedAvailability(player)
      if (status === 'available' || status === 'ok') result[role].available += 1
      if (status === 'injured') result.injured += 1
      if (status === 'suspended') result.suspended += 1
      if (status === 'doubtful' || status === 'doubt') result.doubtful += 1
    }
  }

  return result
}

export function normalizedAvailability(player = {}) {
  const raw = player.availability?.status ?? player.status ?? 'available'
  return String(raw || 'available').toLowerCase()
}

export function eventTypeLabel(type, t) {
  return translatedLookup(EVENT_LABELS[type], t) || type || '-'
}

export function roleLabel(role, t) {
  return translatedLookup(ROLE_LABELS[role], t) || role || '-'
}

export function stateLabel(state, t) {
  return translatedLookup(STATE_LABELS[state], t) || state || '-'
}

export function scoreAfterText(scoreAfter) {
  if (!Array.isArray(scoreAfter) || scoreAfter.length < 2) return ''
  return `${scoreAfter[0]}-${scoreAfter[1]}`
}

export function matchTeamIdentity({
  statusPayload = {},
  predictionConfig = {},
  predictionResult = {},
  teamStrengths = [],
  roster = {},
  t,
} = {}) {
  const resultConfig = predictionResult?.metadata?.prediction_config || {}
  const metadata = predictionResult?.metadata || {}
  const sources = [statusPayload, predictionConfig, resultConfig, metadata]
  const homeStrength = teamStrengths.find(team => team?.team_role === 'home') || {}
  const awayStrength = teamStrengths.find(team => team?.team_role === 'away') || {}
  const homeRoster = (roster.teams || []).find(team => team?.role === 'home') || {}
  const awayRoster = (roster.teams || []).find(team => team?.role === 'away') || {}

  const home = firstText([
    ...sources.map(source => source?.home_team),
    homeStrength.team_name,
    homeRoster.team_name,
    homeRoster.name,
  ]) || translate(t, 'prediction.homeTeam', 'Home')
  const away = firstText([
    ...sources.map(source => source?.away_team),
    awayStrength.team_name,
    awayRoster.team_name,
    awayRoster.name,
  ]) || translate(t, 'prediction.awayTeam', 'Away')
  const matchName = firstText(sources.map(source => source?.match_name)) || `${home} vs ${away}`

  return {
    home,
    away,
    homeLabel: translate(t, 'step3.homeLabelWithTeam', 'Home {team}', { team: home }),
    awayLabel: translate(t, 'step3.awayLabelWithTeam', 'Away {team}', { team: away }),
    matchupLabel: `${home} vs ${away}`,
    matchName,
  }
}

export function formatPercent(value) {
  if (value === undefined || value === null || value === '') return '-'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${Math.round((numeric <= 1 ? numeric * 100 : numeric))}%`
}

export function formatDecimal(value, digits = 2) {
  if (value === undefined || value === null || value === '') return '-'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return numeric.toFixed(digits)
}

export function formatMs(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return '-'
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}s`
  return `${Math.round(numeric)}ms`
}

export function coachReviewSummary(review = {}, ledger = {}, t) {
  if (!review || typeof review !== 'object') {
    return {
      consensusScore: null,
      supportVotes: 0,
      opposeVotes: 0,
      abstainVotes: 0,
      confidenceDelta: 0,
      label: '-',
    }
  }

  const reviews = Array.isArray(review.reviews) ? review.reviews : []
  const failuresByRole = reviewFailureIndex(ledger)
  const reviewRows = reviews.map(item => {
    const verdict = String(item?.verdict || 'watch')
    const role = String(item?.role || '-')
    const failure = failuresByRole.get(role) || null
    return {
      role,
      roleLabel: roleLabel(item?.role, t),
      verdict,
      verdictLabel: verdictLabel(verdict, t),
      weight: verdictWeight(verdict),
      confidence: Number.isFinite(Number(item?.confidence)) ? Number(item.confidence) : null,
      rationale: String(item?.rationale || ''),
      source: item?.source || review.source || '-',
      sourceNote: sourceNote(item?.source || review.source, failure, t),
      failure,
      evidenceRefs: Array.isArray(item?.evidence_refs) ? item.evidence_refs : [],
    }
  })
  const derivedVotes = reviews.reduce(
    (acc, item) => {
      const verdict = String(item?.verdict || 'watch')
      if (verdict === 'support') acc.supportVotes += 1
      else if (verdict === 'reject') acc.opposeVotes += 1
      else acc.abstainVotes += 1
      return acc
    },
    { supportVotes: 0, opposeVotes: 0, abstainVotes: 0 }
  )

  const supportVotes = valueOr(review.support_votes, derivedVotes.supportVotes)
  const opposeVotes = valueOr(review.oppose_votes, derivedVotes.opposeVotes)
  const abstainVotes = valueOr(review.abstain_votes, derivedVotes.abstainVotes)
  const totalVotes = supportVotes + opposeVotes + abstainVotes
  const derivedConsensus = totalVotes > 0
    ? (supportVotes + abstainVotes * 0.5) / totalVotes
    : null
  const consensusScore = normalizeRatio(
    review.consensus_score !== undefined ? review.consensus_score : derivedConsensus
  )
  const confidenceDelta = Number.isFinite(Number(review.confidence_delta))
    ? Number(review.confidence_delta)
    : opposeVotes > 0 ? -0.04 : 0

  return {
    consensusScore: consensusScore === null ? null : roundRatio(consensusScore),
    supportVotes,
    opposeVotes,
    abstainVotes,
    confidenceDelta,
    source: review.source || '-',
    roles: Array.isArray(review.roles) ? review.roles : [],
    summary: String(review.summary || ''),
    formula: totalVotes > 0 ? weightedVoteFormula(supportVotes, abstainVotes, opposeVotes) : '-',
    reviewRows,
    label: consensusScore === null ? '-' : `${Math.round(consensusScore * 100)}%`,
  }
}

export function budgetUsageDetails(ledger = {}, t) {
  const used = toInt(ledger.total_calls ?? ledger.calls_used ?? ledger.spent)
  const spent = toInt(ledger.spent ?? used)
  const cached = toInt(ledger.cached ?? ledger.calls_cached)
  const cap = toInt(ledger.hard_cap ?? ledger.hard_cap_calls)
  const remaining = Math.max(0, cap - used)
  const byRole = ledger.by_role && typeof ledger.by_role === 'object' ? ledger.by_role : {}
  const roleRows = Object.entries(byRole)
    .map(([role, item]) => {
      const payload = item && typeof item === 'object' ? item : {}
      return {
        role,
        roleLabel: roleLabel(role, t),
        calls: toInt(payload.calls),
        cached: toInt(payload.cached),
        fresh: Math.max(0, toInt(payload.calls) - toInt(payload.cached)),
        tokens: toInt(payload.tokens),
        p95Ms: toInt(payload.p95_ms),
      }
    })
    .sort((a, b) => b.calls - a.calls || a.role.localeCompare(b.role))

  const failures = Array.isArray(ledger.failures) ? ledger.failures.filter(Boolean) : []
  return {
    used,
    spent,
    cached,
    cap,
    remaining,
    usedLabel: cap > 0 ? `${used}/${cap}` : `${used}/-`,
    totalTokens: toInt(ledger.total_tokens),
    avgLatencyMs: toInt(ledger.avg_latency_ms),
    p95LatencyMs: toInt(ledger.p95_latency_ms),
    roleRows,
    failures,
    failureReasonRows: countBy(failures, 'reason'),
    failureRoleRows: countBy(failures, 'role'),
  }
}

export function failureEventRows(failures = [], events = [], t) {
  const eventBuckets = new Map()
  for (const event of events || []) {
    const key = failureEventKey(event?.scenario_key || event?.metadata?.scenario_key, event?.event_type)
    if (!key) continue
    if (!eventBuckets.has(key)) eventBuckets.set(key, [])
    eventBuckets.get(key).push(event)
  }

  for (const bucket of eventBuckets.values()) {
    bucket.sort((a, b) => Number(a?.minute || 0) - Number(b?.minute || 0))
  }

  const occurrenceByKey = new Map()
  return (failures || []).filter(Boolean).map((failure, index) => {
    const key = failureEventKey(failure?.scenario_key, failure?.event_type)
    const occurrence = (occurrenceByKey.get(key) || 0)
    occurrenceByKey.set(key, occurrence + 1)
    const event = key ? (eventBuckets.get(key) || [])[occurrence] || null : null
    return {
      id: `${failure?.role || 'failure'}-${failure?.reason || 'unknown'}-${index}`,
      index: index + 1,
      failure,
      event,
      eventLabel: event ? eventFailureLabel(event) : fallbackFailureLabel(failure),
      fallbackLabel: failure?.fallback
        ? translate(t, 'step3.fallbackLabel', 'fallback: {fallback}', { fallback: failure.fallback })
        : translate(t, 'step3.fallbackNoInfo', 'No fallback info'),
    }
  })
}

export function fallbackPanelSummary(rows = [], selectedScenarioKey = '-', showAll = false) {
  const allRows = (rows || []).filter(Boolean)
  const visible = showAll
    ? allRows
    : allRows.filter(row => row.failure?.scenario_key === selectedScenarioKey || row.event?.scenario_key === selectedScenarioKey)

  return {
    total: allRows.length,
    visible,
    currentCount: allRows.filter(row => row.failure?.scenario_key === selectedScenarioKey || row.event?.scenario_key === selectedScenarioKey).length,
    reasonRows: countBy(visible.map(row => row.failure || {}), 'reason'),
  }
}

export function topGoalShareIds(roster = {}, count = 2) {
  return (roster.teams || [])
    .flatMap(team => team.players || [])
    .map(player => ({
      id: player.id,
      goalShare: Number(player.actor_stats?.goal_share || 0),
    }))
    .filter(item => item.id && item.goalShare > 0)
    .sort((a, b) => b.goalShare - a.goalShare)
    .slice(0, count)
    .map(item => item.id)
}

function toInt(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.max(0, Math.trunc(numeric))
}

function firstText(values = []) {
  for (const value of values) {
    if (value === undefined || value === null) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

function failureEventKey(scenarioKey, eventType) {
  const scenario = firstText([scenarioKey])
  const type = firstText([eventType])
  return scenario && type ? `${scenario}::${type}` : ''
}

function eventFailureLabel(event = {}) {
  const leading = [
    event.minute !== undefined && event.minute !== null ? `${event.minute}'` : '',
    event.team,
    event.player,
  ].filter(Boolean).join(' ')
  const trailing = [event.event_type, event.score].filter(Boolean).join(' · ')
  return [leading, trailing].filter(Boolean).join(' · ') || '-'
}

function fallbackFailureLabel(failure = {}) {
  return [failure?.scenario_key, failure?.event_type].filter(Boolean).join(' · ') || '-'
}

function valueOr(value, fallback) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return Math.max(0, Math.trunc(numeric))
}

function normalizeRatio(value) {
  if (value === undefined || value === null || value === '') return null
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return null
  if (numeric > 1) return Math.max(0, Math.min(1, numeric / 100))
  return Math.max(0, Math.min(1, numeric))
}

function roundRatio(value) {
  return Math.round(value * 100) / 100
}

function verdictWeight(verdict) {
  if (verdict === 'support') return 1
  if (verdict === 'reject') return 0
  return 0.5
}

function verdictLabel(verdict, t) {
  return translatedLookup({
    support: ['step3.verdict_support', 'Support'],
    adjust: ['step3.verdict_adjust', 'Adjust / watch'],
    watch: ['step3.verdict_watch', 'Watch'],
    reject: ['step3.verdict_reject', 'Reject'],
  }[verdict], t) || verdict || '-'
}

function weightedVoteFormula(supportVotes, abstainVotes, opposeVotes) {
  const totalVotes = supportVotes + abstainVotes + opposeVotes
  if (totalVotes <= 4) {
    const parts = []
    for (let index = 0; index < supportVotes; index += 1) parts.push('1')
    for (let index = 0; index < abstainVotes; index += 1) parts.push('0.5')
    for (let index = 0; index < opposeVotes; index += 1) parts.push('0')
    return `(${parts.length ? parts.join(' + ') : '0'}) / ${totalVotes}`
  }

  return `(${supportVotes}*1 + ${abstainVotes}*0.5 + ${opposeVotes}*0) / ${totalVotes}`
}

function countBy(items, key) {
  const counts = new Map()
  for (const item of items) {
    const value = String(item?.[key] || '-')
    counts.set(value, (counts.get(value) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ [key]: value, count }))
    .sort((a, b) => b.count - a.count || String(a[key]).localeCompare(String(b[key])))
}

function reviewFailureIndex(ledger = {}) {
  const failures = Array.isArray(ledger.failures) ? ledger.failures : []
  const index = new Map()
  for (const failure of failures) {
    const role = String(failure?.role || '')
    if (!role.startsWith('step3_review_')) continue
    index.set(role.replace('step3_review_', ''), failure)
  }
  return index
}

function sourceNote(source, failure, t) {
  if (failure?.reason || failure?.fallback) {
    return `${failure.reason || translate(t, 'step3.failureDefault', 'failed')}${failure.fallback ? ` / fallback: ${failure.fallback}` : ''}`
  }
  return source || '-'
}

function translatedLookup(entry, t) {
  if (!entry) return ''
  const [key, fallback] = Array.isArray(entry) ? entry : [null, entry]
  return key ? translate(t, key, fallback) : fallback
}

function interpolateParams(template, params = {}) {
  return String(template ?? '').replace(/\{(\w+)\}/g, (match, key) => (
    params[key] === undefined || params[key] === null ? match : String(params[key])
  ))
}

function translate(t, key, fallback, params) {
  const fallbackText = interpolateParams(fallback, params)
  if (typeof t !== 'function') return fallbackText
  const translated = t(key, params)
  return translated && translated !== key ? interpolateParams(translated, params) : fallbackText
}
