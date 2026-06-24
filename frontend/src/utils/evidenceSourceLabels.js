const SOURCE_LABELS = {
  fitted_blend: 'prediction.source_fitted_blend',
  player: 'prediction.source_player',
  injury: 'prediction.source_injury',
  form: 'prediction.source_form',
}

const COMPACT_SOURCE_LABELS = {
  fitted_blend: 'prediction.source_fitted_blend_compact',
  player: 'prediction.source_player_compact',
  injury: 'prediction.source_injury_compact',
  form: 'prediction.source_form_compact',
}

const FALLBACK_LABELS = {
  'prediction.source_fitted_blend': 'Model blend',
  'prediction.source_player': 'Player roster',
  'prediction.source_injury': 'Injury',
  'prediction.source_form': 'Form',
  'prediction.source_fitted_blend_compact': 'Model',
  'prediction.source_player_compact': 'Player',
  'prediction.source_injury_compact': 'Injury',
  'prediction.source_form_compact': 'Form',
  'common.source': 'Source',
}

const normalizeSource = (source) => String(source || '').trim()
const translate = (t, key) => (typeof t === 'function' ? t(key) : FALLBACK_LABELS[key]) || key

export const evidenceSourceLabel = (source, t) => {
  const normalized = normalizeSource(source)
  if (!normalized) return '-'
  return SOURCE_LABELS[normalized] ? translate(t, SOURCE_LABELS[normalized]) : normalized.replaceAll('_', ' ')
}

export const compactEvidenceSourceLabel = (source, t) => {
  const normalized = normalizeSource(source)
  if (!normalized) return translate(t, 'common.source')
  return COMPACT_SOURCE_LABELS[normalized] ? translate(t, COMPACT_SOURCE_LABELS[normalized]) : translate(t, 'common.source')
}
