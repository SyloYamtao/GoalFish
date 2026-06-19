const SOURCE_LABELS = {
  fitted_blend: '模型融合',
  player: '球员名册',
  injury: '伤停',
  form: '状态',
}

const COMPACT_SOURCE_LABELS = {
  fitted_blend: '模型',
  player: '球员',
  injury: '伤停',
  form: '状态',
}

const normalizeSource = (source) => String(source || '').trim()

export const evidenceSourceLabel = (source) => {
  const normalized = normalizeSource(source)
  if (!normalized) return '-'
  return SOURCE_LABELS[normalized] || normalized.replaceAll('_', ' ')
}

export const compactEvidenceSourceLabel = (source) => {
  const normalized = normalizeSource(source)
  if (!normalized) return '来源'
  return COMPACT_SOURCE_LABELS[normalized] || '来源'
}
