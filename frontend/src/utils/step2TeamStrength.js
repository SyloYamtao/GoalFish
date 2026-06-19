const TEAM_ROLE_ORDER = {
  home: 0,
  away: 1,
}

export const orderTeamStrengths = (teams = []) => [...teams].sort((a, b) => {
  const aOrder = TEAM_ROLE_ORDER[a?.team_role] ?? 99
  const bOrder = TEAM_ROLE_ORDER[b?.team_role] ?? 99
  return aOrder - bOrder
})

export const teamStrengthRatingItems = (team = {}) => ([
  { key: 'attack', label: '进攻', value: team.attack_rating },
  { key: 'defense', label: '防守', value: team.defense_rating },
  { key: 'possession', label: '控球', value: team.possession_rating },
  { key: 'transition', label: '转换', value: team.transition_rating },
  { key: 'set_piece', label: '定位球', value: team.set_piece_rating },
  { key: 'goalkeeper', label: '门将', value: team.goalkeeper_rating },
].map(item => {
  const evidence = team.evidence_breakdown?.[item.key] || {}
  return {
    ...item,
    source: 'player',
    refs: evidence.top_contributors || evidence.refs || [],
  }
}))
