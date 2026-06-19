import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  availabilitySummary,
  budgetUsageDetails,
  budgetUsageMeta,
  coachReviewSummary,
  eventTypeLabel,
  fallbackPanelSummary,
  failureEventRows,
  matchTeamIdentity,
  scoreAfterText,
  seedShortCode,
} from '../step3Adapters.js'

describe('step3Adapters', () => {
  it('formats simulation seeds as stable five-digit replay codes', () => {
    assert.equal(seedShortCode(123456789), '56789')
    assert.equal(seedShortCode(42), '00042')
    assert.equal(seedShortCode(null), '-')
  })

  it('classifies budget usage at normal, warning, and over-cap thresholds', () => {
    assert.deepEqual(budgetUsageMeta({ total_calls: 7, hard_cap: 10 }), {
      used: 7,
      cap: 10,
      ratio: 0.7,
      className: 'budget-normal',
    })
    assert.equal(budgetUsageMeta({ total_calls: 8, hard_cap: 10 }).className, 'budget-warning')
    assert.equal(budgetUsageMeta({ total_calls: 11, hard_cap: 10 }).className, 'budget-error')
  })

  it('summarizes roster availability for both teams', () => {
    const summary = availabilitySummary({
      teams: [
        {
          role: 'home',
          players: [
            { availability: { status: 'available' } },
            { availability: { status: 'injured' } },
            { availability: { status: 'doubtful' } },
          ],
        },
        {
          role: 'away',
          players: [
            { availability: { status: 'available' } },
            { availability: { status: 'suspended' } },
          ],
        },
      ],
    })

    assert.equal(summary.total, 5)
    assert.deepEqual(summary.home, { total: 3, available: 1 })
    assert.deepEqual(summary.away, { total: 2, available: 1 })
    assert.equal(summary.injured, 1)
    assert.equal(summary.suspended, 1)
    assert.equal(summary.doubtful, 1)
  })

  it('normalizes event labels and score arrays', () => {
    assert.equal(eventTypeLabel('GOAL'), '进球')
    assert.equal(eventTypeLabel('ET_GOAL'), '加时进球')
    assert.equal(eventTypeLabel('VAR_CHECK'), 'VAR')
    assert.equal(eventTypeLabel('UNKNOWN'), 'UNKNOWN')
    assert.equal(scoreAfterText([2, 1]), '2-1')
    assert.equal(scoreAfterText(null), '')
  })

  it('resolves match team identity from run status', () => {
    const identity = matchTeamIdentity({
      statusPayload: {
        match_name: '阿根廷 vs 法国',
        home_team: '阿根廷',
        away_team: '法国',
      },
    })

    assert.equal(identity.home, '阿根廷')
    assert.equal(identity.away, '法国')
    assert.equal(identity.homeLabel, '主队 阿根廷')
    assert.equal(identity.awayLabel, '客队 法国')
    assert.equal(identity.matchupLabel, '阿根廷 vs 法国')
    assert.equal(identity.matchName, '阿根廷 vs 法国')
  })

  it('falls back to config, team strengths, and roster for match team identity', () => {
    assert.deepEqual(
      matchTeamIdentity({
        predictionConfig: {
          home_team: '加拿大',
          away_team: '波黑',
        },
        teamStrengths: [
          { team_role: 'home', team_name: '错误主队' },
          { team_role: 'away', team_name: '错误客队' },
        ],
      }),
      {
        home: '加拿大',
        away: '波黑',
        homeLabel: '主队 加拿大',
        awayLabel: '客队 波黑',
        matchupLabel: '加拿大 vs 波黑',
        matchName: '加拿大 vs 波黑',
      }
    )

    const identity = matchTeamIdentity({
      teamStrengths: [{ team_role: 'home', team_name: '日本' }],
      roster: {
        teams: [{ role: 'away', team_name: '韩国' }],
      },
    })

    assert.equal(identity.home, '日本')
    assert.equal(identity.away, '韩国')
    assert.equal(identity.matchupLabel, '日本 vs 韩国')
  })

  it('keeps legacy coach review consensus fields when present', () => {
    const summary = coachReviewSummary({
      consensus_score: 0.69,
      support_votes: 69,
      oppose_votes: 16,
      abstain_votes: 15,
      confidence_delta: -0.04,
    })

    assert.equal(summary.consensusScore, 0.69)
    assert.equal(summary.supportVotes, 69)
    assert.equal(summary.opposeVotes, 16)
    assert.equal(summary.abstainVotes, 15)
    assert.equal(summary.confidenceDelta, -0.04)
    assert.equal(summary.label, '69%')
    assert.equal(summary.formula, '(69*1 + 15*0.5 + 16*0) / 100')
  })

  it('derives coach review consensus from role verdicts', () => {
    const summary = coachReviewSummary({
      reviews: [
        { role: 'head_coach', verdict: 'support' },
        { role: 'risk', verdict: 'watch' },
        { role: 'attack', verdict: 'watch' },
      ],
    })

    assert.equal(summary.consensusScore, 0.67)
    assert.equal(summary.supportVotes, 1)
    assert.equal(summary.opposeVotes, 0)
    assert.equal(summary.abstainVotes, 2)
    assert.equal(summary.confidenceDelta, 0)
    assert.equal(summary.label, '67%')
    assert.equal(summary.formula, '(1 + 0.5 + 0.5) / 3')
    assert.equal(summary.reviewRows.length, 3)
  })

  it('explains coach review consensus formula and role verdicts', () => {
    const summary = coachReviewSummary(
      {
        source: 'mixed',
        roles: ['head_coach', 'risk'],
        reviews: [
          { role: 'head_coach', verdict: 'support', confidence: 80, rationale: '认可模态轨迹' },
          { role: 'risk', verdict: 'watch', confidence: 72, rationale: '观察红牌风险' },
        ],
      },
      {
        failures: [
          {
            role: 'step3_review_risk',
            reason: 'budget_exceeded',
            fallback: 'coach_review_fallback_v1',
            error: 'LLM call budget exceeded: 12',
          },
        ],
      }
    )

    assert.equal(summary.label, '75%')
    assert.equal(summary.formula, '(1 + 0.5) / 2')
    assert.equal(summary.source, 'mixed')
    assert.equal(summary.reviewRows[1].failure.reason, 'budget_exceeded')
    assert.equal(summary.reviewRows[1].sourceNote, 'budget_exceeded / fallback: coach_review_fallback_v1')
    assert.deepEqual(
      summary.reviewRows.map(row => [row.role, row.verdict, row.weight, row.confidence]),
      [
        ['head_coach', 'support', 1, 80],
        ['risk', 'watch', 0.5, 72],
      ]
    )
  })

  it('summarizes budget usage by role and failure reason', () => {
    const details = budgetUsageDetails({
      total_calls: 12,
      cached: 0,
      spent: 12,
      hard_cap: 12,
      by_role: {
        narrative_polisher: { calls: 12, cached: 0, tokens: 0, cost: 0 },
      },
      failures: [
        { role: 'step3_review_head_coach', reason: 'budget_exceeded', fallback: 'coach_review_fallback_v1' },
        { role: 'analyst_notes', reason: 'budget_exceeded', fallback: 'template' },
        { role: 'narrative_polisher', reason: 'llm_failed', fallback: 'template' },
      ],
    })

    assert.equal(details.usedLabel, '12/12')
    assert.equal(details.remaining, 0)
    assert.equal(details.roleRows[0].role, 'narrative_polisher')
    assert.deepEqual(details.failureReasonRows, [
      { reason: 'budget_exceeded', count: 2 },
      { reason: 'llm_failed', count: 1 },
    ])
    assert.deepEqual(details.failureRoleRows.slice(0, 2), [
      { role: 'analyst_notes', count: 1 },
      { role: 'narrative_polisher', count: 1 },
    ])
  })

  it('matches failure rows to their concrete match events by scenario and occurrence', () => {
    const rows = failureEventRows(
      [
        { role: 'narrative_polisher', reason: 'player_whitelist_failed', fallback: 'template', scenario_key: 'home_normal_away_normal', event_type: 'GOAL' },
        { role: 'narrative_polisher', reason: 'player_whitelist_failed', fallback: 'template', scenario_key: 'home_normal_away_normal', event_type: 'GOAL' },
        { role: 'narrative_polisher', reason: 'llm_failed', fallback: 'template', scenario_key: 'home_normal_away_underperform', event_type: 'SHOT' },
      ],
      [
        { id: 'e1', scenario_key: 'home_normal_away_normal', event_type: 'GOAL', minute: 33, team: '客队', player: 'A', score: '0-1', description: 'A 破门' },
        { id: 'e2', scenario_key: 'home_normal_away_normal', event_type: 'GOAL', minute: 63, team: '主队', player: 'B', score: '1-1', description: 'B 破门' },
      ]
    )

    assert.equal(rows.length, 3)
    assert.equal(rows[0].event.id, 'e1')
    assert.equal(rows[0].eventLabel, "33' 客队 A · GOAL · 0-1")
    assert.equal(rows[1].event.id, 'e2')
    assert.equal(rows[1].eventLabel, "63' 主队 B · GOAL · 1-1")
    assert.equal(rows[2].event, null)
    assert.equal(rows[2].eventLabel, 'home_normal_away_underperform · SHOT')
  })

  it('summarizes fallback rows for current scenario and all scenarios', () => {
    const rows = failureEventRows(
      [
        { role: 'narrative_polisher', reason: 'player_whitelist_failed', fallback: 'template', scenario_key: 'home_normal_away_normal', event_type: 'GOAL' },
        { role: 'narrative_polisher', reason: 'budget_exceeded', fallback: 'template', scenario_key: 'home_overperform_away_normal', event_type: 'SHOT' },
      ],
      [
        { id: 'e1', scenario_key: 'home_normal_away_normal', event_type: 'GOAL', minute: 33, team: '客队', player: 'A' },
        { id: 'e2', scenario_key: 'home_overperform_away_normal', event_type: 'SHOT', minute: 62, team: '主队', player: 'B' },
      ]
    )

    const current = fallbackPanelSummary(rows, 'home_normal_away_normal', false)
    assert.equal(current.total, 2)
    assert.equal(current.visible.length, 1)
    assert.deepEqual(current.reasonRows, [{ reason: 'player_whitelist_failed', count: 1 }])

    const all = fallbackPanelSummary(rows, 'home_normal_away_normal', true)
    assert.equal(all.visible.length, 2)
    assert.deepEqual(all.reasonRows, [
      { reason: 'budget_exceeded', count: 1 },
      { reason: 'player_whitelist_failed', count: 1 },
    ])
  })
})
