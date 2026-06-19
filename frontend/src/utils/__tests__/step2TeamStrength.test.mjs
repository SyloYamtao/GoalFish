import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  orderTeamStrengths,
  teamStrengthRatingItems,
} from '../step2TeamStrength.js'

describe('step2TeamStrength', () => {
  it('keeps the home team on the left before the away team', () => {
    const ordered = orderTeamStrengths([
      { team_role: 'away', team_name: '埃及' },
      { team_role: 'home', team_name: '比利时' },
    ])

    assert.deepEqual(ordered.map(team => team.team_role), ['home', 'away'])
    assert.equal(ordered[0].team_name, '比利时')
    assert.equal(ordered[1].team_name, '埃及')
  })

  it('renders every strength dimension as player evidence in compact score cells', () => {
    const items = teamStrengthRatingItems({
      attack_rating: 71,
      defense_rating: 68,
      possession_rating: 66,
      transition_rating: 64,
      set_piece_rating: 62,
      goalkeeper_rating: 70,
      evidence_breakdown: {
        attack: {
          source: 'fitted_blend',
          top_contributors: [{ id: 'atk-1', name: '攻击手' }],
        },
        defense: {
          source: 'fitted_blend',
          refs: [{ id: 'def-1', name: '中卫' }],
        },
      },
    })

    assert.deepEqual(items.map(item => item.source), [
      'player',
      'player',
      'player',
      'player',
      'player',
      'player',
    ])
    assert.deepEqual(items.map(item => item.key), [
      'attack',
      'defense',
      'possession',
      'transition',
      'set_piece',
      'goalkeeper',
    ])
    assert.equal(items[0].refs[0].name, '攻击手')
    assert.equal(items[1].refs[0].name, '中卫')
  })
})
