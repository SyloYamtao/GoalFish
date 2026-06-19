export const EVENT_LABELS = {
  KICKOFF: '开球',
  TACTICAL_PHASE: '战术阶段',
  CHANCE_CREATED: '机会',
  CHANCE: '机会',
  SHOT: '射门',
  SAVE: '扑救',
  GOAL: '进球',
  ET_GOAL: '加时进球',
  FOUL: '犯规',
  CARD: '牌',
  YELLOW_CARD: '黄牌',
  RED_CARD: '红牌',
  VAR: 'VAR',
  VAR_CHECK: 'VAR',
  SUB: '换人',
  SUBSTITUTION: '换人',
  PRESS: '压迫',
  PRESSURE_SHIFT: '压力',
  PSO: '点球',
  FINAL_SCORE_HYPOTHESIS: '终局假设',
}

export const ROLE_LABELS = {
  data: '数据研判',
  tactics: '战术研判',
  risk: '风险研判',
  event_simulation: '事件推演',
  coach_review: '教练复核',
  head_coach: '战术主教练',
  attack: '进攻教练',
  defense: '防守教练',
  set_piece: '定位球教练',
  fitness: '体能教练',
  goalkeeper: '门将教练',
  transition: '转换教练',
  narrative_polisher: '事件叙述润色',
  analyst_notes: '分析笔记',
  step3_review_head_coach: 'Step3 主教练复核',
  step3_review_risk: 'Step3 风险复核',
  step3_review_attack: 'Step3 进攻复核',
}

export const STATE_LABELS = {
  normal: '正常',
  overperform: '超常',
  underperform: '低迷',
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

export function eventTypeLabel(type) {
  return EVENT_LABELS[type] || type || '-'
}

export function roleLabel(role) {
  return ROLE_LABELS[role] || role || '-'
}

export function stateLabel(state) {
  return STATE_LABELS[state] || state || '-'
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
  ]) || '主队'
  const away = firstText([
    ...sources.map(source => source?.away_team),
    awayStrength.team_name,
    awayRoster.team_name,
    awayRoster.name,
  ]) || '客队'
  const matchName = firstText(sources.map(source => source?.match_name)) || `${home} vs ${away}`

  return {
    home,
    away,
    homeLabel: `主队 ${home}`,
    awayLabel: `客队 ${away}`,
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

export function coachReviewSummary(review = {}, ledger = {}) {
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
      roleLabel: roleLabel(item?.role),
      verdict,
      verdictLabel: verdictLabel(verdict),
      weight: verdictWeight(verdict),
      confidence: Number.isFinite(Number(item?.confidence)) ? Number(item.confidence) : null,
      rationale: String(item?.rationale || ''),
      source: item?.source || review.source || '-',
      sourceNote: sourceNote(item?.source || review.source, failure),
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

export function budgetUsageDetails(ledger = {}) {
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
        roleLabel: roleLabel(role),
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

export function failureEventRows(failures = [], events = []) {
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
      fallbackLabel: failure?.fallback ? `fallback: ${failure.fallback}` : '无 fallback 信息',
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

function verdictLabel(verdict) {
  return {
    support: '支持',
    adjust: '调整观察',
    watch: '观察',
    reject: '反对',
  }[verdict] || verdict || '-'
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

function sourceNote(source, failure) {
  if (failure?.reason || failure?.fallback) {
    return `${failure.reason || 'failed'}${failure.fallback ? ` / fallback: ${failure.fallback}` : ''}`
  }
  return source || '-'
}
