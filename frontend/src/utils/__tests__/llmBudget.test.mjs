import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { estimateLLMBudgetCalls, MAX_LLM_HARD_CAP_CALLS } from '../llmBudget.js'

const maxProfile = {
  coach_panel_roles: ['head_coach', 'attack', 'defense', 'transition', 'set_piece', 'goalkeeper', 'fitness', 'risk'],
  coach_deliberation_rounds: 3,
  enable_llm_data_extraction: true,
  narrative_polish_count: 9,
  analyst_note_groups: ['baseline', 'home_upside', 'away_upside', 'home_error', 'away_error', 'volatility'],
  coach_review_roles: ['head_coach', 'risk', 'attack'],
  hard_cap_calls: MAX_LLM_HARD_CAP_CALLS,
}

describe('llm budget helpers', () => {
  it('allows the full custom maximum without clipping below the plan', () => {
    assert.equal(MAX_LLM_HARD_CAP_CALLS, 130)
    assert.equal(estimateLLMBudgetCalls(maxProfile), 130)
  })

  it('clips display estimates to the selected hard cap', () => {
    assert.equal(estimateLLMBudgetCalls({ ...maxProfile, hard_cap_calls: 40 }), 40)
  })
})
