export const MAX_LLM_HARD_CAP_CALLS = 130

export const estimateLLMBudgetCalls = (profile = {}) => {
  const raw = (profile.enable_llm_data_extraction ? 1 : 0)
    + (profile.coach_panel_roles || []).length * Number(profile.coach_deliberation_rounds || 1)
    + Number(profile.narrative_polish_count || 0) * 8
    + (profile.analyst_note_groups || []).length
    + (profile.coach_review_roles || []).length * 9
  const cap = Number(profile.hard_cap_calls || profile.hard_cap || raw || 0)
  return cap ? Math.min(raw, cap) : raw
}
