import assert from 'node:assert/strict'
import { afterEach, describe, it } from 'node:test'

import {
  clearPendingPredictionUpload,
  DEFAULT_PREDICTION_REQUIREMENT,
  getPendingPredictionUpload,
  setPendingPredictionUpload,
} from '../../store/pendingUpload.js'

describe('pendingUpload', () => {
  afterEach(() => {
    clearPendingPredictionUpload()
  })

  it('uses the default football prediction requirement when none is provided', () => {
    const file = { name: 'match-report.md' }

    setPendingPredictionUpload([file])

    assert.equal(
      getPendingPredictionUpload().predictionRequirement,
      DEFAULT_PREDICTION_REQUIREMENT
    )
  })

  it('uses the default football prediction requirement for blank input', () => {
    const file = { name: 'match-report.md' }

    setPendingPredictionUpload([file], '   ')

    assert.equal(
      getPendingPredictionUpload().predictionRequirement,
      DEFAULT_PREDICTION_REQUIREMENT
    )
  })
})
