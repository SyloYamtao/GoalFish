const TEAM_ROLE_ORDER = {
  home: 0,
  away: 1,
}

export const orderTeamStrengths = (teams = []) => [...teams].sort((a, b) => {
  const aOrder = TEAM_ROLE_ORDER[a?.team_role] ?? 99
  const bOrder = TEAM_ROLE_ORDER[b?.team_role] ?? 99
  return aOrder - bOrder
})

const fallbackT = (key) => ({
  'step2.rating_attack': 'Attack',
  'step2.rating_defense': 'Defense',
  'step2.rating_possession': 'Possession',
  'step2.rating_transition': 'Transition',
  'step2.rating_set_piece': 'Set pieces',
  'step2.rating_goalkeeper': 'Goalkeeper',
}[key] || key)

export const teamStrengthRatingItems = (team = {}, t = fallbackT) => ([
  { key: 'attack', label: t('step2.rating_attack'), value: team.attack_rating },
  { key: 'defense', label: t('step2.rating_defense'), value: team.defense_rating },
  { key: 'possession', label: t('step2.rating_possession'), value: team.possession_rating },
  { key: 'transition', label: t('step2.rating_transition'), value: team.transition_rating },
  { key: 'set_piece', label: t('step2.rating_set_piece'), value: team.set_piece_rating },
  { key: 'goalkeeper', label: t('step2.rating_goalkeeper'), value: team.goalkeeper_rating },
].map(item => {
  const evidence = team.evidence_breakdown?.[item.key] || {}
  return {
    ...item,
    source: 'player',
    refs: evidence.top_contributors || evidence.refs || [],
  }
}))
