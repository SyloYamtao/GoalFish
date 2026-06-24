import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  compactEvidenceSourceLabel,
  evidenceSourceLabel,
} from '../evidenceSourceLabels.js'

describe('evidenceSourceLabels', () => {
  it('renders internal team-strength sources as readable compact labels', () => {
    assert.equal(evidenceSourceLabel('fitted_blend'), 'Model blend')
    assert.equal(evidenceSourceLabel('player'), 'Player roster')
    assert.equal(compactEvidenceSourceLabel('fitted_blend'), 'Model')
    assert.equal(compactEvidenceSourceLabel('player'), 'Player')
  })

  it('keeps unknown sources out of compact score cells', () => {
    assert.equal(evidenceSourceLabel('custom_feed'), 'custom feed')
    assert.equal(compactEvidenceSourceLabel('custom_feed'), 'Source')
  })

  it('accepts vue-i18n translator functions for UI locale labels', () => {
    const zh = key => ({
      'prediction.source_player': '球员名册',
      'prediction.source_player_compact': '球员',
      'common.source': '来源',
    }[key] || key)

    assert.equal(evidenceSourceLabel('player', zh), '球员名册')
    assert.equal(compactEvidenceSourceLabel('player', zh), '球员')
    assert.equal(compactEvidenceSourceLabel('custom_feed', zh), '来源')
  })
})
