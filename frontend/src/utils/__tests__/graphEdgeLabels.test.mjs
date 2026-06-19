import test from 'node:test'
import assert from 'node:assert/strict'

import {
  LARGE_GRAPH_EDGE_THRESHOLD,
  LARGE_GRAPH_NODE_THRESHOLD,
  canRenderEdgeLabels,
  isLargeGraphData,
  shouldRenderEdgeLabels,
} from '../graphEdgeLabels.js'

test('classifies graphs above node or edge thresholds as large', () => {
  assert.equal(isLargeGraphData({
    node_count: LARGE_GRAPH_NODE_THRESHOLD + 1,
    edge_count: 2,
  }), true)

  assert.equal(isLargeGraphData({
    node_count: 2,
    edge_count: LARGE_GRAPH_EDGE_THRESHOLD + 1,
  }), true)

  assert.equal(isLargeGraphData({
    node_count: LARGE_GRAPH_NODE_THRESHOLD,
    edge_count: LARGE_GRAPH_EDGE_THRESHOLD,
  }), false)
})

test('allows edge labels for non-sampled graphs even when they have more than 500 edges', () => {
  assert.equal(shouldRenderEdgeLabels({
    showEdgeLabels: true,
    sampled: false,
    edgeCount: 501,
  }), true)
})

test('creates edge label elements for non-sampled graphs even when the toggle starts off', () => {
  assert.equal(canRenderEdgeLabels({
    sampled: false,
    showEdgeLabels: false,
  }), true)
})

test('does not render edge labels when the graph is sampled or the toggle is off', () => {
  assert.equal(shouldRenderEdgeLabels({
    showEdgeLabels: true,
    sampled: true,
  }), false)

  assert.equal(shouldRenderEdgeLabels({
    showEdgeLabels: false,
    sampled: false,
  }), false)
})
