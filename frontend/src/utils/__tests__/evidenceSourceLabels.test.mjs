import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  compactEvidenceSourceLabel,
  evidenceSourceLabel,
} from '../evidenceSourceLabels.js'

describe('evidenceSourceLabels', () => {
  it('renders internal team-strength sources as readable compact labels', () => {
    assert.equal(evidenceSourceLabel('fitted_blend'), '模型融合')
    assert.equal(evidenceSourceLabel('player'), '球员名册')
    assert.equal(compactEvidenceSourceLabel('fitted_blend'), '模型')
    assert.equal(compactEvidenceSourceLabel('player'), '球员')
  })

  it('keeps unknown sources out of compact score cells', () => {
    assert.equal(evidenceSourceLabel('custom_feed'), 'custom feed')
    assert.equal(compactEvidenceSourceLabel('custom_feed'), '来源')
  })
})
