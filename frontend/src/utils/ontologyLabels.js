export const ontologyEntityLabelKeys = {
  FootballTeam: 'ontologyLabels.entities.FootballTeam',
  Player: 'ontologyLabels.entities.Player',
  Coach: 'ontologyLabels.entities.Coach',
  Match: 'ontologyLabels.entities.Match',
  Competition: 'ontologyLabels.entities.Competition',
  Venue: 'ontologyLabels.entities.Venue',
  TacticalFormation: 'ontologyLabels.entities.TacticalFormation',
  Referee: 'ontologyLabels.entities.Referee',
  Person: 'ontologyLabels.entities.Person',
  Organization: 'ontologyLabels.entities.Organization',
}

export const ontologyEdgeLabelKeys = {
  PLAYS_FOR: 'ontologyLabels.relations.PLAYS_FOR',
  COACHED_BY: 'ontologyLabels.relations.COACHED_BY',
  PARTICIPATES_IN: 'ontologyLabels.relations.PARTICIPATES_IN',
  SCHEDULED_AT: 'ontologyLabels.relations.SCHEDULED_AT',
  PART_OF_COMPETITION: 'ontologyLabels.relations.PART_OF_COMPETITION',
  USES_FORMATION: 'ontologyLabels.relations.USES_FORMATION',
  MATCHES_UP_AGAINST: 'ontologyLabels.relations.MATCHES_UP_AGAINST',
  REFEREES: 'ontologyLabels.relations.REFEREES',
  KEY_PLAYER_FOR: 'ontologyLabels.relations.KEY_PLAYER_FOR',
  COMPETES_WITH: 'ontologyLabels.relations.COMPETES_WITH',
}

export function resolveOntologyEntityLabel(entity, t) {
  return resolveOntologyLabelFromMap(entity, t, ontologyEntityLabelKeys)
}

export function resolveOntologyEdgeLabel(edge, t) {
  return resolveOntologyLabelFromMap(edge, t, ontologyEdgeLabelKeys)
}

export function resolveOntologyLabel(item, t) {
  if (!item) return ''
  if (item.name && ontologyEdgeLabelKeys[item.name]) {
    return resolveOntologyEdgeLabel(item, t)
  }
  return resolveOntologyEntityLabel(item, t)
}

function resolveOntologyLabelFromMap(item, t, labelKeys) {
  const key = item?.name ? labelKeys[item.name] : ''
  if (key && typeof t === 'function') {
    const translated = t(key)
    if (translated && translated !== key) return translated
  }
  return item?.display_name || item?.name || ''
}
